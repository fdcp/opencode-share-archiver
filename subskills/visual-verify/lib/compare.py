"""
compare.py — Core comparison library for visual-verify subskill.

Public API:
    extract_fields(html_path, browser) -> dict
    dom_diff(new_map, old_map) -> dict
    check_dom_fields(new_fields, old_fields) -> list[dict]
    check_visual(screenshots_dir, new_html, old_html, browser) -> list[dict]
    compare_versions(new_html, old_html, outdir, options) -> dict
"""

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path


# ── DOM field extraction ──────────────────────────────────────────────────────

EXTRACT_JS = """() => {
    const h1 = document.querySelector('h1')?.textContent?.trim() || '';
    const meta = document.querySelector('.page-header .meta')?.textContent?.trim() || '';
    const stats = [...document.querySelectorAll('.stat')].map(s => s.textContent.trim());

    const turn0 = document.querySelector('#turn-0');
    const userRole = turn0?.querySelector('.user-role')?.textContent?.trim() || '';
    const userMetaEl = turn0?.querySelector('.msg-meta')?.textContent?.trim() || '';
    const userText = turn0?.querySelector('.msg-text')?.textContent?.trim().substring(0, 80) || '';

    let shellLabel = '';
    for (const el of document.querySelectorAll('.tool-part')) {
        const lbl = el.querySelector('.part-label')?.textContent?.trim() || '';
        if (lbl.startsWith('Shell:')) { shellLabel = lbl; break; }
    }

    const calledLabels = [];
    for (const el of document.querySelectorAll('.tool-part')) {
        const lbl = el.querySelector('.part-label')?.textContent?.trim() || '';
        if (!lbl.startsWith('Shell:') && (lbl.includes('call_omo_agent') || lbl.includes('session_') || lbl.includes('background_'))) {
            calledLabels.push(lbl);
            if (calledLabels.length >= 3) break;
        }
    }

    const fileTools = [];
    for (const el of document.querySelectorAll('.tool-part')) {
        const lbl = el.querySelector('.part-label')?.textContent?.trim() || '';
        const out = el.querySelector('pre.tool-output')?.textContent?.trim() || '';
        if (out.includes('\u202a')) {
            fileTools.push({ label: lbl, output: out.substring(0, 120) });
            if (fileTools.length >= 3) break;
        }
    }

    const hasReasoning = !!document.querySelector('.reasoning-part');
    const reasoningCollapsible = !!document.querySelector('.reasoning-part details, .reasoning-part [data-collapsible]');

    const textPartMeta = !!document.querySelector('.text-part-meta');

    // Functional: TOC checks
    const tocLinks = [...document.querySelectorAll('.toc a[href^="#"]')];
    const tocCount = tocLinks.length;
    const turnCount = document.querySelectorAll('.turn[id]').length;
    const brokenTocLinks = tocLinks
        .filter(a => !document.getElementById(a.getAttribute('href').slice(1)))
        .map(a => a.getAttribute('href'));
    const tocLinksWithNewlineInTitle = tocLinks
        .filter(a => /[\\n\\r\\u2028\\u2029]/.test(a.getAttribute('title') || '')
                  || /[\\n\\r\\u2028\\u2029]/.test(a.textContent || ''))
        .map(a => a.getAttribute('href'));

    // Functional: search input present
    const hasSearchBox = !!document.querySelector('#searchInput');

    // Functional: all turns rendered (turn elements have at least one child)
    const emptyTurns = [...document.querySelectorAll('.turn[id]')]
        .filter(t => t.children.length <= 1)
        .map(t => t.id);

    // Functional: no duplicate turn IDs
    const allTurnIds = [...document.querySelectorAll('.turn[id]')].map(t => t.id);
    const duplicateTurnIds = allTurnIds.filter((id, i) => allTurnIds.indexOf(id) !== i);

    return {
        h1, meta, stats, userRole, userMetaEl, userText,
        shellLabel, calledLabels, fileTools,
        hasReasoning, reasoningCollapsible, textPartMeta,
        tocCount, turnCount, brokenTocLinks, tocLinksWithNewlineInTitle,
        hasSearchBox, emptyTurns, duplicateTurnIds
    };
}"""

