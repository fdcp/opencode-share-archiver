import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import compare as cmp

TOP_LEVEL_KEYS = {"metadata", "summary", "checks", "visual_specs", "dom_diff", "images", "raw"}


def test_save_report_writes_json(tmp_path, minimal_report):
    cmp.save_report(minimal_report, str(tmp_path))
    report_path = tmp_path / "compare_report.json"
    assert report_path.exists()
    loaded = json.loads(report_path.read_text())
    assert set(loaded.keys()) >= TOP_LEVEL_KEYS


def test_save_report_top_level_keys(tmp_path, minimal_report):
    cmp.save_report(minimal_report, str(tmp_path))
    loaded = json.loads((tmp_path / "compare_report.json").read_text())
    for key in TOP_LEVEL_KEYS:
        assert key in loaded, f"Missing top-level key: {key}"


def test_write_markdown_report_creates_file(tmp_path, minimal_report):
    cmp.write_markdown_report(minimal_report, str(tmp_path))
    md_path = tmp_path / "compare_report.md"
    assert md_path.exists()


def test_write_markdown_report_contains_sections(tmp_path, minimal_report):
    cmp.write_markdown_report(minimal_report, str(tmp_path))
    content = (tmp_path / "compare_report.md").read_text()
    assert "HTML 渲染层" in content
    assert "# Compare Report" in content


def test_write_markdown_report_has_all_check_names(tmp_path, minimal_report):
    cmp.write_markdown_report(minimal_report, str(tmp_path))
    content = (tmp_path / "compare_report.md").read_text()
    for c in minimal_report["checks"]:
        assert c["name"] in content, f"Check name missing from MD: {c['name']}"


def test_write_markdown_report_baseline_missing(tmp_path, baseline_missing_report):
    cmp.write_markdown_report(baseline_missing_report, str(tmp_path))
    content = (tmp_path / "compare_report.md").read_text()
    assert "Baseline 未找到" in content
    assert "--init-baseline" in content
    assert "NO_BASELINE" in content or "—" in content


def test_baseline_missing_report_structure(baseline_missing_report):
    assert baseline_missing_report["summary"]["baseline_missing"] is True
    assert baseline_missing_report["metadata"]["baseline"]["exists"] is False
    assert baseline_missing_report["raw"]["old_fields"] is None
    for c in baseline_missing_report["checks"]:
        assert c["result"] == cmp.NO_BASELINE_STATUS


def test_baseline_missing_report_new_shots_present(tmp_path, sample_dom_new):
    shots = {"header": str(tmp_path / "new_header.png")}
    report = cmp.build_baseline_missing_report("/tmp/new.html", sample_dom_new, shots, [], str(tmp_path), {})
    assert report["images"]["new"] == shots
    assert report["images"]["old"] == {}


def test_write_markdown_report_with_visual_checks(tmp_path, minimal_report):
    visual_check = {
        "id": "visual_header",
        "name": "Visual: header",
        "result": "pass",
        "new_value": "header looks clean",
        "old_value": "header looks clean",
        "explanation": "look_at summary for 'header'.",
    }
    minimal_report["checks"].append(visual_check)
    minimal_report["summary"]["pass_count"] += 1
    cmp.write_markdown_report(minimal_report, str(tmp_path))
    content = (tmp_path / "compare_report.md").read_text()
    assert "Visual Checks" in content
    assert "header looks clean" in content


def test_dom_diff_added_removed():
    new_map = {"slot_1_A": {}, "slot_2_B": {}}
    old_map = {"slot_1_A": {}, "slot_3_C": {}}
    result = cmp.dom_diff(new_map, old_map)
    assert "slot_2_B" in result["added"]
    assert "slot_3_C" in result["removed"]


def test_dom_diff_no_change():
    m = {"a": {}, "b": {}}
    result = cmp.dom_diff(m, m)
    assert result["added"] == []
    assert result["removed"] == []


def test_dom_diff_empty_old():
    result = cmp.dom_diff({"a": {}}, None)
    assert "a" in result["added"]
    assert result["removed"] == []
