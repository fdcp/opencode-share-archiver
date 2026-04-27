import importlib.util
import json
from pathlib import Path


def _load_orchestrate():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("orchestrate_verify", root / "scripts" / "orchestrate_verify.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_write_visual_spec_bundle_creates_files(tmp_path):
    mod = _load_orchestrate()
    compare_dir = tmp_path / "compare"
    specs = [
        {
            "region": "header",
            "goal": "页面顶部 header meta + 统计条",
            "new_path": "/tmp/new_header.png",
            "old_path": "/tmp/old_header.png",
        }
    ]

    bundle_path = mod.write_visual_spec_bundle(compare_dir, specs)

    assert bundle_path.exists()
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert payload[0]["region"] == "header"

    readme = compare_dir / "look_at" / "README.md"
    assert readme.exists()
    content = readme.read_text(encoding="utf-8")
    assert "header" in content
    assert "inject" in content


def test_lookat_is_available_false_for_missing_binary():
    mod = _load_orchestrate()
    assert mod.lookat_is_available("definitely-not-a-real-command") is False
