#!/usr/bin/env python3
import sys
import os
import json
import re
import html as html_module
import sqlite3
import subprocess
from pathlib import Path

if len(sys.argv) < 3:
    print("Usage: python3 run_db.py <session_id> <output_dir> [--validate]", file=sys.stderr)
    sys.exit(1)

SESSION_ID = sys.argv[1]
OUTPUT_DIR = sys.argv[2]
RUN_VALIDATE = "--validate" in sys.argv
os.makedirs(OUTPUT_DIR, exist_ok=True)


def esc(text):
    return html_module.escape(str(text))


def get_db_path():
    proc = subprocess.run(["opencode", "db", "path"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip())
    return proc.stdout.strip()


def format_output_text(text):
    if not text:
        return ""
    lines = text.split('\n')
    formatted = []
    for line in lines:
        escaped = esc(line)
        if line.startswith('$ '):
            formatted.append(f'<div class="cmd-line"><span class="prompt">$</span> {escaped[2:]}</div>')
        elif line.startswith('+') and not line.startswith('+++'):
            formatted.append(f'<div class="line-added">{escaped}</div>')
        elif line.startswith('-') and not line.startswith('---'):
            formatted.append(f'<div class="line-removed">{escaped}</div>')
        else:
            formatted.append(f'<div class="line-normal">{escaped}</div>')
    return '\n'.join(formatted)


def render_text_as_html(text):
    if not text:
        return ""
    escaped = esc(text)
    escaped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)
    escaped = re.sub(r'`([^`]+)`', r'<code>\1</code>', escaped)
    lines = escaped.split('\n')
    out = []
    in_pre = False
    pre_buf = []
    for line in lines:
        if line.startswith('    ') or line.startswith('\t'):
            if not in_pre:
                in_pre = True
                pre_buf = []
            pre_buf.append(line)
        else:
            if in_pre:
                out.append('<pre>' + '\n'.join(pre_buf) + '</pre>')
                in_pre = False
                pre_buf = []
            if line.strip():
                out.append(f'<p>{line}</p>')
            else:
                out.append('<br>')
    if in_pre:
        out.append('<pre>' + '\n'.join(pre_buf) + '</pre>')
    return '\n'.join(out)


print(f"[1/3] Reading DB for session {SESSION_ID} ...")

db_path = get_db_path()
conn = sqlite3.connect(db_path)

session_row = conn.execute(
    "select id, title, version, time_created, time_updated from session where id=?",
    (SESSION_ID,)
).fetchone()
if not session_row:
    raise SystemExit(f"Session {SESSION_ID} not found in DB")

session_title = session_row[1] or SESSION_ID
session_version = session_row[2] or ""

msg_rows = conn.execute(
    "select id, data from message where session_id=? order by time_created asc",
    (SESSION_ID,)
).fetchall()

part_rows = conn.execute(
    "select id, message_id, data from part where session_id=? order by time_created asc",
    (SESSION_ID,)
).fetchall()

parts_by_msg = {}
for pid, mid, pdata in part_rows:
    try:
        d = json.loads(pdata) if isinstance(pdata, str) else pdata
    except Exception:
        continue
    parts_by_msg.setdefault(mid, []).append(d)

turns = []
current_turn = None

def flush_turn():
    if current_turn is not None:
        turns.append(current_turn)

