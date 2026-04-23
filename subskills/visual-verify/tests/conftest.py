import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUBSKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUBSKILL_ROOT / "lib"))

FIXTURES = Path(__file__).parent / "fixtures"


def make_png_bytes(color=(255, 255, 255, 255), size=(10, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


class FakeLocator:
    def __init__(self, png_bytes: bytes):
        self._png = png_bytes

    async def screenshot(self, path: str):
        Path(path).write_bytes(self._png)


class FakePage:
    def __init__(self, eval_result: dict, png_bytes: bytes = None):
        self._eval = eval_result
        self._png = png_bytes or make_png_bytes()

    async def evaluate(self, script):
        return self._eval

    async def evaluate_handle(self, script):
        return FakeElementHandle(self._png)

    async def close(self):
        pass


class FakeElementHandle:
    def __init__(self, png_bytes: bytes):
        self._png = png_bytes

    def as_element(self):
        return self

    async def screenshot(self, path: str):
        Path(path).write_bytes(self._png)


@pytest.fixture
def white_png(tmp_path):
    p = tmp_path / "white.png"
    p.write_bytes(make_png_bytes((255, 255, 255, 255)))
    return str(p)


@pytest.fixture
def black_png(tmp_path):
    p = tmp_path / "black.png"
    p.write_bytes(make_png_bytes((0, 0, 0, 255)))
    return str(p)


@pytest.fixture
def sample_dom_new():
    return {
        "h1": "Test Conversation",
        "meta": "opencode v1.2.3 · 2 turns · 10 parts",
        "stats": ["10 parts", "2 turns"],
        "userRole": "user",
        "userMetaEl": "2026-01-01",
        "userText": "Hello world",
        "shellLabel": "Shell: ls -la",
        "calledLabels": ["call_omo_agent: explore"],
        "fileTools": [{"label": "Read", "output": "\u202a/some/path/file.txt\u202c contents"}],
        "hasReasoning": True,
        "reasoningCollapsible": True,
        "textPartMeta": True,
        "tocCount": 2,
        "turnCount": 2,
        "brokenTocLinks": [],
        "tocLinksWithNewlineInTitle": [],
        "hasSearchBox": True,
        "emptyTurns": [],
        "duplicateTurnIds": [],
    }


@pytest.fixture
def sample_dom_old():
    return {
        "h1": "Test Conversation",
        "meta": "opencode v1.2.2 · 2 turns · 8 parts",
        "stats": ["8 parts", "2 turns"],
        "userRole": "user",
        "userMetaEl": "2026-01-01",
        "userText": "Hello world",
        "shellLabel": "Shell: ls",
        "calledLabels": ["call_omo_agent: explore"],
        "fileTools": [{"label": "Read", "output": "\u202a/other/file.txt\u202c contents"}],
        "hasReasoning": True,
        "reasoningCollapsible": True,
        "textPartMeta": True,
        "tocCount": 2,
        "turnCount": 2,
        "brokenTocLinks": [],
        "tocLinksWithNewlineInTitle": [],
        "hasSearchBox": True,
        "emptyTurns": [],
        "duplicateTurnIds": [],
    }


@pytest.fixture
def minimal_report(tmp_path, sample_dom_new, sample_dom_old):
    import compare as cmp
    shots = {r: None for r, _, _ in cmp.SCREENSHOT_REGIONS}
    checks = cmp.check_dom_fields(sample_dom_new, sample_dom_old)
    return {
        "metadata": {
            "new_html": "/tmp/new.html",
            "old_html": "/tmp/old.html",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "options": {},
        },
        "summary": {
            "passed": True,
            "pass_count": len([c for c in checks if c["result"] == "pass"]),
            "fail_count": 0,
            "warn_count": len([c for c in checks if c["result"] == "warn"]),
        },
        "checks": checks,
        "visual_specs": [],
        "dom_diff": {},
        "images": {"new": shots, "old": shots},
        "raw": {"new_fields": sample_dom_new, "old_fields": sample_dom_old},
    }


@pytest.fixture
def baseline_missing_report(tmp_path, sample_dom_new):
    import compare as cmp
    shots = {r: None for r, _, _ in cmp.SCREENSHOT_REGIONS}
    return cmp.build_baseline_missing_report(
        new_html="/tmp/new.html",
        new_fields=sample_dom_new,
        new_shots=shots,
        visual_specs=[],
        outdir=str(tmp_path),
        opts={},
    )