SCREENSHOT_REGIONS = [
    ("header",     "document.querySelector('.page-header')",           "页面顶部 header meta + 统计条"),
    ("toc",        "document.querySelector('.toc, #toc, .sidebar')",   "目录区域"),
    ("turn1_user", "document.querySelector('#turn-0 .user-msg')",      "用户消息区（turn 0）"),
    ("shell_tool", "(() => { for (const e of document.querySelectorAll('.tool-part')) { if (e.querySelector('.part-label')?.textContent?.includes('Shell:')) return e; } return null; })()", "第一个 Shell 工具"),
    ("file_tool",  "(() => { for (const e of document.querySelectorAll('.tool-part')) { const o = e.querySelector('pre.tool-output')?.textContent || ''; if (o.includes('\u202a')) return e; } return null; })()", "第一个文件工具"),
    ("reasoning",  "document.querySelector('.reasoning-part')",        "Thinking/Reasoning 区"),
    ("text_part",  "document.querySelector('.text-part')",             "Text 区（markdown 渲染）"),
]


async def _open_page(browser, html_path: str):
    page = await browser.new_page(viewport={"width": 1200, "height": 900})
    await page.goto(f"file://{html_path}")
    await page.wait_for_load_state("networkidle")
    time.sleep(1)
    return page


async def extract_fields(html_path: str, browser) -> dict:
    """Render html_path in browser and extract structured DOM fields."""
    page = await _open_page(browser, html_path)
    fields = await page.evaluate(EXTRACT_JS)
    await page.close()
    return fields


async def take_screenshots(html_path: str, prefix: str, outdir: Path, browser) -> dict:
    """Screenshot key regions of html_path. Returns {region_name: path_str}."""
    page = await _open_page(browser, html_path)
    saved = {}
    for name, selector_js, _ in SCREENSHOT_REGIONS:
        out_path = outdir / f"{prefix}_{name}.png"
        try:
            element = await page.evaluate_handle(selector_js)
            if element:
                el = element.as_element()
                if el:
                    await el.screenshot(path=str(out_path))
                    saved[name] = str(out_path)
                    continue
        except Exception:
            pass
        # fallback: full page viewport crop not available — skip region
        saved[name] = None
    await page.close()
    return saved


# ── DOM map diff ──────────────────────────────────────────────────────────────

def dom_diff(new_map: dict, old_map: dict) -> dict:
    """Compare two dom_map.json dicts. Returns added/removed slot+component keys."""
    new_keys = set(new_map.keys())
    old_keys = set(old_map.keys()) if old_map else set()
    return {
        "added":   sorted(new_keys - old_keys),
        "removed": sorted(old_keys - new_keys),
    }


# ── DOM field checks ──────────────────────────────────────────────────────────

def _check(id_, name, result, new_val, old_val, explanation) -> dict:
    return {
        "id": id_,
        "name": name,
        "result": result,
        "new_value": str(new_val),
        "old_value": str(old_val) if old_val is not None else "n/a",
        "explanation": explanation,
    }


def check_html_integrity(new_fields: dict, new_shots: dict) -> dict:
    """
    Summarize whether the rendered HTML looks complete enough for review.

    This is a top-level structural check that bundles the core signals the
    completeness page depends on: title/meta/stats, turn structure, TOC
    coherence, search box presence, and screenshot coverage.
    """
    missing = []

    if not str(new_fields.get("h1", "")).strip():
        missing.append("h1 missing")
    if not str(new_fields.get("meta", "")).strip():
        missing.append("header meta missing")

    stats = new_fields.get("stats", []) or []
    if len(stats) < 2:
        missing.append(f"stats incomplete ({len(stats)}/2)")

    toc_count = int(new_fields.get("tocCount", 0) or 0)
    turn_count = int(new_fields.get("turnCount", 0) or 0)
    if toc_count <= 0:
        missing.append("TOC missing")
    if turn_count <= 0:
        missing.append("turns missing")

    broken = new_fields.get("brokenTocLinks", []) or []
    if broken:
        missing.append(f"broken TOC links ({len(broken)})")

    dup_ids = new_fields.get("duplicateTurnIds", []) or []
    if dup_ids:
        missing.append(f"duplicate turn IDs ({len(dup_ids)})")

    empty_turns = new_fields.get("emptyTurns", []) or []
    if empty_turns:
        missing.append(f"empty turns ({len(empty_turns)})")

    if not new_fields.get("hasSearchBox", False):
        missing.append("search box missing")

    captured = 0
    total = len(SCREENSHOT_REGIONS)
    missing_regions = []
    for region, path in new_shots.items():
        if path and Path(path).exists():
            captured += 1
        else:
            missing_regions.append(region)
    if missing_regions:
        missing.append(f"missing screenshots: {', '.join(missing_regions)}")

    result = "pass" if not missing else "fail"
    new_val = f"core_ok={not missing}; screenshots={captured}/{total}"
    explanation = (
        "Core HTML structure and screenshots are present."
        if not missing
        else f"HTML completeness failed: {'; '.join(missing)}"
    )
    return _check(
        "html_integrity",
        "HTML 完整性",
        result,
        new_val,
        "n/a",
        explanation,
    )


