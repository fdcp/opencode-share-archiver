#!/usr/bin/env python3
"""
orchestrate_verify.py — End-to-end pipeline: scrape → verify → look_at → inject

Usage:
    python3 orchestrate_verify.py <share_url> <output_dir> [options]

Options:
    --skip-scrape               Skip run.py (use existing chat.html in output_dir)
    --skip-verify               Skip verify.py (only scrape)
    --auto-inject               Auto-call look_at CLI for each visual_spec and inject results
    --lookat-cmd CMD            look_at CLI command template (default: "look_at")
                                Use {image} and {goal} as placeholders, e.g.:
                                  "my_tool --image {image} --goal {goal}"
    --concurrency N             Max parallel look_at calls (default: 4)
    --lookat-timeout S          Seconds to wait per look_at call (default: 30)
    --init-baseline             Pass --init-baseline to verify.py when no baseline exists
    --update-baseline           Pass --update-baseline to verify.py
    --fail-on-missing-baseline  Exit non-zero when baseline is missing
    --pixel-diff                Enable pixel diff in verify.py
    --pixel-threshold F         Pixel diff threshold (default 0.05)
    --old PATH                  Explicit old/baseline HTML path (overrides auto-detect)
    --verbose                   Show extra output

Pipeline:
    1. run.py    → <outdir>/chat.html + dom_map.json + conversation_final.json
    2. verify.py → <outdir>/compare/compare_report.json + screenshots + visual_specs
    3. [--auto-inject] For each visual_spec: call look_at CLI (parallel, up to --concurrency)
    4. [--auto-inject] Inject all summaries into report → final compare_report.json + .md

look_at CLI contract:
    The command must accept two positional args: <image_path> <goal_text>
    and print the visual summary to stdout.
    Example:  look_at /path/to/screenshot.png "check header layout"
    Override with --lookat-cmd if your tool has a different interface.
"""
import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
RUN_PY = SKILL_ROOT / "scripts" / "run.py"
VERIFY_PY = SKILL_ROOT / "subskills" / "visual-verify" / "scripts" / "verify.py"
LIB_PATH = SKILL_ROOT / "subskills" / "visual-verify" / "lib"

sys.path.insert(0, str(LIB_PATH))


def run_cmd(cmd: list, label: str) -> int:
    print(f"\n[orchestrate] {label}")
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        print(f"  ✗ {label} exited with code {result.returncode}", file=sys.stderr)
    else:
        print(f"  ✓ {label} completed")
    return result.returncode


def parse_args():
    p = argparse.ArgumentParser(description="End-to-end scrape + verify + look_at pipeline")
    p.add_argument("share_url", help="https://opncd.ai/share/<ID>")
    p.add_argument("output_dir", help="Output directory (will be created if needed)")
    p.add_argument("--skip-scrape", action="store_true")
    p.add_argument("--skip-verify", action="store_true")
    p.add_argument("--auto-inject", action="store_true",
                   help="Auto-call look_at CLI and inject results into the report")
    p.add_argument("--lookat-cmd", default="look_at",
                   help="look_at CLI command. Use {image} and {goal} as placeholders. "
                        "Default: 'look_at {image} {goal}'")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--lookat-timeout", type=int, default=30)
    p.add_argument("--init-baseline", action="store_true")
    p.add_argument("--update-baseline", action="store_true")
    p.add_argument("--fail-on-missing-baseline", action="store_true")
    p.add_argument("--pixel-diff", action="store_true")
    p.add_argument("--pixel-threshold", type=float, default=0.05)
    p.add_argument("--old", default=None, help="Explicit path to old/baseline chat.html")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def find_baseline_html(skill_root: Path) -> str | None:
    candidate = skill_root / "subskills" / "visual-verify" / "assets" / "baseline" / "chat.html"
    return str(candidate) if candidate.exists() else None


def call_lookat(image_path: str, goal: str, lookat_cmd: str, timeout: int) -> str:
    if "{image}" in lookat_cmd or "{goal}" in lookat_cmd:
        cmd_str = lookat_cmd.format(image=image_path, goal=goal)
        cmd = cmd_str.split()
    else:
        cmd = lookat_cmd.split() + [image_path, goal]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"look_at exited {result.returncode}: {result.stderr.strip()[:200]}"
        )
    return result.stdout.strip()


def run_lookat_for_specs(
    visual_specs: list,
    lookat_cmd: str,
    concurrency: int,
    timeout: int,
    look_at_dir: Path,
) -> dict:
    summaries = {vs["region"]: {"new": None, "old": None} for vs in visual_specs}
    tasks = []
    for vs in visual_specs:
        region = vs["region"]
        goal = vs.get("goal", region)
        if vs.get("new_path"):
            tasks.append(("new", region, vs["new_path"], goal))
        if vs.get("old_path"):
            tasks.append(("old", region, vs["old_path"], goal))

    print(f"\n[orchestrate] Step 3: Running look_at for {len(tasks)} image(s) "
          f"(concurrency={concurrency}, timeout={timeout}s)")

    look_at_dir.mkdir(parents=True, exist_ok=True)
    failures = []

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_map = {
            executor.submit(call_lookat, img_path, goal, lookat_cmd, timeout): (kind, region)
            for kind, region, img_path, goal in tasks
        }
        for future in as_completed(future_map):
            kind, region = future_map[future]
            try:
                summary = future.result()
                summaries[region][kind] = summary
                (look_at_dir / f"{region}_{kind}.txt").write_text(summary, encoding="utf-8")
                print(f"  ✓ look_at {region} [{kind}]: {summary[:60]}...")
            except Exception as exc:
                msg = f"ERROR: {exc}"
                summaries[region][kind] = msg
                failures.append({"region": region, "kind": kind, "error": str(exc)})
                print(f"  ✗ look_at {region} [{kind}]: {exc}", file=sys.stderr)

    if failures:
        (look_at_dir / "failures.json").write_text(
            json.dumps(failures, indent=2), encoding="utf-8"
        )
        print(f"  ⚠️  {len(failures)} look_at call(s) failed — see {look_at_dir}/failures.json")

    return summaries


