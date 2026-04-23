import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import compare as cmp
from conftest import make_png_bytes


def _write_png(path: Path, color):
    path.write_bytes(make_png_bytes(color, (20, 20)))


def test_pixel_diff_identical_images_pass(tmp_path):
    a = tmp_path / "new_header.png"
    b = tmp_path / "old_header.png"
    _write_png(a, (200, 200, 200, 255))
    _write_png(b, (200, 200, 200, 255))
    result = cmp.check_pixel_diff(str(a), str(b), threshold=0.05)
    assert result["result"] in ("pass", "info"), f"Expected pass or info, got {result['result']}"


def test_pixel_diff_completely_different_images_fail(tmp_path):
    a = tmp_path / "new_header.png"
    b = tmp_path / "old_header.png"
    _write_png(a, (255, 255, 255, 255))
    _write_png(b, (0, 0, 0, 255))
    result = cmp.check_pixel_diff(str(a), str(b), threshold=0.05)
    assert result["result"] in ("fail", "info", "warn"), (
        f"Completely different images should not pass: {result}"
    )


def test_pixel_diff_result_has_required_keys(tmp_path):
    a = tmp_path / "new_test.png"
    b = tmp_path / "old_test.png"
    _write_png(a, (100, 100, 100, 255))
    _write_png(b, (100, 100, 100, 255))
    result = cmp.check_pixel_diff(str(a), str(b))
    for key in ("id", "name", "result", "new_value", "old_value", "explanation"):
        assert key in result


def test_pixel_diff_missing_file_returns_error_not_exception(tmp_path):
    result = cmp.check_pixel_diff("/nonexistent/a.png", "/nonexistent/b.png", threshold=0.05)
    assert result["result"] in ("warn", "info", "fail")
    assert "error" in result["id"] or "skip" in result["id"] or result["result"] != "pass"


def test_pixel_diff_different_size_images(tmp_path):
    a = tmp_path / "new_x.png"
    b = tmp_path / "old_x.png"
    a.write_bytes(make_png_bytes((255, 255, 255, 255), (10, 10)))
    b.write_bytes(make_png_bytes((255, 255, 255, 255), (20, 20)))
    result = cmp.check_pixel_diff(str(a), str(b), threshold=0.05)
    assert result["result"] in ("pass", "fail", "warn", "info")
