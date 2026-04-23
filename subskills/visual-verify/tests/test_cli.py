import json
import sys
import shutil
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SUBSKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUBSKILL_ROOT / "lib"))
sys.path.insert(0, str(SUBSKILL_ROOT / "scripts"))

import compare as cmp


def _load_verify():
    import importlib
    spec = importlib.util.spec_from_file_location("verify_cli", SUBSKILL_ROOT / "scripts" / "verify.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_inject_visual_cli_path(tmp_path, minimal_report):
    cmp.save_report(minimal_report, str(tmp_path))
    verify = _load_verify()
    verify.inject_visual_result(str(tmp_path), "header", "new summary v1.2 meta", "old summary meta")
    loaded = json.loads((tmp_path / "compare_report.json").read_text())
    assert any(c["id"] == "visual_header" for c in loaded["checks"])


def test_fail_on_missing_baseline_exits_2(tmp_path, sample_dom_new):
    shots = {r: None for r, _, _ in cmp.SCREENSHOT_REGIONS}
    report = cmp.build_baseline_missing_report("/tmp/new.html", sample_dom_new, shots, [], str(tmp_path), {})
    cmp.save_report(report, str(tmp_path))

    verify = _load_verify()

    with pytest.raises(SystemExit) as exc_info:
        args = verify.parse_args.__wrapped__ if hasattr(verify.parse_args, "__wrapped__") else None

        class FakeArgs:
            inject_visual = None
            new = "/tmp/new.html"
            old = None
            outdir = str(tmp_path)
            mode = "both"
            pixel_diff = False
            pixel_threshold = 0.05
            baseline_dom_map = None
            new_dom_map = None
            update_baseline = False
            init_baseline = False
            fail_on_missing_baseline = True
            verbose = False

        with patch.object(verify, "parse_args", return_value=FakeArgs()):
            async def fake_compare(*a, **kw):
                return report

            with patch.object(cmp, "compare_versions", fake_compare):
                with patch.object(cmp, "write_markdown_report", return_value=str(tmp_path / "compare_report.md")):
                    asyncio.run(verify.main())

    assert exc_info.value.code == 2


def test_baseline_missing_no_flag_exits_0(tmp_path, sample_dom_new):
    shots = {r: None for r, _, _ in cmp.SCREENSHOT_REGIONS}
    report = cmp.build_baseline_missing_report("/tmp/new.html", sample_dom_new, shots, [], str(tmp_path), {})
    cmp.save_report(report, str(tmp_path))

    verify = _load_verify()

    class FakeArgs:
        inject_visual = None
        new = "/tmp/new.html"
        old = None
        outdir = str(tmp_path)
        mode = "both"
        pixel_diff = False
        pixel_threshold = 0.05
        baseline_dom_map = None
        new_dom_map = None
        update_baseline = False
        init_baseline = False
        fail_on_missing_baseline = False
        verbose = False

    with patch.object(verify, "parse_args", return_value=FakeArgs()):
        async def fake_compare(*a, **kw):
            return report

        with patch.object(cmp, "compare_versions", fake_compare):
            with patch.object(cmp, "write_markdown_report", return_value=str(tmp_path / "compare_report.md")):
                with pytest.raises(SystemExit) as exc_info:
                    asyncio.run(verify.main())

    assert exc_info.value.code == 0


def test_init_baseline_creates_baseline_dir(tmp_path, sample_dom_new):
    shots = {r: None for r, _, _ in cmp.SCREENSHOT_REGIONS}
    report = cmp.build_baseline_missing_report("/tmp/new.html", sample_dom_new, shots, [], str(tmp_path), {})

    new_html = tmp_path / "chat.html"
    new_html.write_text("<html></html>")

    verify = _load_verify()

    fake_baseline_dir = tmp_path / "fake_baseline"

    with patch.object(verify, "SUBSKILL_ROOT", tmp_path):
        (tmp_path / "assets" / "baseline").mkdir(parents=True, exist_ok=True)
        shutil.rmtree(tmp_path / "assets" / "baseline")

        verify.init_baseline(str(new_html), None, str(tmp_path))

    baseline = tmp_path / "assets" / "baseline"
    assert baseline.exists()
    assert (baseline / "chat.html").exists()
    assert (baseline / "baseline_meta.json").exists()


def test_init_baseline_fails_if_baseline_exists(tmp_path):
    existing_baseline = tmp_path / "assets" / "baseline"
    existing_baseline.mkdir(parents=True)
    (existing_baseline / "chat.html").write_text("<html></html>")

    verify = _load_verify()

    with patch.object(verify, "SUBSKILL_ROOT", tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            verify.init_baseline(str(tmp_path / "new.html"), None, str(tmp_path))

    assert exc_info.value.code == 1


def test_update_baseline_copies_files(tmp_path):
    new_html = tmp_path / "chat.html"
    new_html.write_text("<html></html>")
    shots_dir = tmp_path / "screenshots"
    shots_dir.mkdir()
    (shots_dir / "new_header.png").write_bytes(b"PNG")

    verify = _load_verify()

    with patch.object(verify, "SUBSKILL_ROOT", tmp_path):
        (tmp_path / "assets" / "baseline").mkdir(parents=True, exist_ok=True)
        verify.update_baseline(str(new_html), None, str(tmp_path))

    assert (tmp_path / "assets" / "baseline" / "chat.html").exists()
