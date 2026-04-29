#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS_DIR.parent.parent.parent
SUBSKILL_LIB = SKILL_ROOT / "subskills" / "visual-verify" / "lib"
LOOK_AT_PY = SKILL_ROOT / "subskills" / "visual-verify" / "scripts" / "look_at.py"

VISUAL_REGIONS = [
    ("toc",        "document.querySelector('.toc')",              "TOC 目录区域：条目编号正确、链接文字清晰、无乱码、无换行截断"),
    ("turn0_user", "document.querySelector('#turn-0 .user-msg')", "第一条用户消息：背景色正确、文字可读、角色标签显示"),
    ("shell_tool", "document.querySelector('.tool-part')",        "工具调用块：part-label 格式正确、输出可展开/折叠、图标显示正确"),
    ("text_part",  "document.querySelector('.text-part')",        "Assistant 文字回复：markdown 渲染正确、字体可读"),
    ("reasoning",  "document.querySelector('.reasoning-part')",   "Thinking 块：带折叠箭头、内容可收起"),
]


class _Node:
    __slots__ = ("tag", "attrs", "text", "children")

    def __init__(self, tag: str, attrs: dict):
        self.tag = tag
        self.attrs = attrs
        self.text = ""
        self.children: list[_Node] = []


class _TreeBuilder(HTMLParser):
    VOID = {"area","base","br","col","embed","hr","img","input","link","meta",
            "param","source","track","wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("__root__", {})
        self._stack: list[_Node] = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs))
        self._stack[-1].children.append(node)
        if tag not in self.VOID:
            self._stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                self._stack = self._stack[:i]
                return

    def handle_data(self, data):
        if self._stack:
            self._stack[-1].text += data


def _parse(html_path: str) -> _Node:
    text = Path(html_path).read_text(encoding="utf-8", errors="replace")
    b = _TreeBuilder()
    b.feed(text)
    return b.root


def _find_all(root: _Node, tag: str | None = None, cls: str | None = None) -> list[_Node]:
    results = []
    stack = list(root.children)
    while stack:
        node = stack.pop()
        ok = True
        if tag and node.tag != tag:
            ok = False
        if cls and cls not in node.attrs.get("class", "").split():
            ok = False
        if ok:
            results.append(node)
        stack.extend(node.children)
    return results


def _find_one(root: _Node, tag: str | None = None, cls: str | None = None) -> _Node | None:
    r = _find_all(root, tag=tag, cls=cls)
    return r[0] if r else None


def _text(node: _Node) -> str:
    parts = [node.text]
    for c in node.children:
        parts.append(_text(c))
    return "".join(parts)


def _chk(id_: str, name: str, result: str, detail: str) -> dict:
    return {"id": id_, "name": name, "result": result, "detail": detail}


_NL_RE = re.compile(r'[\n\r\u2028\u2029]')