for mid, mdata in msg_rows:
    try:
        msg = json.loads(mdata) if isinstance(mdata, str) else mdata
    except Exception:
        continue

    role = msg.get("role", "")
    if role == "user":
        flush_turn()
        parts = parts_by_msg.get(mid, [])
        user_text = ""
        for p in parts:
            if p.get("type") == "text":
                user_text = p.get("text", "")
                break
        if not user_text:
            user_text = msg.get("content", "") or ""
            if isinstance(user_text, list):
                texts = [c.get("text", "") for c in user_text if isinstance(c, dict) and c.get("type") == "text"]
                user_text = "\n".join(texts)
        current_turn = {"userMessage": user_text, "meta": "", "assistantContent": []}

    elif role == "assistant":
        if current_turn is None:
            current_turn = {"userMessage": "", "meta": "", "assistantContent": []}
        parts = parts_by_msg.get(mid, [])
        for p in parts:
            ptype = p.get("type", "")
            if ptype == "text":
                current_turn["assistantContent"].append({
                    "type": "text",
                    "text": p.get("text", ""),
                })
            elif ptype == "reasoning":
                current_turn["assistantContent"].append({
                    "type": "reasoning",
                    "text": p.get("text", ""),
                })
            elif ptype == "tool":
                state = p.get("state", {})
                raw_tool = p.get("tool", "") or ""
                tool_name = state.get("title", "") or raw_tool
                inp = state.get("input", {}) if isinstance(state.get("input"), dict) else {}
                out = (state.get("output", "") or "") if isinstance(state, dict) else ""

                if raw_tool in ("read", "write", "edit"):
                    file_path = inp.get("filePath", "")
                    if file_path:
                        fp = Path(file_path)
                        dir_part = str(fp.parent) + "/" if str(fp.parent) != "." else ""
                        file_marker = f"\u202a{dir_part}\u202c{fp.name}"
                        out = file_marker + ("\n" + out if out else "")
                    name = tool_name or raw_tool
                else:
                    desc = inp.get("description", "")
                    cmd = inp.get("command", "")
                    name = desc or (cmd[:120] if cmd else tool_name)

                current_turn["assistantContent"].append({
                    "type": "tool",
                    "toolType": raw_tool or tool_name,
                    "name": name,
                    "outputText": out,
                })
            elif ptype == "compaction":
                current_turn["assistantContent"].append({
                    "type": "compaction",
                    "label": "Context compacted",
                })
            elif ptype == "patch":
                files = p.get("files", [])
                label = "Patch: " + ", ".join(Path(f).name for f in files) if files else "Patch"
                current_turn["assistantContent"].append({
                    "type": "patch",
                    "label": label,
                    "hash": p.get("hash", ""),
                    "files": files,
                })
            elif ptype in ("step-start", "step-finish"):
                pass

flush_turn()

for i, t in enumerate(turns):
    t["turnIndex"] = i

total_parts = sum(len(t.get("assistantContent", [])) for t in turns)
print(f"  Extracted {len(turns)} turns, {total_parts} parts total")

json_path = os.path.join(OUTPUT_DIR, "conversation_final.json")
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(turns, f, ensure_ascii=False, indent=2)
print(f"  Saved {json_path}")

print(f"[2/3] Generating chat.html ...")

turns_html = []
toc_items = []

for i, turn in enumerate(turns):
    user_msg = turn.get("userMessage", "")
    meta = turn.get("meta", "")
    assistant_parts = turn.get("assistantContent", [])

    toc_title_attr = re.sub(r'[\n\r\t\u2028\u2029]+', ' ', user_msg[:200]) if user_msg else f"Turn {i+1}"
    toc_title = toc_title_attr[:80] if user_msg else f"Turn {i+1}"
    toc_items.append(
        f'<li><a href="#turn-{i}" title="{esc(toc_title_attr)}">{esc(toc_title)}</a></li>'
    )

    user_html = f'''
    <div class="msg user-msg">
        <div class="msg-header">
            <span class="msg-role user-role">User</span>
            <span class="msg-meta">{esc(meta)}</span>
        </div>
        <div class="msg-body user-body">
            <div class="msg-text">{esc(user_msg)}</div>
        </div>
    </div>'''

    assistant_html_parts = []
    for part in assistant_parts:
        ptype = part.get("type", "")

        if ptype == "reasoning":
            content = render_text_as_html(part.get("text", ""))
            if content:
                assistant_html_parts.append(f'''
            <div class="part reasoning-part">
                <div class="part-header reasoning-header" onclick="this.parentElement.classList.toggle('collapsed')">
                    <span class="part-icon">&#x1F4AD;</span>
                    <span class="part-label">Thinking</span>
                    <span class="toggle-hint">click to toggle</span>
                </div>
                <div class="part-content reasoning-content">{content}</div>
            </div>''')

        elif ptype == "tool":
            tool_type = part.get("toolType", "")
            name = part.get("name", "")
            if tool_type == "bash":
                label = f"Shell: {name}" if name else "Shell"
            elif tool_type in ("read", "write", "edit"):
                label = f"{tool_type.capitalize()}: {name}" if name else tool_type.capitalize()
            else:
                label = f"{tool_type}: {name}" if name else tool_type
            output_text = part.get("outputText", "")
            if output_text:
                formatted_output = format_output_text(output_text)
                assistant_html_parts.append(f'''
            <div class="part tool-part">
                <div class="part-header tool-header" onclick="this.parentElement.classList.toggle('collapsed')">
                    <span class="part-icon">&#x1F527;</span>
                    <span class="part-label">{esc(label)}</span>
                    <span class="toggle-hint">click to toggle</span>
                </div>
                <div class="part-content tool-content">
                    <pre class="tool-output">{formatted_output}</pre>
                </div>
            </div>''')
            else:
                assistant_html_parts.append(f'''
            <div class="part tool-part no-output">
                <div class="part-header tool-header">
                    <span class="part-icon">&#x1F527;</span>
                    <span class="part-label">{esc(label)}</span>
                    <span class="no-output-hint">(no output)</span>
                </div>
            </div>''')

        elif ptype == "text":
            content = render_text_as_html(part.get("text", ""))
            if content:
                assistant_html_parts.append(f'''
            <div class="part text-part">
                <div class="part-content text-content">{content}</div>
            </div>''')

        elif ptype == "compaction":
            label = esc(part.get("label", "Context compacted"))
            assistant_html_parts.append(f'''
            <div class="compaction-divider">
                <span class="compaction-line"></span>
                <span class="compaction-label">{label}</span>
                <span class="compaction-line"></span>
            </div>''')

        elif ptype == "patch":
            label = esc(part.get("label", "Patch"))
            hash_val = esc(part.get("hash", ""))
            files_html = "".join(f'<div class="patch-file">{esc(f)}</div>' for f in part.get("files", []))
            assistant_html_parts.append(f'''
            <div class="part patch-part">
                <div class="part-header patch-header" onclick="this.parentElement.classList.toggle('collapsed')">
                    <span class="part-icon">&#x1F4CB;</span>
                    <span class="part-label">{label}</span>
                    <span class="toggle-hint">click to toggle</span>
                </div>
                <div class="part-content patch-content">
                    <div class="patch-hash">hash: {hash_val}</div>
                    {files_html}
                </div>
            </div>''')

    assistant_html = f'''
    <div class="msg assistant-msg">
        <div class="msg-header">
            <span class="msg-role assistant-role">Assistant</span>
        </div>
        <div class="msg-body assistant-body">
            {''.join(assistant_html_parts)}
        </div>
    </div>''' if assistant_html_parts else ''

    turns_html.append(f'''
    <div class="turn" id="turn-{i}">
        <div class="turn-number">#{i+1}</div>
        {user_html}
        {assistant_html}
    </div>''')

