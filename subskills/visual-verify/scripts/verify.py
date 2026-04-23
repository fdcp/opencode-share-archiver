#!/usr/bin/env python3

import argparse
import asyncio
import json
import sys
from pathlib import Path

SUBSKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUBSKILL_ROOT / "lib"))

import compare as cmp


def parse_args():
    p = argparse.ArgumentParser(description="Visual verify: compare new vs old chat.html")
    p.add_argument("--new", default=None, help="Path to new chat.html")
    p.add_argument("--old", default=None, help="Path to old/baseline chat.html")
    p.add_argument("--outdir", required=True, help="Output directory")
    p.add_argument("--mode", choices=["dom", "visual", "both"], default="both")
    p.add_argument("--pixel-diff", action="store_true", default=False)
    p.add_argument("--pixel-threshold", type=float, default=0.05)
    p.add_argument("--baseline-dom-map", default=None)
    p.add_argument("--new-dom-map", default=None)
    p.add_argument("--update-baseline", action="store_true", default=False)
    p.add_argument("--init-baseline", action="store_true", default=False,
                   help="Create baseline from current --new output (only when baseline does not exist)")
    p.add_argument("--fail-on-missing-baseline", action="store_true", default=False,
                   help="Exit non-zero when no baseline is found (useful in CI)")
    p.add_argument("--verbose", action="store_true", default=False)
    p.add_argument("--inject-visual", nargs=3, metavar=("REGION", "NEW_SUMMARY", "OLD_SUMMARY"),
                   help="Inject a look_at visual result into existing report")
    return p.parse_args()


def print_summary(report: dict):
    s = report["summary"]
    status = "✅ PASSED" if s["passed"] else "❌ FAILED"
    print(f"\n{status}  pass={s['pass_count']} fail={s['fail_count']} warn={s['warn_count']}\n")


def print_checks_table(report: dict):
    icon_map = {"pass": "✅", "fail": "❌", "warn": "⚠️", "info": "ℹ️"}
    print("### HTML 渲染层\n")
    print("| 维度 | 新版 | 旧版 | 结论 |")
    print("|------|------|------|------|")
    for c in report["checks"]:
        if c["id"].startswith("visual_"):
            continue
        icon = icon_map.get(c["result"], "")
        nv = c["new_value"][:60].replace("\n", " ")
        ov = c["old_value"][:60].replace("\n", " ")
        ex = c["explanation"][:80]
        print(f"| {c['name']} | {nv} | {ov} | {icon} {ex} |")

    visual = [c for c in report["checks"] if c["id"].startswith("visual_")]
    if visual:
        print("\n### Visual Checks (look_at)\n")
        print("| Region | 新版摘要 | 旧版摘要 | 结论 |")
        print("|--------|----------|----------|------|")
        for c in visual:
            icon = icon_map.get(c["result"], "")
            nv = c["new_value"][:80].replace("\n", " ")
            ov = c["old_value"][:80].replace("\n", " ")
            ex = c["explanation"][:60]
            print(f"| {c['name'].replace('Visual: ','')} | {nv} | {ov} | {icon} {ex} |")


def print_visual_spec_instructions(report: dict, outdir: str):
    vspecs = report.get("visual_specs", [])
    if not vspecs:
        return
    print(f"\n### Visual check specs — run look_at on each region, then inject results\n")
    for vs in vspecs:
        print(f"Region: {vs['region']}  ({vs['goal']})")
        if vs.get("new_path"):
            print(f"  new: {vs['new_path']}")
        if vs.get("old_path"):
            print(f"  old: {vs['old_path']}")
        print(f"  inject command:")
        print(f"    python3 {__file__} --inject-visual {vs['region']} \"<new_summary>\" \"<old_summary>\" --outdir {outdir}")


def inject_visual_result(outdir: str, region: str, new_summary: str, old_summary: str):
    report_path = Path(outdir) / "compare_report.json"
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    check = cmp.record_visual_result(region, new_summary, old_summary)
    existing_ids = {c["id"] for c in report["checks"]}
    if check["id"] in existing_ids:
        report["checks"] = [c if c["id"] != check["id"] else check for c in report["checks"]]
    else:
        report["checks"].append(check)

    pass_count = sum(1 for c in report["checks"] if c["result"] == "pass")
    fail_count = sum(1 for c in report["checks"] if c["result"] == "fail")
    warn_count = sum(1 for c in report["checks"] if c["result"] == "warn")
    report["summary"] = {
        "passed": fail_count == 0,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "warn_count": warn_count,
    }

    cmp.save_report(report, outdir)
    print(f"Injected visual_{region}: {check['result']}")
    print_summary(report)
    print_checks_table(report)
    md_path = Path(outdir) / "compare_report.md"
    print(f"\nUpdated: {report_path}")
    print(f"Updated: {md_path}")