def check_dom_fields(new_fields: dict, old_fields: dict | None) -> list:
    """
    Run structured checks on extracted DOM fields.
    Returns list of check result dicts.
    """
    checks = []
    o = old_fields or {}

    # 1. Header meta: should contain version pattern
    meta_n = new_fields.get("meta", "")
    meta_o = o.get("meta", "")
    has_version = bool(re.search(r'v\d+\.\d+', meta_n))
    checks.append(_check(
        "header_meta", "Header Meta",
        "pass" if has_version else "fail",
        meta_n, meta_o,
        "New header meta contains version string." if has_version
        else "New header meta missing version pattern (v\\d+.\\d+)."
    ))

    # 2. Stats: parts count should be >= old (if old exists)
    stats_n = new_fields.get("stats", [])
    stats_o = o.get("stats", [])
    parts_n = next((s for s in stats_n if "parts" in s), "")
    parts_o = next((s for s in stats_o if "parts" in s), "")
    n_num = int(re.search(r'\d+', parts_n).group()) if re.search(r'\d+', parts_n) else 0
    o_num = int(re.search(r'\d+', parts_o).group()) if re.search(r'\d+', parts_o) else 0
    parts_ok = (n_num >= o_num) if o_num > 0 else (n_num > 0)
    checks.append(_check(
        "stats_parts", "Stats: parts count",
        "pass" if parts_ok else "warn",
        parts_n, parts_o,
        f"New parts ({n_num}) >= old ({o_num})." if parts_ok
        else f"New parts ({n_num}) < old ({o_num}) — possible regression."
    ))

    # 3. User message separation: userText should not contain userMetaEl
    user_text = new_fields.get("userText", "")
    user_meta = new_fields.get("userMetaEl", "")
    meta_leaked = user_meta and (user_meta[:20] in user_text)
    checks.append(_check(
        "user_separation", "User message / meta separation",
        "fail" if meta_leaked else "pass",
        user_text[:60], user_meta[:60],
        "Meta leaked into userText." if meta_leaked else "userText and userMetaEl are separate."
    ))

    # 4. Shell tool label: no duplicate tokens, no unexpected prefix
    shell_lbl = new_fields.get("shellLabel", "")
    words = shell_lbl.split()
    has_dup = len(words) != len(set(words)) and len(words) > 0
    checks.append(_check(
        "shell_label", "Shell tool label",
        "fail" if has_dup else "pass",
        shell_lbl, o.get("shellLabel", ""),
        "Duplicate tokens in shell label." if has_dup else "Shell label looks clean."
    ))

    # 5. Called tool labels: no 'Shell:' prefix, no duplicate tokens
    called = new_fields.get("calledLabels", [])
    bad_called = [l for l in called if "Shell:" in l or len(l.split()) != len(set(l.split()))]
    checks.append(_check(
        "called_labels", "Called tool labels",
        "fail" if bad_called else "pass",
        str(called), str(o.get("calledLabels", [])),
        f"Bad labels: {bad_called}" if bad_called else "Called tool labels are clean."
    ))

    # 6. File tool outputText: should contain U+202A path marker
    file_tools = new_fields.get("fileTools", [])
    bad_file = [t for t in file_tools if "\u202a" not in t.get("output", "")]
    checks.append(_check(
        "file_tool_output", "File tool outputText",
        "fail" if bad_file else "pass",
        str([t["output"][:40] for t in file_tools]),
        str([t["output"][:40] for t in o.get("fileTools", [])]),
        f"{len(bad_file)} file tool(s) missing U+202A path marker." if bad_file
        else "All sampled file tools have U+202A path marker."
    ))

    # 7. Reasoning: present and collapsible
    has_r = new_fields.get("hasReasoning", False)
    r_col = new_fields.get("reasoningCollapsible", False)
    checks.append(_check(
        "reasoning", "Thinking/Reasoning block",
        "pass" if has_r else "warn",
        f"present={has_r}, collapsible={r_col}", "n/a",
        "Reasoning block present." if has_r else "No reasoning block found (may be expected)."
    ))

    # 8. Text part meta spans present
    tpm = new_fields.get("textPartMeta", False)
    checks.append(_check(
        "text_part_meta", "Text part meta spans",
        "pass" if tpm else "warn",
        str(tpm), "n/a",
        "text-part-meta spans present." if tpm else "No text-part-meta spans found."
    ))

    # 9. TOC count matches turn count
    toc_count = new_fields.get("tocCount", 0)
    turn_count = new_fields.get("turnCount", 0)
    toc_match = toc_count == turn_count
    checks.append(_check(
        "toc_count", "TOC link count",
        "pass" if toc_match else "fail",
        f"{toc_count} toc links", f"{turn_count} turns",
        f"TOC has {toc_count} links, {turn_count} turns." if toc_match
        else f"Mismatch: {toc_count} TOC links vs {turn_count} turns."
    ))

    # 10. No broken TOC links (href targets exist as IDs)
    broken = new_fields.get("brokenTocLinks", [])
    checks.append(_check(
        "toc_broken_links", "TOC broken links",
        "pass" if not broken else "fail",
        f"{len(broken)} broken", "n/a",
        "All TOC links have matching turn IDs." if not broken
        else f"Broken links (no matching ID): {broken[:5]}"
    ))

    # 11. TOC title attributes contain no raw newlines (breaks browser anchor nav)
    nl_titles = new_fields.get("tocLinksWithNewlineInTitle", [])
    checks.append(_check(
        "toc_title_newlines", "TOC link newlines",
        "pass" if not nl_titles else "fail",
        f"{len(nl_titles)} links with newlines", "n/a",
        "No raw newlines in TOC link title or text." if not nl_titles
        else f"Links with newlines in title/text (breaks nav): {nl_titles[:5]}"
    ))

    # 12. Search box present
    has_search = new_fields.get("hasSearchBox", False)
    checks.append(_check(
        "search_box", "Search box present",
        "pass" if has_search else "warn",
        str(has_search), "n/a",
        "Search input found." if has_search else "Search input (#searchInput) not found."
    ))

    # 13. No empty turns (turns with no content children)
    empty_turns = new_fields.get("emptyTurns", [])
    checks.append(_check(
        "empty_turns", "Empty turns",
        "pass" if not empty_turns else "warn",
        f"{len(empty_turns)} empty", "n/a",
        "All turns have content." if not empty_turns
        else f"Empty turn(s) detected: {empty_turns[:5]}"
    ))

    # 14. No duplicate turn IDs
    dup_ids = new_fields.get("duplicateTurnIds", [])
    checks.append(_check(
        "duplicate_turn_ids", "Duplicate turn IDs",
        "pass" if not dup_ids else "fail",
        f"{len(dup_ids)} duplicates", "n/a",
        "No duplicate turn IDs." if not dup_ids
        else f"Duplicate IDs found: {dup_ids[:5]}"
    ))

    return checks