def _static_checks(html_path: str) -> list[dict]:
    root = _parse(html_path)
    checks = []

    missing = []
    if not _find_one(root, tag="html"):
        missing.append("<html>")
    if not _find_one(root, tag="head"):
        missing.append("<head>")
    if not _find_one(root, tag="body"):
        missing.append("<body>")
    metas = _find_all(root, tag="meta")
    if not any("charset" in n.attrs for n in metas):
        missing.append("<meta charset>")
    title = _find_one(root, tag="title")
    if not title or not _text(title).strip():
        missing.append("<title>")
    checks.append(_chk("html_structure", "HTML 基本结构",
                        "fail" if missing else "pass",
                        f"缺少: {', '.join(missing)}" if missing else "html/head/body/charset/title 均存在"))

    turns = [n for n in _find_all(root, tag="div") if n.attrs.get("id", "").startswith("turn-")]
    toc_links = [n for n in _find_all(root, tag="a") if n.attrs.get("href", "").startswith("#turn-")]
    all_ids = {n.attrs["id"] for n in _find_all(root, tag=None) if "id" in n.attrs
               for n in [n]}

    all_ids = set()
    stack = list(root.children)
    while stack:
        node = stack.pop()
        if "id" in node.attrs:
            all_ids.add(node.attrs["id"])
        stack.extend(node.children)

    n_turns = len(turns)
    n_toc = len(toc_links)
    checks.append(_chk("s_turn_count", "Turn 数量 > 0",
                        "pass" if n_turns > 0 else "fail", f"{n_turns} turns"))
    checks.append(_chk("s_toc_count", "TOC 链接数 == turn 数",
                        "pass" if n_toc == n_turns else "fail",
                        f"TOC={n_toc}, turns={n_turns}"))

    broken = [a.attrs["href"] for a in toc_links
              if a.attrs["href"][1:] not in all_ids]
    checks.append(_chk("s_toc_broken_links", "TOC 无断链",
                        "pass" if not broken else "fail",
                        "所有 TOC 链接均有对应锚点" if not broken
                        else f"{len(broken)} 个断链: {broken[:5]}"))

    bad_nl = [a.attrs.get("href", "?") for a in toc_links
              if _NL_RE.search(a.attrs.get("title", "")) or _NL_RE.search(_text(a))]
    checks.append(_chk("s_toc_title_newlines", "TOC title 无换行",
                        "pass" if not bad_nl else "fail",
                        "无原始换行" if not bad_nl else f"{len(bad_nl)} 个链接含换行: {bad_nl[:5]}"))

    ids = [t.attrs.get("id", "") for t in turns]
    seen: set[str] = set()
    dups = [i for i in ids if (i in seen or seen.add(i))]  # type: ignore[func-returns-value]
    checks.append(_chk("s_duplicate_turn_ids", "Turn ID 无重复",
                        "pass" if not dups else "fail",
                        "所有 turn id 唯一" if not dups else f"重复 ID: {dups[:5]}"))

    empty = [t.attrs.get("id", f"#{i}") for i, t in enumerate(turns) if len(t.children) <= 1]
    checks.append(_chk("s_empty_turns", "无空 turn",
                        "pass" if not empty else "warn",
                        "所有 turn 均有内容" if not empty else f"{len(empty)} 个空 turn: {empty[:5]}"))

    inputs = _find_all(root, tag="input")
    has_search = any(n.attrs.get("id") == "searchInput" for n in inputs)
    checks.append(_chk("s_search_box", "搜索框存在",
                        "pass" if has_search else "warn",
                        "#searchInput 存在" if has_search else "#searchInput 未找到"))

    user_texts = _find_all(root, tag="div", cls="msg-text")
    non_empty = [n for n in user_texts if _text(n).strip()]
    checks.append(_chk("user_messages", "用户消息非空",
                        "pass" if non_empty else "warn",
                        f"{len(non_empty)} 条非空用户消息" if non_empty else "未找到非空用户消息"))

    return checks


async def _dom_checks(html_path: str) -> list[dict]:
    sys.path.insert(0, str(SUBSKILL_LIB))
    import compare as cmp

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return [_chk("dom_playwright", "DOM 检查 (Playwright)",
                     "warn", "playwright 未安装，跳过 DOM 检查")]

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
        fields = await cmp.extract_fields(str(Path(html_path).resolve()), browser)
        await browser.close()

    raw = cmp.check_dom_fields(fields, None)
    return [_chk(c["id"], c["name"],
                 c["result"] if c["result"] != cmp.NO_BASELINE_STATUS else "warn",
                 c["explanation"]) for c in raw]


async def _visual_checks(html_path: str, outdir: Path) -> list[dict]:
    if not LOOK_AT_PY.exists():
        return [_chk("visual_skip", "视觉检查", "warn", f"look_at.py 未找到: {LOOK_AT_PY}")]

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return [_chk("visual_playwright", "视觉检查 (Playwright)",
                     "warn", "playwright 未安装，跳过视觉检查")]

    shots_dir = outdir / "validate_screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        await page.goto(f"file://{Path(html_path).resolve()}")
        await page.wait_for_load_state("networkidle")

        screenshots: dict[str, str | None] = {}
        for name, selector_js, _ in VISUAL_REGIONS:
            out_path = shots_dir / f"{name}.png"
            try:
                el = await page.evaluate_handle(selector_js)
                if el:
                    dom_el = el.as_element()
                    if dom_el:
                        await dom_el.screenshot(path=str(out_path))
                        screenshots[name] = str(out_path)
                        continue
            except Exception:
                pass
            screenshots[name] = None

        await browser.close()

    checks = []
    for name, _, goal in VISUAL_REGIONS:
        path = screenshots.get(name)
        if not path:
            checks.append(_chk(f"visual_{name}", f"视觉: {name}", "warn", "截图失败，元素未找到"))
            continue

        proc = subprocess.run(
            [sys.executable, str(LOOK_AT_PY), path, goal,
             "--model", "github-copilot/gpt-4o", "--json"],
            capture_output=True, text=True
        )
        if proc.returncode != 0:
            checks.append(_chk(f"visual_{name}", f"视觉: {name}", "warn",
                                f"look_at 调用失败: {proc.stderr.strip()[:120]}"))
            continue

        try:
            data = json.loads(proc.stdout)
            verdict = data.get("verdict", "info")
            summary = data.get("summary", "")
            lines = [ln.strip() for ln in summary.splitlines() if ln.strip()]
            detail_line = lines[-1][:200] if lines else ""
            checks.append(_chk(f"visual_{name}", f"视觉: {name}", verdict, detail_line))
        except Exception as e:
            checks.append(_chk(f"visual_{name}", f"视觉: {name}", "warn", f"解析失败: {e}"))

    return checks


