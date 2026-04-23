import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import compare as cmp

NO_BASELINE = cmp.NO_BASELINE_STATUS

_TOTAL_CHECKS = 14


@pytest.mark.parametrize("check_id,new_override,old_override,expected", [
    # ── original 8 checks ────────────────────────────────────────────────────
    ("header_meta", {"meta": "opencode v1.2.3 · 2 turns"}, {}, "pass"),
    ("header_meta", {"meta": "no version here"}, {}, "fail"),
    ("stats_parts", {"stats": ["10 parts"]}, {"stats": ["8 parts"]}, "pass"),
    ("stats_parts", {"stats": ["3 parts"]}, {"stats": ["8 parts"]}, "warn"),
    ("stats_parts", {"stats": ["5 parts"]}, {}, "warn"),
    ("user_separation", {"userText": "Hello world", "userMetaEl": "2026-01-01"}, {}, "pass"),
    ("user_separation", {"userText": "2026-01-01 Hello world", "userMetaEl": "2026-01-01"}, {}, "fail"),
    ("shell_label", {"shellLabel": "Shell: ls -la"}, {}, "pass"),
    ("shell_label", {"shellLabel": "Shell: Shell: ls"}, {}, "fail"),
    ("shell_label", {"shellLabel": ""}, {}, "pass"),
    ("called_labels", {"calledLabels": ["call_omo_agent: explore"]}, {}, "pass"),
    ("called_labels", {"calledLabels": ["Shell: something"]}, {}, "fail"),
    ("called_labels", {"calledLabels": ["call_omo_agent call_omo_agent"]}, {}, "fail"),
    ("file_tool_output", {"fileTools": [{"label": "Read", "output": "\u202a/path/file.txt\u202c"}]}, {}, "pass"),
    ("file_tool_output", {"fileTools": [{"label": "Read", "output": "/path/file.txt"}]}, {}, "fail"),
    ("file_tool_output", {"fileTools": []}, {}, "pass"),
    ("reasoning", {"hasReasoning": True, "reasoningCollapsible": True}, {}, "pass"),
    ("reasoning", {"hasReasoning": False, "reasoningCollapsible": False}, {}, "warn"),
    ("text_part_meta", {"textPartMeta": True}, {}, "pass"),
    ("text_part_meta", {"textPartMeta": False}, {}, "warn"),
    # ── toc_count ────────────────────────────────────────────────────────────
    ("toc_count", {"tocCount": 5, "turnCount": 5}, {}, "pass"),
    ("toc_count", {"tocCount": 4, "turnCount": 5}, {}, "fail"),
    ("toc_count", {"tocCount": 5, "turnCount": 4}, {}, "fail"),
    # ── toc_broken_links ─────────────────────────────────────────────────────
    ("toc_broken_links", {"brokenTocLinks": []}, {}, "pass"),
    ("toc_broken_links", {"brokenTocLinks": ["#turn-99"]}, {}, "fail"),
    ("toc_broken_links", {"brokenTocLinks": ["#turn-1", "#turn-2"]}, {}, "fail"),
    # ── toc_title_newlines ───────────────────────────────────────────────────
    ("toc_title_newlines", {"tocLinksWithNewlineInTitle": []}, {}, "pass"),
    ("toc_title_newlines", {"tocLinksWithNewlineInTitle": ["#turn-3"]}, {}, "fail"),
    # ── search_box ───────────────────────────────────────────────────────────
    ("search_box", {"hasSearchBox": True}, {}, "pass"),
    ("search_box", {"hasSearchBox": False}, {}, "warn"),
    # ── empty_turns ──────────────────────────────────────────────────────────
    ("empty_turns", {"emptyTurns": []}, {}, "pass"),
    ("empty_turns", {"emptyTurns": ["turn-3"]}, {}, "warn"),
    # ── duplicate_turn_ids ───────────────────────────────────────────────────
    ("duplicate_turn_ids", {"duplicateTurnIds": []}, {}, "pass"),
    ("duplicate_turn_ids", {"duplicateTurnIds": ["turn-2"]}, {}, "fail"),
])
def test_dom_rule(check_id, new_override, old_override, expected, sample_dom_new, sample_dom_old):
    new = {**sample_dom_new, **new_override}
    old = {**sample_dom_old, **old_override}
    results = {c["id"]: c for c in cmp.check_dom_fields(new, old)}
    assert check_id in results, f"Check {check_id!r} not found in results"
    assert results[check_id]["result"] == expected, (
        f"{check_id}: expected {expected!r}, got {results[check_id]['result']!r}. "
        f"explanation: {results[check_id]['explanation']}"
    )