# ── Visual checks via look_at ─────────────────────────────────────────────────

def check_visual_lookat(new_shots: dict, old_shots: dict) -> list:
    """
    Return look_at check specs.
    Actual look_at calls must be made by the calling agent (CLI or skill).
    This returns a list of {region, new_path, old_path, goal} dicts
    that the caller should process with look_at and then call
    record_visual_result() for each.
    """
    specs = []
    for name, _, goal in SCREENSHOT_REGIONS:
        np = new_shots.get(name)
        op = old_shots.get(name)
        if np or op:
            specs.append({
                "region": name,
                "new_path": np,
                "old_path": op,
                "goal": goal,
            })
    return specs


def record_visual_result(region: str, new_summary: str, old_summary: str) -> dict:
    """
    Build a check result dict from look_at summaries.
    Applies simple keyword heuristics for known regions.
    """
    keywords = {
        "header":     ["v1.", "meta", "turns", "parts"],
        "reasoning":  ["purple", "collapsible", "border", "triangle", "fold"],
        "file_tool":  ["\u202a", "+", "-", "path", "Write", "Edit", "Read"],
        "shell_tool": ["Shell", "output", "command", "green"],
        "text_part":  ["markdown", "code", "block", "paragraph"],
    }
    kws = keywords.get(region, [])
    new_ok = any(k.lower() in new_summary.lower() for k in kws) if kws else True
    result = "pass" if new_ok else "info"
    return _check(
        f"visual_{region}", f"Visual: {region}",
        result,
        new_summary[:200], old_summary[:200] if old_summary else "n/a",
        f"look_at summary for '{region}'."
    )


