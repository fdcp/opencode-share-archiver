import asyncio
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import compare as cmp
from conftest import FakePage, make_png_bytes


@pytest.mark.asyncio
async def test_take_screenshots_creates_files(tmp_path):
    shots_dir = tmp_path / "screenshots"
    shots_dir.mkdir()
    page = FakePage(eval_result={}, png_bytes=make_png_bytes())

    async def fake_open(browser, html_path):
        return page

    original = cmp._open_page
    cmp._open_page = fake_open
    try:
        result = await cmp.take_screenshots("/fake/new.html", "new", shots_dir, browser=None)
    finally:
        cmp._open_page = original

    written = [v for v in result.values() if v is not None]
    assert len(written) > 0
    for path in written:
        assert Path(path).exists()


@pytest.mark.asyncio
async def test_take_screenshots_files_are_valid_png(tmp_path):
    shots_dir = tmp_path / "screenshots"
    shots_dir.mkdir()
    page = FakePage(eval_result={}, png_bytes=make_png_bytes((0, 128, 255, 255)))

    async def fake_open(browser, html_path):
        return page

    original = cmp._open_page
    cmp._open_page = fake_open
    try:
        result = await cmp.take_screenshots("/fake/new.html", "new", shots_dir, browser=None)
    finally:
        cmp._open_page = original

    for path in result.values():
        if path:
            img = Image.open(path)
            assert img.size[0] > 0


@pytest.mark.asyncio
async def test_take_screenshots_prefix_naming(tmp_path):
    shots_dir = tmp_path / "screenshots"
    shots_dir.mkdir()
    page = FakePage(eval_result={}, png_bytes=make_png_bytes())

    async def fake_open(browser, html_path):
        return page

    original = cmp._open_page
    cmp._open_page = fake_open
    try:
        result = await cmp.take_screenshots("/fake/old.html", "old", shots_dir, browser=None)
    finally:
        cmp._open_page = original

    for name, path in result.items():
        if path:
            assert Path(path).name.startswith("old_")