toc_html = '<ol>' + ''.join(toc_items) + '</ol>'

page = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenCode Session - {esc(SESSION_ID)}</title>
<style>
:root {{
    --bg: #0f0e0e; --bg2: #181616; --bg3: #201d1d; --bg4: #2a2626;
    --text: #e8e4e0; --text2: #b0a8a0; --text3: #807870; --text4: #605850;
    --border: #2a2525; --border2: #3a3535;
    --user-accent: #4a9a4a; --user-bg: #141e14; --user-border: #1e2e1e;
    --assistant-accent: #6b8afd;
    --reasoning-accent: #8b7afd; --reasoning-bg: #16141e; --reasoning-border: #28203a;
    --tool-accent: #5ba85b; --tool-bg: #141e14; --tool-border: #1e3a1e;
    --patch-accent: #da8a3a; --patch-bg: #1e1a14; --patch-border: #3a2e1e;
    --added: #4a9a4a; --removed: #da4a4a; --cmd: #7adfb8; --prompt: #5ba85b;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
html {{ scroll-behavior:smooth; }}
body {{
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans SC',Roboto,sans-serif;
    font-size:14px; line-height:1.6; color:var(--text); background:var(--bg);
}}
.page-container {{ max-width:900px; margin:0 auto; padding:24px 20px 80px; }}
.page-header {{ margin-bottom:24px; padding-bottom:16px; border-bottom:1px solid var(--border); }}
.page-header h1 {{ font-size:22px; font-weight:600; margin-bottom:6px; }}
.page-header .meta {{ color:var(--text3); font-size:13px; }}
.toc {{ background:var(--bg2); border:1px solid var(--border); border-radius:8px; padding:16px 20px 16px 32px; margin-bottom:28px; }}
.toc h3 {{ font-size:13px; color:var(--text3); margin-bottom:10px; text-transform:uppercase; letter-spacing:0.5px; }}
.toc ol {{ column-count:2; column-gap:24px; list-style:decimal; }}
.toc li {{ margin-bottom:4px; break-inside:avoid; font-size:13px; }}
.toc a {{ color:var(--assistant-accent); text-decoration:none; }}
.toc a:hover {{ text-decoration:underline; }}
.turn {{ margin-bottom:28px; position:relative; padding-left:40px; }}
.turn-number {{ position:absolute; left:0; top:4px; font-size:12px; font-weight:600; color:var(--text4); width:30px; text-align:right; }}
.msg {{ margin-bottom:8px; }}
.msg-header {{ display:flex; align-items:center; gap:8px; margin-bottom:4px; }}
.msg-role {{ font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.8px; }}
.user-role {{ color:var(--user-accent); }}
.assistant-role {{ color:var(--assistant-accent); }}
.msg-meta {{ color:var(--text4); font-size:11px; }}
.user-body {{ background:var(--user-bg); border:1px solid var(--user-border); border-radius:8px; padding:10px 14px; }}
.msg-text {{ color:var(--text); font-size:14px; white-space:pre-wrap; word-break:break-word; line-height:1.6; }}
.assistant-body {{ background:var(--bg2); border-radius:8px; padding:10px 14px; }}
.part {{ margin-bottom:10px; }}
.part:last-child {{ margin-bottom:0; }}
.part-header {{ display:flex; align-items:center; gap:6px; margin-bottom:6px; cursor:pointer; user-select:none; padding:3px 6px; border-radius:4px; transition:background 0.15s; }}
.part-header:hover {{ background:var(--bg3); }}
.part-icon {{ font-size:13px; }}
.part-label {{ font-size:12px; font-weight:600; }}
.reasoning-header .part-label {{ color:var(--reasoning-accent); }}
.tool-header .part-label {{ color:var(--tool-accent); }}
.patch-header .part-label {{ color:var(--patch-accent); }}
.toggle-hint {{ font-size:10px; color:var(--text4); margin-left:auto; }}
.no-output-hint {{ font-size:11px; color:var(--text4); margin-left:8px; }}
.reasoning-part {{ border-left:3px solid var(--reasoning-border); padding-left:10px; margin-left:2px; }}
.reasoning-content {{ color:var(--text2); font-size:13px; line-height:1.6; }}
.reasoning-content p {{ margin-bottom:6px; }}
.reasoning-content code {{ background:var(--bg3); padding:1px 4px; border-radius:3px; font-family:'SF Mono','Fira Code',monospace; font-size:12px; }}
.tool-part {{ border:1px solid var(--tool-border); border-radius:6px; padding:8px 10px; background:var(--tool-bg); }}
.tool-part.no-output {{ padding:4px 10px; }}
.tool-output {{ font-family:'SF Mono','Fira Code',monospace; font-size:12px; line-height:1.5; color:var(--text2); max-height:500px; overflow-y:auto; white-space:pre; word-break:normal; background:var(--bg); border-radius:4px; padding:8px 10px; margin:0; }}
.cmd-line {{ color:var(--cmd); }}
.prompt {{ color:var(--prompt); font-weight:700; }}
.line-added {{ color:var(--added); }}
.line-removed {{ color:var(--removed); }}
.line-normal {{ color:var(--text2); }}
.text-content {{ color:var(--text); line-height:1.7; font-size:14px; }}
.text-content p {{ margin-bottom:8px; }}
.text-content code {{ background:var(--bg3); padding:1px 5px; border-radius:3px; font-family:'SF Mono','Fira Code',monospace; font-size:12px; color:var(--cmd); }}
.text-content pre {{ background:var(--bg); padding:12px 14px; border-radius:6px; overflow-x:auto; margin:8px 0; font-family:'SF Mono','Fira Code',monospace; font-size:12px; line-height:1.5; border:1px solid var(--border); }}
.text-content pre code {{ background:none; padding:0; color:var(--text2); }}
.text-content ul,.text-content ol {{ margin-left:20px; margin-bottom:8px; }}
.text-content li {{ margin-bottom:4px; }}
.text-content h1,.text-content h2,.text-content h3,.text-content h4 {{ margin:14px 0 6px; color:var(--text); font-weight:600; }}
.text-content h1 {{ font-size:18px; }} .text-content h2 {{ font-size:16px; }} .text-content h3 {{ font-size:15px; }}
.text-content a {{ color:var(--assistant-accent); text-decoration:none; }}
.text-content a:hover {{ text-decoration:underline; }}
.text-content blockquote {{ border-left:3px solid var(--border2); padding-left:12px; color:var(--text2); margin:8px 0; }}
.text-content table {{ border-collapse:collapse; width:100%; margin:8px 0; font-size:13px; }}
.text-content th,.text-content td {{ border:1px solid var(--border); padding:6px 10px; text-align:left; }}
.text-content th {{ background:var(--bg3); font-weight:600; }}
.text-content strong {{ color:var(--text); font-weight:600; }}
.text-content hr {{ border:none; border-top:1px solid var(--border); margin:12px 0; }}
.compaction-divider {{ display:flex; align-items:center; gap:12px; margin:12px 0; color:var(--text4); font-size:11px; text-transform:uppercase; letter-spacing:0.5px; }}
.compaction-line {{ flex:1; height:1px; background:var(--border); }}
.patch-part {{ border:1px solid var(--patch-border); border-radius:6px; padding:8px 10px; background:var(--patch-bg); }}
.patch-hash {{ font-family:'SF Mono','Fira Code',monospace; font-size:11px; color:var(--text3); margin-bottom:4px; }}
.patch-file {{ font-family:'SF Mono','Fira Code',monospace; font-size:12px; color:var(--text2); padding:2px 0; }}
.part.collapsed .part-content {{ display:none; }}
.stats {{ display:flex; gap:12px; margin-bottom:20px; flex-wrap:wrap; }}
.stat {{ background:var(--bg2); border:1px solid var(--border); border-radius:6px; padding:6px 12px; font-size:13px; }}
.stat-value {{ font-weight:700; color:var(--text); }}
.stat-label {{ color:var(--text3); margin-left:4px; }}
.search-box {{ margin-bottom:20px; }}
.search-box input {{ width:100%; padding:8px 12px; background:var(--bg2); border:1px solid var(--border); border-radius:6px; color:var(--text); font-size:13px; outline:none; }}
.search-box input:focus {{ border-color:var(--assistant-accent); }}
.search-box input::placeholder {{ color:var(--text4); }}
@media (max-width:640px) {{
    .toc ol {{ column-count:1; }}
    .stats {{ flex-direction:column; gap:8px; }}
    .turn {{ padding-left:24px; }}
    .turn-number {{ font-size:10px; width:18px; }}
    .page-container {{ padding:12px 12px 40px; }}
}}
</style>
</head>
<body>
<div class="page-container">
<div class="page-header">
    <h1>{esc(session_title)}</h1>
    <div class="meta">{esc(SESSION_ID)} · v{esc(session_version)}</div>
</div>
<div class="stats">
    <div class="stat"><span class="stat-value">{len(turns)}</span><span class="stat-label">turns</span></div>
    <div class="stat"><span class="stat-value">{total_parts}</span><span class="stat-label">parts</span></div>
</div>
<div class="search-box">
    <input type="text" id="searchInput" placeholder="Search conversation..." oninput="filterTurns(this.value)">
</div>
<div class="toc">
    <h3>Table of Contents</h3>
    {toc_html}
</div>
{''.join(turns_html)}
</div>
<script>
(function(){{
    var idx=[];
    document.addEventListener('DOMContentLoaded',function(){{
        document.querySelectorAll('.turn').forEach(function(t){{
            idx.push({{el:t,text:t.textContent.toLowerCase()}});
        }});
    }});
    window.filterTurns=function(query){{
        var q=query.toLowerCase();
        requestAnimationFrame(function(){{
            idx.forEach(function(o){{
                o.el.style.display=(!q||o.text.includes(q))?'':'none';
            }});
        }});
    }};
}})();
</script>
</body>
</html>'''

html_path = os.path.join(OUTPUT_DIR, "chat.html")
with open(html_path, "w", encoding="utf-8") as f:
    f.write(page)
print(f"  Saved {html_path}: {len(page):,} chars")

json_copy = os.path.join(OUTPUT_DIR, "conversation.json")
with open(json_copy, "w", encoding="utf-8") as f:
    json.dump(turns, f, ensure_ascii=False, indent=2)

print(f"[3/3] Done.")
print(f"  Turns  : {len(turns)}")
print(f"  Parts  : {total_parts}")
print(f"  JSON   : {json_path}")
print(f"  HTML   : {html_path}")

validate_script = Path(__file__).resolve().parent.parent / "subskills" / "validate-db" / "scripts" / "validate_html.py"
if RUN_VALIDATE:
    if validate_script.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("validate_html", validate_script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        validate_json = os.path.join(OUTPUT_DIR, "validate_report.json")
        validate_md = os.path.join(OUTPUT_DIR, "validate_report.md")
        mod.run(html_path, json_out=validate_json, md_out=validate_md)
    else:
        print(f"  [warn] validate-db subskill not found at {validate_script}", file=sys.stderr)