# ── Pixel diff (optional) ─────────────────────────────────────────────────────

def check_pixel_diff(new_path: str, old_path: str, threshold: float = 0.05) -> dict:
    """
    Pixel-level diff between two screenshot files.
    Requires: pip install pixelmatch Pillow
    Returns a check result dict.
    """
    try:
        from pixelmatch.contrib.PIL import pixelmatch
        from PIL import Image
        import numpy as np

        img_new = Image.open(new_path).convert("RGBA")
        img_old = Image.open(old_path).convert("RGBA")

        # Resize old to match new if sizes differ
        if img_new.size != img_old.size:
            img_old = img_old.resize(img_new.size, Image.LANCZOS)

        w, h = img_new.size
        diff_img = Image.new("RGBA", (w, h))
        mismatch = pixelmatch(img_new, img_old, diff_img, threshold=0.1)
        diff_fraction = mismatch / (w * h)

        region = Path(new_path).stem.replace("new_", "")
        diff_path = str(Path(new_path).parent / f"diff_{region}.png")
        diff_img.save(diff_path)

        ok = diff_fraction <= threshold
        return _check(
            f"pixel_{region}", f"Pixel diff: {region}",
            "pass" if ok else "fail",
            f"{diff_fraction:.3%} mismatch",
            f"threshold={threshold:.0%}",
            f"Pixel diff {diff_fraction:.3%} {'<=' if ok else '>'} threshold {threshold:.0%}. Diff saved: {diff_path}"
        )
    except ImportError:
        return _check(
            f"pixel_skip", "Pixel diff: skipped",
            "info", "pixelmatch not installed", "n/a",
            "Install pixelmatch + Pillow to enable pixel diff: pip install pixelmatch Pillow"
        )
    except Exception as e:
        return _check(
            f"pixel_error", "Pixel diff: error",
            "warn", str(e), "n/a",
            f"Pixel diff failed: {e}"
        )


# ── Main compare entry point ──────────────────────────────────────────────────

NO_BASELINE_STATUS = "NO_BASELINE"