def inject_summaries(report: dict, summaries: dict, outdir: Path) -> dict:
    import compare as cmp

    for region, pair in summaries.items():
        new_sum = pair.get("new") or ""
        old_sum = pair.get("old") or ""
        if not new_sum and not old_sum:
            continue
        check = cmp.record_visual_result(region, new_sum, old_sum)
        ids = [c["id"] for c in report["checks"]]
        if check["id"] in ids:
            report["checks"] = [
                check if c["id"] == check["id"] else c
                for c in report["checks"]
            ]
        else:
            report["checks"].append(check)

    pass_count = sum(1 for c in report["checks"] if c["result"] == "pass")
    fail_count = sum(1 for c in report["checks"] if c["result"] == "fail")
    warn_count = sum(1 for c in report["checks"] if c["result"] == "warn")
    report["summary"].update({
        "passed": fail_count == 0,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "warn_count": warn_count,
    })

    cmp.save_report(report, str(outdir))
    return report


def main():
    args = parse_args()
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    compare_dir = outdir / "compare"
    chat_html = outdir / "chat.html"
    dom_map = outdir / "dom_map.json"

    exit_code = 0

    if not args.skip_scrape:
        rc = run_cmd(
            [sys.executable, str(RUN_PY), args.share_url, str(outdir)],
            "Step 1: Scrape"
        )
        if rc != 0:
            print("Scrape failed. Aborting.", file=sys.stderr)
            sys.exit(rc)
    else:
        print("[orchestrate] Step 1: Scrape — skipped")
        if not chat_html.exists():
            print(f"Error: --skip-scrape given but {chat_html} does not exist.", file=sys.stderr)
            sys.exit(1)

    if args.skip_verify:
        print("[orchestrate] Step 2: Verify — skipped")
        sys.exit(0)

    old_html = args.old or find_baseline_html(SKILL_ROOT)

    verify_cmd = [
        sys.executable, str(VERIFY_PY),
        "--new", str(chat_html),
        "--outdir", str(compare_dir),
        "--new-dom-map", str(dom_map),
    ]
    if old_html:
        verify_cmd += ["--old", old_html]
        baseline_dom = SKILL_ROOT / "subskills" / "visual-verify" / "assets" / "baseline" / "dom_map.json"
        if baseline_dom.exists():
            verify_cmd += ["--baseline-dom-map", str(baseline_dom)]
    if args.init_baseline:
        verify_cmd.append("--init-baseline")
    if args.update_baseline:
        verify_cmd.append("--update-baseline")
    if args.fail_on_missing_baseline:
        verify_cmd.append("--fail-on-missing-baseline")
    if args.pixel_diff:
        verify_cmd += ["--pixel-diff", "--pixel-threshold", str(args.pixel_threshold)]
    if args.verbose:
        verify_cmd.append("--verbose")

    rc = run_cmd(verify_cmd, "Step 2: Verify")
    if rc not in (0, 1):
        print(f"Verify exited with unexpected code {rc}", file=sys.stderr)
        sys.exit(rc)

    report_path = compare_dir / "compare_report.json"
    if not report_path.exists():
        print(f"No compare_report.json found at {report_path}", file=sys.stderr)
        sys.exit(1)

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    visual_specs = report.get("visual_specs", [])

    if args.auto_inject and visual_specs:
        look_at_dir = compare_dir / "look_at"
        summaries = run_lookat_for_specs(
            visual_specs,
            lookat_cmd=args.lookat_cmd,
            concurrency=args.concurrency,
            timeout=args.lookat_timeout,
            look_at_dir=look_at_dir,
        )
        print(f"\n[orchestrate] Step 4: Injecting look_at results into report...")
        report = inject_summaries(report, summaries, compare_dir)
        print(f"  ✓ Injection complete")
    elif args.auto_inject and not visual_specs:
        print("\n[orchestrate] Step 3: No visual specs — nothing to inject.")
    else:
        if visual_specs:
            print(f"\n[orchestrate] Step 3: {len(visual_specs)} visual spec(s) ready for look_at.")
            print("  Re-run with --auto-inject to process automatically, or inject manually:")
            for vs in visual_specs:
                region = vs["region"]
                inject_cmd = (
                    f"python3 {VERIFY_PY} --inject-visual {region} "
                    f'"<new_summary>" "<old_summary>" --outdir {compare_dir}'
                )
                print(f"    {inject_cmd}")
        else:
            print("\n[orchestrate] Step 3: No visual specs to inject.")

    s = report["summary"]
    baseline_missing = s.get("baseline_missing", False)
    if baseline_missing:
        print(f"\n[orchestrate] ⚠️  Baseline missing.")
        print(f"  Run with --init-baseline to create one.")
        exit_code = 0
    elif s["passed"]:
        print(f"\n[orchestrate] ✅ PASSED  pass={s['pass_count']} fail={s['fail_count']} warn={s['warn_count']}")
    else:
        print(f"\n[orchestrate] ❌ FAILED  pass={s['pass_count']} fail={s['fail_count']} warn={s['warn_count']}")
        exit_code = 1

    print(f"\n  Report: {report_path}")
    print(f"  MD:     {compare_dir / 'compare_report.md'}")
    print(f"  HTML:   {chat_html}")

    if args.fail_on_missing_baseline and baseline_missing:
        sys.exit(2)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
