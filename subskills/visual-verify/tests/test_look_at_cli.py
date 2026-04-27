import json
import sys
from pathlib import Path
from unittest.mock import patch

from PIL import Image

SUBSKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUBSKILL_ROOT / "scripts"))

import look_at


def _make_png(path: Path):
    Image.new("RGBA", (12, 12), (255, 255, 255, 255)).save(path)


def test_parse_args_supports_positional_and_flags(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["look_at.py", "img.png", "check header"])
    args = look_at.parse_args()
    assert args.image == "img.png"
    assert args.goal == "check header"


def test_resolve_inputs_prefers_optional_flags():
    class Args:
        image = "pos.png"
        goal = "pos goal"
        image_opt = "opt.png"
        goal_opt = "opt goal"

    image, goal = look_at.resolve_inputs(Args())
    assert image == "opt.png"
    assert goal == "opt goal"


def test_call_opencode_parses_output(tmp_path):
    img = tmp_path / "shot.png"
    _make_png(img)

    opencode_output = '{"type":"text","part":{"text":"summary: 页面结构正常\\nverdict: pass\\nnotes: ok"}}\n'

    class DummyProc:
        returncode = 0
        stdout = opencode_output
        stderr = ""

    with patch.object(look_at.subprocess, "run", return_value=DummyProc()) as mock_run:
        result = look_at.call_opencode(str(img), "check header", "github-copilot/gpt-4o", "default")

    assert "summary: 页面结构正常" in result.summary
    assert "verdict: pass" in result.summary
    assert result.verdict == "pass"
    assert mock_run.called


def test_main_json_output(monkeypatch, tmp_path, capsys):
    img = tmp_path / "shot.png"
    _make_png(img)

    opencode_output = '{"type":"text","part":{"text":"summary: 页面结构正常\\nverdict: info"}}\n'

    class DummyProc:
        returncode = 0
        stdout = opencode_output
        stderr = ""

    monkeypatch.setattr(sys, "argv", ["look_at.py", str(img), "check header", "--json"])
    with patch.object(look_at.subprocess, "run", return_value=DummyProc()):
        look_at.main()

    out = json.loads(capsys.readouterr().out)
    assert out["model"] == "github-copilot/gpt-4o"
    assert out["verdict"] == "info"


def test_build_prompt_mentions_region_and_table(tmp_path):
    img = tmp_path / "new_header.png"
    _make_png(img)
    prompt = look_at.build_prompt(str(img), "检查 header meta")
    assert "当前区域: header" in prompt
    assert "检测结果分析表" in prompt