def test_check_dom_fields_returns_correct_count(sample_dom_new, sample_dom_old):
    results = cmp.check_dom_fields(sample_dom_new, sample_dom_old)
    assert len(results) == _TOTAL_CHECKS


def test_check_dom_fields_check_ids(sample_dom_new, sample_dom_old):
    expected_ids = {
        "header_meta", "stats_parts", "user_separation", "shell_label",
        "called_labels", "file_tool_output", "reasoning", "text_part_meta",
        "toc_count", "toc_broken_links", "toc_title_newlines",
        "search_box", "empty_turns", "duplicate_turn_ids",
    }
    ids = {c["id"] for c in cmp.check_dom_fields(sample_dom_new, sample_dom_old)}
    assert ids == expected_ids


def test_check_dom_fields_no_baseline_returns_no_baseline_status(sample_dom_new):
    report = cmp.build_baseline_missing_report(
        new_html="/tmp/new.html",
        new_fields=sample_dom_new,
        new_shots={},
        visual_specs=[],
        outdir="/tmp",
        opts={},
    )
    for c in report["checks"]:
        assert c["result"] == NO_BASELINE, f"{c['id']} should be NO_BASELINE"


def test_baseline_missing_report_includes_all_functional_check_ids(sample_dom_new):
    report = cmp.build_baseline_missing_report(
        new_html="/tmp/new.html",
        new_fields=sample_dom_new,
        new_shots={},
        visual_specs=[],
        outdir="/tmp",
        opts={},
    )
    ids = {c["id"] for c in report["checks"]}
    for cid in ("toc_count", "toc_broken_links", "toc_title_newlines",
                "search_box", "empty_turns", "duplicate_turn_ids"):
        assert cid in ids, f"baseline_missing report missing check {cid!r}"


def test_check_dom_fields_none_old(sample_dom_new):
    results = cmp.check_dom_fields(sample_dom_new, None)
    assert len(results) == _TOTAL_CHECKS
    for c in results:
        assert c["result"] in ("pass", "fail", "warn", "info")


def test_each_check_has_required_keys(sample_dom_new, sample_dom_old):
    for c in cmp.check_dom_fields(sample_dom_new, sample_dom_old):
        for key in ("id", "name", "result", "new_value", "old_value", "explanation"):
            assert key in c, f"Missing key {key!r} in check {c.get('id')}"


def test_toc_mismatch_multiple_broken_links(sample_dom_new, sample_dom_old):
    new = {**sample_dom_new, "brokenTocLinks": ["#turn-5", "#turn-10", "#turn-20"]}
    results = {c["id"]: c for c in cmp.check_dom_fields(new, sample_dom_old)}
    assert results["toc_broken_links"]["result"] == "fail"
    assert "3" in results["toc_broken_links"]["new_value"]


def test_toc_title_newlines_reports_affected_hrefs(sample_dom_new, sample_dom_old):
    affected = ["#turn-1", "#turn-7"]
    new = {**sample_dom_new, "tocLinksWithNewlineInTitle": affected}
    results = {c["id"]: c for c in cmp.check_dom_fields(new, sample_dom_old)}
    c = results["toc_title_newlines"]
    assert c["result"] == "fail"
    assert "#turn-1" in c["explanation"] or "2" in c["new_value"]


def test_duplicate_turn_ids_lists_duplicates(sample_dom_new, sample_dom_old):
    new = {**sample_dom_new, "duplicateTurnIds": ["turn-0", "turn-0"]}
    results = {c["id"]: c for c in cmp.check_dom_fields(new, sample_dom_old)}
    assert results["duplicate_turn_ids"]["result"] == "fail"