def init_baseline(new_html: str, new_dom_map: str | None, outdir: str):
    import shutil
    baseline_dir = SUBSKILL_ROOT / "assets" / "baseline"
    if baseline_dir.exists() and any(baseline_dir.iterdir()):
        print("Error: baseline already exists. Use --update-baseline to overwrite.", file=sys.stderr)
        sys.exit(1)
    baseline_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(new_html, baseline_dir / "chat.html")
    if new_dom_map and Path(new_dom_map).exists():
        shutil.copy2(new_dom_map, baseline_dir / "dom_map.json")
    shots_src = Path(outdir) / "screenshots"
    shots_dst = baseline_dir / "screenshots"
    if shots_src.exists():
        if shots_dst.exists():
            shutil.rmtree(shots_dst)
        shutil.copytree(shots_src, shots_dst)
    meta = {
        "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "source_html": new_html,
    }
    (baseline_dir / "baseline_meta.json").write_text(
        __import__("json").dumps(meta, indent=2), encoding="utf-8"
    )
    print(f"Baseline created: {baseline_dir}")


def update_baseline(new_html: str, new_dom_map: str | None, outdir: str):
    import shutil
    baseline_dir = SUBSKILL_ROOT / "assets" / "baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(new_html, baseline_dir / "chat.html")
    print(f"  Copied {new_html} → {baseline_dir / 'chat.html'}")

    if new_dom_map and Path(new_dom_map).exists():
        shutil.copy2(new_dom_map, baseline_dir / "dom_map.json")
        print(f"  Copied {new_dom_map} → {baseline_dir / 'dom_map.json'}")

    shots_src = Path(outdir) / "screenshots"
    shots_dst = baseline_dir / "screenshots"
    if shots_src.exists():
        if shots_dst.exists():
            shutil.rmtree(shots_dst)
        shutil.copytree(shots_src, shots_dst)
        print(f"  Copied screenshots → {shots_dst}")

    print("Baseline updated.")


async def main():
    args = parse_args()

    if args.inject_visual:
        region, new_sum, old_sum = args.inject_visual
        inject_visual_result(args.outdir, region, new_sum, old_sum)
        sys.exit(0)

    if not args.new:
        print("Error: --new is required unless using --inject-visual", file=sys.stderr)
        sys.exit(2)

    options = {
        "pixel_diff": args.pixel_diff,
        "pixel_threshold": args.pixel_threshold,
        "baseline_dom_map": args.baseline_dom_map,
        "new_dom_map": args.new_dom_map,
    }

    new_html = str(Path(args.new).resolve())
    old_html = str(Path(args.old).resolve()) if args.old else None

    print(f"Comparing:")
    print(f"  new: {new_html}")
    print(f"  old: {old_html or '(none)'}")
    print(f"  outdir: {args.outdir}")
    print(f"  mode: {args.mode}  pixel_diff: {args.pixel_diff}  threshold: {args.pixel_threshold}")

    report = await cmp.compare_versions(new_html, old_html, args.outdir, options)

    md_path = cmp.write_markdown_report(report, args.outdir)

    print_summary(report)
    print_checks_table(report)

    diff = report.get("dom_diff", {})
    if diff.get("added") or diff.get("removed"):
        print("\n### DOM Map Diff\n")
        if diff.get("added"):
            print(f"  ➕ Added:   {diff['added']}")
        if diff.get("removed"):
            print(f"  ➖ Removed: {diff['removed']}")

    print_visual_spec_instructions(report, args.outdir)

    report_path = Path(args.outdir) / "compare_report.json"
    print(f"\nReport saved: {report_path}")
    print(f"Markdown saved: {md_path}")

    if args.verbose:
        print("\n### Raw fields\n")
        print(json.dumps(report["raw"], ensure_ascii=False, indent=2))

    if args.update_baseline:
        print("\nUpdating baseline...")
        update_baseline(new_html, args.new_dom_map, args.outdir)

    baseline_missing = report["summary"].get("baseline_missing", False)

    if baseline_missing and args.init_baseline:
        print("\nInitializing baseline...")
        init_baseline(new_html, args.new_dom_map, args.outdir)

    if baseline_missing and args.fail_on_missing_baseline:
        print("Error: baseline missing and --fail-on-missing-baseline is set.", file=sys.stderr)
        sys.exit(2)

    sys.exit(0 if (report["summary"]["passed"] or baseline_missing) else 1)


if __name__ == "__main__":
    asyncio.run(main())