def build_baseline_missing_report(
    new_html: str,
    new_fields: dict,
    new_shots: dict,
    visual_specs: list,
    outdir: str,
    opts: dict,
) -> dict:
    """Build a compare_report when no baseline/old HTML is available."""
    checks = []
    check_ids = [
        ("header_meta", "Header Meta"),
        ("stats_parts", "Stats: parts count"),
        ("user_separation", "User message / meta separation"),
        ("shell_label", "Shell tool label"),
        ("called_labels", "Called tool labels"),
        ("file_tool_output", "File tool outputText"),
        ("reasoning", "Thinking/Reasoning block"),
        ("text_part_meta", "Text part meta spans"),
        ("toc_count", "TOC link count"),
        ("toc_broken_links", "TOC broken links"),
        ("toc_title_newlines", "TOC title newlines"),
        ("search_box", "Search box present"),
        ("empty_turns", "Empty turns"),
        ("duplicate_turn_ids", "Duplicate turn IDs"),
    ]
    for cid, cname in check_ids:
        checks.append({
            "id": cid,
            "name": cname,
            "result": NO_BASELINE_STATUS,
            "new_value": "—",
            "old_value": "N/A",
            "explanation": "No baseline available — run with --init-baseline to create one.",
        })

    baseline_dir = str(Path(__file__).resolve().parents[1] / "assets" / "baseline")
    return {
        "metadata": {
            "new_html": new_html,
            "old_html": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "options": opts,
            "baseline": {
                "exists": False,
                "expected_path": baseline_dir,
                "suggestion": "Run verify.py --new <path> --init-baseline to create baseline.",
            },
        },
        "summary": {
            "passed": False,
            "pass_count": 0,
            "fail_count": 0,
            "warn_count": 0,
            "baseline_missing": True,
        },
        "checks": checks,
        "visual_specs": visual_specs,
        "dom_diff": {},
        "images": {"new": new_shots, "old": {}},
        "raw": {"new_fields": new_fields, "old_fields": None},
    }


async def compare_versions(
    new_html: str,
    old_html: str | None,
    outdir: str,
    options: dict | None = None,
) -> dict:
    """
    Full comparison pipeline. Returns compare_report dict.

    options keys:
        pixel_diff (bool): run pixelmatch in addition to look_at (default False)
        pixel_threshold (float): pixelmatch threshold (default 0.05)
        baseline_dom_map (str): path to baseline dom_map.json for diff
        new_dom_map (str): path to new run's dom_map.json
    """
    opts = options or {}
    pixel_diff = opts.get("pixel_diff", False)
    pixel_threshold = opts.get("pixel_threshold", 0.05)
    outdir_p = Path(outdir)
    shots_dir = outdir_p / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-gpu"])

        new_fields = await extract_fields(new_html, browser)
        old_fields = await extract_fields(old_html, browser) if old_html else None

        new_shots = await take_screenshots(new_html, "new", shots_dir, browser)
        old_shots = await take_screenshots(old_html, "old", shots_dir, browser) if old_html else {}

        await browser.close()

    visual_specs = check_visual_lookat(new_shots, old_shots)

    if old_html is None:
        report = build_baseline_missing_report(
            new_html, new_fields, new_shots, visual_specs, outdir, opts
        )
        report["checks"].insert(0, check_html_integrity(new_fields, new_shots))
        report["summary"]["pass_count"] = sum(1 for c in report["checks"] if c["result"] == "pass")
        report["summary"]["fail_count"] = sum(1 for c in report["checks"] if c["result"] == "fail")
        report["summary"]["warn_count"] = sum(1 for c in report["checks"] if c["result"] == "warn")
        report["summary"]["passed"] = report["summary"]["fail_count"] == 0
        report_path = outdir_p / "compare_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        write_markdown_report(report, outdir)
        return report

    checks = [check_html_integrity(new_fields, new_shots)]
    checks.extend(check_dom_fields(new_fields, old_fields))

    # Pixel diff (optional)
    pixel_checks = []
    if pixel_diff and old_html:
        for name, _, _ in SCREENSHOT_REGIONS:
            np_ = new_shots.get(name)
            op_ = old_shots.get(name)
            if np_ and op_:
                pixel_checks.append(check_pixel_diff(np_, op_, pixel_threshold))
    checks.extend(pixel_checks)

    # Visual look_at specs (caller must process these)
    visual_specs = check_visual_lookat(new_shots, old_shots)

    # DOM map diff
    baseline_dom_path = opts.get("baseline_dom_map")
    new_dom_path = opts.get("new_dom_map")
    d_diff = {}
    if baseline_dom_path and new_dom_path:
        try:
            with open(baseline_dom_path) as f:
                baseline_dom = json.load(f)
            with open(new_dom_path) as f:
                new_dom = json.load(f)
            d_diff = dom_diff(new_dom, baseline_dom)
        except Exception as e:
            d_diff = {"error": str(e)}

    pass_count = sum(1 for c in checks if c["result"] == "pass")
    fail_count = sum(1 for c in checks if c["result"] == "fail")
    warn_count = sum(1 for c in checks if c["result"] == "warn")

    report = {
        "metadata": {
            "new_html": new_html,
            "old_html": old_html,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "options": opts,
        },
        "summary": {
            "passed": fail_count == 0,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "warn_count": warn_count,
        },
        "checks": checks,
        "visual_specs": visual_specs,
        "dom_diff": d_diff,
        "images": {
            "new": new_shots,
            "old": old_shots,
        },
        "raw": {
            "new_fields": new_fields,
            "old_fields": old_fields,
        },
    }

    report_path = outdir_p / "compare_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report