def _write_markdown(checks: list[dict], html_path: str, md_path: Path):
    icon = {"pass": "✅", "fail": "❌", "warn": "⚠️", "info": "ℹ️"}
    fail_count = sum(1 for c in checks if c["result"] == "fail")
    warn_count = sum(1 for c in checks if c["result"] == "warn")
    pass_count = sum(1 for c in checks if c["result"] == "pass")
    status = "✅ PASSED" if fail_count == 0 else "❌ FAILED"

    lines = [
        f"# HTML 验证报告\n\n",
        f"- **文件**: `{html_path}`\n",
        f"- **结果**: {status}  pass={pass_count} warn={warn_count} fail={fail_count}\n\n",
        "| 检查项 | ID | 结论 | 详情 |\n",
        "|--------|-----|------|------|\n",
    ]
    for c in checks:
        sym = icon.get(c["result"], "")
        detail = c["detail"].replace("\n", " ").replace("|", "\\|")[:120]
        lines.append(f"| {c['name']} | `{c['id']}` | {sym} {c['result']} | {detail} |\n")

    md_path.write_text("".join(lines), encoding="utf-8")


def _print_report(checks: list[dict], html_path: str) -> bool:
    icon = {"pass": "✓", "fail": "✗", "warn": "~", "info": "i"}
    fail_count = sum(1 for c in checks if c["result"] == "fail")
    warn_count = sum(1 for c in checks if c["result"] == "warn")
    pass_count = sum(1 for c in checks if c["result"] == "pass")

    print(f"\n[validate] {Path(html_path).name}  pass={pass_count} warn={warn_count} fail={fail_count}")
    for c in checks:
        sym = icon.get(c["result"], "?")
        print(f"  [{sym}] {c['name']}: {c['detail']}")
    print(f"  → {'OK' if fail_count == 0 else 'FAILED'}" +
          (" (with warnings)" if fail_count == 0 and warn_count > 0 else ""))
    return fail_count == 0


async def _run_async(html_path: str, outdir: Path, skip_dom: bool, skip_visual: bool) -> list[dict]:
    checks = _static_checks(html_path)

    if not skip_dom:
        dom = await _dom_checks(html_path)
        checks.extend(dom)

    if not skip_visual:
        visual = await _visual_checks(html_path, outdir)
        checks.extend(visual)

    return checks


def run(html_path: str, json_out: str | None = None, md_out: str | None = None,
        skip_dom: bool = False, skip_visual: bool = False) -> bool:
    outdir = Path(json_out).parent if json_out else Path(html_path).parent

    checks = asyncio.run(_run_async(html_path, outdir, skip_dom, skip_visual))
    ok = _print_report(checks, html_path)

    report = {"html": html_path, "checks": checks}

    if json_out:
        Path(json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = Path(md_out) if md_out else outdir / "validate_report.md"
    _write_markdown(checks, html_path, md_path)
    print(f"  MD report: {md_path}")

    return ok


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Validate run_db.py chat.html")
    p.add_argument("html", help="Path to chat.html")
    p.add_argument("--json-out", default=None)
    p.add_argument("--md-out", default=None)
    p.add_argument("--skip-dom", action="store_true", help="Skip Playwright DOM checks")
    p.add_argument("--skip-visual", action="store_true", help="Skip visual look_at checks")
    args = p.parse_args()
    ok = run(args.html, args.json_out, args.md_out, args.skip_dom, args.skip_visual)
    sys.exit(0 if ok else 1)
