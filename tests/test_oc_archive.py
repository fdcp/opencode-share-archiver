from __future__ import annotations

import json
import subprocess
import sys
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import oc_archive  # type: ignore


def test_normalize_export_and_render_html(tmp_path):
    export_data = {
        "info": {
            "title": "Demo session",
            "slug": "demo-session",
            "version": "1.0.0",
            "time": {"created": 1710000000000, "updated": 1710003600000},
        },
        "messages": [
            {
                "info": {"role": "user", "id": "m1", "sessionID": "ses_123"},
                "parts": [{"type": "text", "text": "hello"}],
            },
            {
                "info": {"role": "assistant", "id": "m2", "sessionID": "ses_123"},
                "parts": [{"type": "step-start", "reason": "testing"}],
            },
        ],
    }

    archive = oc_archive.normalize_export(export_data)
    out_dir = oc_archive.write_outputs(archive, "ses_123", str(tmp_path))

    assert out_dir == tmp_path / "ses_123"
    assert json.loads((out_dir / "conversation.json").read_text(encoding="utf-8")) == export_data
    html = (out_dir / "chat.html").read_text(encoding="utf-8")
    assert "OpenCode Session ses_123" in html
    assert "Demo session" in html
    assert "hello" in html


def test_run_share_uses_session_id_and_extracts_url(monkeypatch):
    calls = {}

    class Proc:
        returncode = 0
        stdout = '{"type":"text","sessionID":"ses_abc"}'
        stderr = ""

    def fake_run(cmd, capture_output, text):
        calls["cmd"] = cmd
        calls["capture_output"] = capture_output
        calls["text"] = text
        return Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(oc_archive, "query_share_url", lambda session_id: "https://opncd.ai/share/ErCg0NRB")

    data = oc_archive.run_share("ses_abc")

    assert data == "https://opncd.ai/share/ErCg0NRB"
    assert calls["cmd"] == ["opencode", "run", "--session", "ses_abc", "--share", "--format", "json", "--dangerously-skip-permissions", "--model", "github-copilot/gpt-4o", "/share"]
    assert calls["capture_output"] is True
    assert calls["text"] is True


def test_run_unshare_deletes_share_row(monkeypatch):
    db_dir = Path(__file__).resolve().parent / "tmp-db"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / "opencode.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("create table session_share(session_id text primary key, id text, secret text, url text, time_created integer, time_updated integer)")
        conn.execute("create table session(id text primary key, share_url text)")
        conn.execute("insert into session_share values(?,?,?,?,?,?)", ("ses_abc", "abc", "secret", "https://opncd.ai/share/abc", 1, 1))
        conn.execute("insert into session values(?, ?)", ("ses_abc", "https://opncd.ai/share/abc"))
        conn.commit()

    monkeypatch.setattr(oc_archive, "get_db_path", lambda: str(db_path))

    oc_archive.run_unshare("ses_abc")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("select count(*) from session_share where session_id=?", ("ses_abc",)).fetchone()[0] == 0
        assert conn.execute("select share_url from session where id=?", ("ses_abc",)).fetchone()[0] is None
