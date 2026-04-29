#!/usr/bin/env python3
"""Archive a local OpenCode session by session ID.

This command shares the target session and archives the generated share URL into a
self-contained offline HTML archive:

  <output_dir>/<session_id>/

Outputs:
  - conversation_final.json  normalized session archive
  - conversation.json        raw exported JSON
  - chat.html                self-contained HTML archive viewer
"""

from __future__ import annotations

import argparse
import datetime as dt
import html as html_module
import json
import subprocess
import sys
from pathlib import Path


def esc(text: object) -> str:
    return html_module.escape(str(text))


def parse_args():
    p = argparse.ArgumentParser(description="Archive an OpenCode session by session ID")
    p.add_argument("session_id", help="OpenCode session ID, e.g. ses_...")
    p.add_argument("output_dir", help="Directory to write output files into")
    return p.parse_args()


def format_time(epoch_ms: int | None) -> str:
    if not epoch_ms:
        return ""
    try:
        return dt.datetime.fromtimestamp(epoch_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(epoch_ms)


def format_meta(info: dict) -> str:
    parts = []
    role = info.get("role")
    if role:
        parts.append(str(role))
    agent = info.get("agent")
    if agent:
        parts.append(str(agent))
    model = info.get("model") or {}
    provider_id = model.get("providerID")
    model_id = model.get("modelID")
    if provider_id and model_id:
        parts.append(f"{provider_id}/{model_id}")
    time_info = info.get("time") or {}
    created = time_info.get("created")
    if created:
        parts.append(format_time(created))
    return " · ".join(parts)


def normalize_export(export_data: dict) -> dict:
    info = export_data.get("info", {})
    normalized_messages = []
    total_parts = 0
    for idx, message in enumerate(export_data.get("messages", [])):
        msg_info = message.get("info", {})
        parts = []
        for p in message.get("parts", []):
            ptype = p.get("type", "unknown")
            total_parts += 1
            item = {"type": ptype}
            for key in ("text", "html", "snapshot", "reason", "cost", "tokens", "snapshot", "id", "messageID", "sessionID"):
                if key in p:
                    item[key] = p[key]
            if ptype not in {"text", "step-start", "step-finish"}:
                item["raw"] = {k: v for k, v in p.items() if k not in {"type", "text", "html"}}
            parts.append(item)

        normalized_messages.append({
            "turnIndex": idx,
            "role": msg_info.get("role", ""),
            "meta": format_meta(msg_info),
            "messageID": msg_info.get("id", ""),
            "sessionID": msg_info.get("sessionID", ""),
            "parts": parts,
        })

    summary = {
        "messages": len(normalized_messages),
        "parts": total_parts,
        "users": sum(1 for m in normalized_messages if m.get("role") == "user"),
        "assistants": sum(1 for m in normalized_messages if m.get("role") == "assistant"),
    }

    return {
        "info": info,
        "summary": summary,
        "messages": normalized_messages,
        "raw": export_data,
    }


def render_part(part: dict) -> str:
    ptype = part.get("type", "unknown")
    if ptype == "text":
        text = part.get("text", "")
        return f'<div class="part text-part"><div class="part-label">text</div><pre>{esc(text)}</pre></div>'
    if ptype in {"step-start", "step-finish"}:
        return f'<div class="part meta-part"><div class="part-label">{esc(ptype)}</div><pre>{esc(json.dumps(part, ensure_ascii=False, indent=2))}</pre></div>'
    if "html" in part and part["html"]:
        return f'<div class="part html-part"><div class="part-label">{esc(ptype)}</div><div class="html-content">{part["html"]}</div></div>'
    return f'<div class="part raw-part"><div class="part-label">{esc(ptype)}</div><pre>{esc(json.dumps(part, ensure_ascii=False, indent=2))}</pre></div>'


def render_html(archive: dict, session_id: str) -> str:
    info = archive.get("info", {})
    title = info.get("title") or session_id
    slug = info.get("slug") or ""
    version = info.get("version") or ""
    summary = archive.get("summary", {})
    messages = archive.get("messages", [])
    toc = []
    bodies = []
    for msg in messages:
        idx = msg["turnIndex"]
        role = msg.get("role", "message")
        label = f"#{idx + 1} {role}"
        toc.append(f'<li><a href="#message-{idx}">{esc(label)}</a></li>')
        search_text = esc(" ".join([msg.get("meta", ""), role, json.dumps(msg.get("parts", []), ensure_ascii=False)]).lower())
        parts_html = "".join(render_part(p) for p in msg.get("parts", []))
        bodies.append(f'''
        <details class="message {esc(role)}" id="message-{idx}" open data-search="{search_text}">
          <summary>
            <span class="role">{esc(role or 'message')}</span>
            <span class="meta">{esc(msg.get('meta', ''))}</span>
          </summary>
          <div class="message-body">
            <div class="message-id">{esc(msg.get('messageID', ''))}</div>
            {parts_html}
          </div>
        </details>
        ''')

    toc_html = "".join(toc)
    body_html = "".join(bodies)
    created = info.get("time", {}).get("created")
    updated = info.get("time", {}).get("updated")
    created_txt = format_time(created)
    updated_txt = format_time(updated)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenCode Session - {esc(session_id)}</title>
<style>
  :root {{
    --bg:#0f0e0e; --bg2:#181616; --bg3:#201d1d; --border:#2a2525; --text:#e8e4e0; --text2:#b0a8a0; --text3:#807870; --accent:#6b8afd; --green:#4a9a4a;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans SC',sans-serif; background:var(--bg); color:var(--text); }}
  .wrap {{ max-width:1000px; margin:0 auto; padding:24px 20px 80px; }}
  .header {{ border-bottom:1px solid var(--border); padding-bottom:14px; margin-bottom:18px; }}
  h1 {{ margin:0 0 6px; font-size:22px; }}
  .meta {{ color:var(--text3); font-size:13px; }}
  .stats {{ display:flex; gap:10px; flex-wrap:wrap; margin:16px 0; }}
  .stat {{ background:var(--bg2); border:1px solid var(--border); border-radius:8px; padding:8px 12px; }}
  .stat strong {{ display:block; font-size:18px; }}
  .search {{ margin:16px 0 20px; }}
  .search input {{ width:100%; padding:10px 12px; border-radius:8px; background:var(--bg2); border:1px solid var(--border); color:var(--text); }}
  .toc {{ background:var(--bg2); border:1px solid var(--border); border-radius:8px; padding:14px 18px; margin-bottom:20px; }}
  .toc ol {{ margin:0; padding-left:20px; column-count:2; column-gap:24px; }}
  .toc li {{ margin:0 0 5px; break-inside:avoid; }}
  .toc a {{ color:var(--accent); text-decoration:none; }}
  details.message {{ background:var(--bg2); border:1px solid var(--border); border-radius:10px; margin:0 0 14px; overflow:hidden; }}
  details.message summary {{ cursor:pointer; padding:12px 14px; display:flex; gap:10px; align-items:center; }}
  details.message summary::-webkit-details-marker {{ display:none; }}
  .role {{ font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.8px; color:var(--green); }}
  .assistant .role {{ color:var(--accent); }}
  .meta {{ font-size:12px; color:var(--text3); }}
  .message-body {{ padding:0 14px 14px; }}
  .message-id {{ color:var(--text3); font-size:11px; margin-bottom:8px; }}
  .part {{ margin-bottom:10px; border:1px solid var(--border); border-radius:8px; background:var(--bg); padding:10px 12px; }}
  .part-label {{ font-size:12px; font-weight:700; margin-bottom:8px; color:var(--accent); }}
  .part pre {{ margin:0; white-space:pre-wrap; word-break:break-word; color:var(--text2); font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:12px; line-height:1.6; }}
  .html-content {{ color:var(--text); }}
  .html-content p {{ margin:0 0 8px; }}
  @media (max-width:700px) {{ .toc ol {{ column-count:1; }} }}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>OpenCode Session {esc(session_id)}</h1>
    <div class="meta">{esc(title)}{f' · {esc(slug)}' if slug else ''}{f' · v{esc(version)}' if version else ''}</div>
  </div>
  <div class="stats">
    <div class="stat"><strong>{len(messages)}</strong><span>messages</span></div>
    <div class="stat"><strong>{summary.get('parts', 0)}</strong><span>parts</span></div>
    <div class="stat"><strong>{summary.get('users', 0)}</strong><span>user msgs</span></div>
    <div class="stat"><strong>{summary.get('assistants', 0)}</strong><span>assistant msgs</span></div>
    <div class="stat"><strong>{created_txt or 'n/a'}</strong><span>created</span></div>
    <div class="stat"><strong>{updated_txt or 'n/a'}</strong><span>updated</span></div>
  </div>
  <div class="search"><input id="searchInput" placeholder="Search messages..." oninput="filterMessages(this.value)"></div>
  <div class="toc"><ol>{toc_html}</ol></div>
  {body_html}
</div>
<script>
function filterMessages(q) {{
  const query = q.trim().toLowerCase();
  document.querySelectorAll('details.message').forEach(el => {{
    const hay = (el.dataset.search || '').toLowerCase();
    el.style.display = !query || hay.includes(query) ? '' : 'none';
  }});
}}
</script>
</body>
</html>'''


def write_outputs(archive: dict, session_id: str, output_dir: str) -> Path:
    root = Path(output_dir) / session_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "conversation_final.json").write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "conversation.json").write_text(json.dumps(archive.get("raw", {}), ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "chat.html").write_text(render_html(archive, session_id), encoding="utf-8")
    return root


def archive_db(session_id: str, output_dir: str) -> Path:
    script = Path(__file__).with_name("run_db.py")
    out = Path(output_dir) / session_id
    proc = subprocess.run([sys.executable, str(script), session_id, str(out)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or f"run_db.py exited with {proc.returncode}")
    print(proc.stdout, end="")
    return out


def main():
    args = parse_args()
    out_dir = archive_db(args.session_id, args.output_dir)
    print(f"[oc-archive] OK — wrote DB-based archive to {out_dir}")
    print(f"  HTML : {out_dir / 'chat.html'}")


if __name__ == "__main__":
    main()