def save_report(report: dict, outdir: str):
    """Re-save report JSON and write compare_report.md from current report state."""
    outdir_p = Path(outdir)
    report_path = outdir_p / "compare_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    write_markdown_report(report, outdir)


def write_markdown_report(report: dict, outdir: str):
    outdir_p = Path(outdir)
    s = report["summary"]
    baseline_missing = s.get("baseline_missing", False)
    status = "⚠️ NO BASELINE" if baseline_missing else ("✅ PASSED" if s["passed"] else "❌ FAILED")
    icon_map = {"pass": "✅", "fail": "❌", "warn": "⚠️", "info": "ℹ️", NO_BASELINE_STATUS: "—"}

    lines = []
    lines.append(f"# Compare Report\n\n")
    if baseline_missing:
        bl = report["metadata"].get("baseline", {})
        lines.append(f"> **Baseline 未找到（首次运行）**  \n")
        lines.append(f"> 请运行以下命令创建 baseline：  \n")
        lines.append(f"> `python3 verify.py --new <path> --init-baseline`\n\n")
    lines.append(f"- **Status**: {status}\n")
    lines.append(f"- **pass**: {s['pass_count']}  **fail**: {s['fail_count']}  **warn**: {s['warn_count']}\n")
    lines.append(f"- **new**: `{report['metadata']['new_html']}`\n")
    lines.append(f"- **old**: `{report['metadata'].get('old_html') or 'n/a'}`\n")
    lines.append(f"- **timestamp**: {report['metadata']['timestamp']}\n\n")

    lines.append("## HTML 渲染层\n\n")
    lines.append("| 维度 | 新版 | 旧版 | 结论 |\n")
    lines.append("|------|------|------|------|\n")
    for c in report["checks"]:
        icon = icon_map.get(c["result"], "")
        nv = c["new_value"].replace("\n", " ").replace("|", "\\|")[:80]
        ov = c["old_value"].replace("\n", " ").replace("|", "\\|")[:80]
        ex = c["explanation"].replace("\n", " ")[:100]
        lines.append(f"| {c['name']} | {nv} | {ov} | {icon} {ex} |\n")

    diff = report.get("dom_diff", {})
    if diff.get("added") or diff.get("removed"):
        lines.append("\n## DOM Map Diff\n\n")
        if diff.get("added"):
            lines.append(f"- ➕ **Added**: {diff['added']}\n")
        if diff.get("removed"):
            lines.append(f"- ➖ **Removed**: {diff['removed']}\n")

    visual_checks = [c for c in report["checks"] if c["id"].startswith("visual_")]
    if visual_checks:
        lines.append("\n## Visual Checks (look_at)\n\n")
        lines.append("| Region | 新版摘要 | 旧版摘要 | 结论 |\n")
        lines.append("|--------|----------|----------|------|\n")
        for c in visual_checks:
            icon = icon_map.get(c["result"], "")
            nv = c["new_value"].replace("\n", " ").replace("|", "\\|")[:100]
            ov = c["old_value"].replace("\n", " ").replace("|", "\\|")[:100]
            ex = c["explanation"].replace("\n", " ")[:80]
            lines.append(f"| {c['name'].replace('Visual: ','')} | {nv} | {ov} | {icon} {ex} |\n")

    lines.append("\n## Screenshots\n\n")
    for region, path in report["images"]["new"].items():
        if path:
            lines.append(f"- **new_{region}**: `{path}`\n")

    md_path = outdir_p / "compare_report.md"
    md_path.write_text("".join(lines), encoding="utf-8")
    return str(md_path)
