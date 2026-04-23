import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import compare as cmp
from conftest import FakePage


EVAL_RESULT = {
    "h1": "Test",
    "meta": "opencode v1.0.0 · 1 turn",
    "stats": ["5 parts"],
    "userRole": "user",
    "userMetaEl": "2026-01-01",
    "userText": "Hello",
    "shellLabel": "Shell: ls",
    "calledLabels": [],
    "fileTools": [],
    "hasReasoning": False,
    "reasoningCollapsible": False,
    "textPartMeta": False,
}


@pytest.mark.asyncio
async def test_extract_fields_returns_expected_keys():
    page = FakePage(eval_result=EVAL_RESULT)
    result = await cmp.extract_fields.__wrapped__(page) if hasattr(cmp.extract_fields, "__wrapped__") else await _call_extract(page)
    for key in ("h1", "meta", "stats", "userRole", "shellLabel", "hasReasoning", "textPartMeta"):
        assert key in result


@pytest.mark.asyncio
async def test_extract_fields_values_match():
    page = FakePage(eval_result=EVAL_RESULT)
    result = await _call_extract(page)
    assert result["h1"] == "Test"
    assert result["meta"] == "opencode v1.0.0 · 1 turn"
    assert result["hasReasoning"] is False


@pytest.mark.asyncio
async def test_extract_fields_missing_keys_handled():
    page = FakePage(eval_result={})
    result = await _call_extract(page)
    assert isinstance(result, dict)


async def _call_extract(fake_page):
    original_open = cmp._open_page

    async def fake_open(browser, html_path):
        return fake_page

    cmp._open_page = fake_open
    try:
        result = await cmp.extract_fields("/fake/path.html", browser=None)
    finally:
        cmp._open_page = original_open
    return result
