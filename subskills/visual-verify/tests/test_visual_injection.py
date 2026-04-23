import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import compare as cmp


def test_record_visual_result_returns_check_dict():
    result = cmp.record_visual_result("header", "clean header v1.2", "clean header v1.1")
    assert result["id"] == "visual_header"
    assert result["result"] in ("pass", "info", "warn", "fail")
    assert "header" in result["name"].lower()


def test_record_visual_result_new_summary_stored(tmp_path):
    result = cmp.record_visual_result("header", "clean header v1.2 meta", "old header meta")
    assert "clean header v1.2 meta" in result["new_value"]


def test_record_visual_result_old_summary_stored():
    result = cmp.record_visual_result("toc", "toc looks good", "toc old")
    assert "toc old" in result["old_value"]


def test_inject_visual_updates_json(tmp_path, minimal_report):
    report_path = tmp_path / "compare_report.json"
    report_path.write_text(json.dumps(minimal_report), encoding="utf-8")

    cmp.save_report(minimal_report, str(tmp_path))

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import importlib, types

    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    spec = importlib.util.spec_from_file_location("verify", scripts_dir / "verify.py")
    verify_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify_mod)

    verify_mod.inject_visual_result(str(tmp_path), "header", "new header summary", "old header summary")

    updated = json.loads((tmp_path / "compare_report.json").read_text())
    visual_check = next((c for c in updated["checks"] if c["id"] == "visual_header"), None)
    assert visual_check is not None
    assert "new header summary" in visual_check["new_value"]


def test_inject_visual_updates_markdown(tmp_path, minimal_report):
    cmp.save_report(minimal_report, str(tmp_path))

    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    import importlib
    spec = importlib.util.spec_from_file_location("verify_inj", scripts_dir / "verify.py")
    verify_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify_mod)

    verify_mod.inject_visual_result(str(tmp_path), "reasoning", "purple collapsible border", "old reasoning")

    md = (tmp_path / "compare_report.md").read_text()
    assert "purple collapsible border" in md


def test_inject_visual_replaces_existing_entry(tmp_path, minimal_report):
    existing_visual = {
        "id": "visual_header",
        "name": "Visual: header",
        "result": "info",
        "new_value": "old summary",
        "old_value": "n/a",
        "explanation": "look_at summary for 'header'.",
    }
    minimal_report["checks"].append(existing_visual)
    cmp.save_report(minimal_report, str(tmp_path))

    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    import importlib
    spec = importlib.util.spec_from_file_location("verify_rep", scripts_dir / "verify.py")
    verify_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify_mod)

    verify_mod.inject_visual_result(str(tmp_path), "header", "updated summary v1.2 meta", "old baseline")

    updated = json.loads((tmp_path / "compare_report.json").read_text())
    visual_checks = [c for c in updated["checks"] if c["id"] == "visual_header"]
    assert len(visual_checks) == 1
    assert "updated summary" in visual_checks[0]["new_value"]


def test_inject_visual_summary_recalculated(tmp_path, minimal_report):
    cmp.save_report(minimal_report, str(tmp_path))

    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    import importlib
    spec = importlib.util.spec_from_file_location("verify_sum", scripts_dir / "verify.py")
    verify_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify_mod)

    verify_mod.inject_visual_result(str(tmp_path), "header", "header v1.2 meta", "old header meta v1.2")

    updated = json.loads((tmp_path / "compare_report.json").read_text())
    total = (
        updated["summary"]["pass_count"]
        + updated["summary"]["fail_count"]
        + updated["summary"]["warn_count"]
    )
    assert total == len([c for c in updated["checks"] if c["result"] in ("pass", "fail", "warn")])
