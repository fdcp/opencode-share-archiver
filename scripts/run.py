#!/usr/bin/env python3
"""
OpenCode Share Archiver - run.py
================================
Usage:
    python3 run.py <share_url> <output_dir>

    share_url   - e.g. https://opncd.ai/share/ErCg0NRB
    output_dir  - directory to write output files

Outputs:
    <output_dir>/conversation_final.json   - structured data
    <output_dir>/chat.html                 - self-contained HTML viewer
    <output_dir>/conversation.json         - JSON copy

Requirements:
    pip install playwright
    python -m playwright install chromium
    apt-get install -y fonts-noto-cjk  (for CJK font support)
"""
import sys
import os
import json
import re
import html as html_module
import shutil
import time

# ── CLI args ──────────────────────────────────────────────────────────────────
if len(sys.argv) < 3:
    print("Usage: python3 run.py <share_url> <output_dir>", file=sys.stderr)
    sys.exit(1)

SHARE_URL = sys.argv[1]
_OUTPUT_ROOT = sys.argv[2]

def _extract_share_id(url: str) -> str:
    m = re.search(r'/share/([^/?#]+)', url)
    return m.group(1) if m else re.sub(r'[^\w-]', '_', url)[-32:]

_SHARE_ID = _extract_share_id(SHARE_URL)
OUTPUT_DIR = os.path.join(_OUTPUT_ROOT, f"{_SHARE_ID}_url")
os.makedirs(OUTPUT_DIR, exist_ok=True)
print(f"[run] share_id={_SHARE_ID}  output={OUTPUT_DIR}")

# ── Helper functions ──────────────────────────────────────────────────────────

def esc(text):
    return html_module.escape(str(text))

def clean_tool_name(name):
    name = name.replace("ShellShell", "Shell")
    name = re.sub(r'Called\s+`([^`]+)`\s*', r'\1 ', name)
    name = re.sub(r'(Shell|call_omo_agent|background_output)\1+', r'\1', name)
    return name.strip()

def skip_empty_tool(tool_type, output_text):
    if output_text:
        return False
    return tool_type.startswith("Called `")

def process_html(h):
    if not h:
        return ""
    meta_match = re.search(r'data-slot="text-part-meta"[^>]*>([^<]+)<', h)
    meta_text = meta_match.group(1) if meta_match else ''
    h = re.sub(r'<div\s[^>]*text-part-copy-wrapper[^>]*>.*', '', h, flags=re.DOTALL)
    h = re.sub(r'<button[^>]*>.*?</button>', '', h, flags=re.DOTALL)
    h = re.sub(r'<svg[^>]*>.*?</svg>', '', h, flags=re.DOTALL)
    h = re.sub(r'<span\s+data-slot="text-shimmer[^"]*"[^>]*>[^<]*</span>', '', h)
    h = re.sub(r'<span\s+data-component="text-shimmer"[^>]*>', '<span>', h)
    h = re.sub(r'\s+style="[^"]*text-shimmer[^"]*"', '', h)
    h = re.sub(r'\s+data-slot="[^"]*"', '', h)
    h = re.sub(r'\s+data-component="[^"]*"', '', h)
    h = re.sub(r'\s+data-closed=""', '', h)
    h = re.sub(r'\s+data-icon="[^"]*"', '', h)
    h = re.sub(r'\s+data-size="[^"]*"', '', h)
    h = re.sub(r'\s+data-variant="[^"]*"', '', h)
    h = re.sub(r'\s+data-active="[^"]*"', '', h)
    h = re.sub(r'\s+aria-label="[^"]*"', '', h)
    h = re.sub(r'\s+aria-hidden="[^"]*"', '', h)
    h = re.sub(r'\s+data-run="[^"]*"', '', h)
    h = re.sub(r'\s+data-message="[^"]*"', '', h)
    h = re.sub(r'\s+data-hk="[^"]*"', '', h)
    h = re.sub(r'\s+id="collapsible[^"]*"', '', h)
    h = re.sub(r'<!--\$-->|<!--/-->|<!--\$!-->', '', h)
    h = re.sub(r'<div\s*>\s*<div\s*>([\s\S]*?)</div>\s*</div>', r'\1', h)
    h = h.strip()
    if meta_text:
        h += f'\n<span class="text-part-meta">{meta_text}</span>'
    return h

def format_output_text(text):
    """Colorize CLI output lines for HTML rendering."""
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

# ── Phase 1: Playwright scrape ────────────────────────────────────────────────

print(f"[1/3] Scraping {SHARE_URL} ...")

from playwright.sync_api import sync_playwright

def scrape(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-dev-shm-usage", "--disable-gpu"]
        )
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(url, wait_until="networkidle", timeout=60000)
        time.sleep(3)

        def expand_all():
            """Click all closed collapsible items."""
            count = page.evaluate("""() => {
                const items = document.querySelectorAll('[data-component="collapsible"][data-closed=""]');
                items.forEach(el => {
                    const trigger = el.querySelector('[data-slot="collapsible-trigger"]');
                    if (trigger) trigger.click();
                });
                return items.length;
            }""")
            return count

        def scroll_full():
            """Scroll page fully to trigger lazy loading."""
            page.evaluate("""async () => {
                await new Promise(resolve => {
                    let total = 0;
                    const step = () => {
                        window.scrollBy(0, 1000);
                        total += 1000;
                        if (total < document.body.scrollHeight) {
                            setTimeout(step, 80);
                        } else {
                            window.scrollTo(0, 0);
                            resolve();
                        }
                    };
                    step();
                });
            }""")
            time.sleep(2)

        # Two-pass expand: first pass + scroll for lazy loading + second pass
        n1 = expand_all()
        print(f"  Pass 1: expanded {n1} collapsibles")
        scroll_full()
        n2 = expand_all()
        print(f"  Pass 2: expanded {n2} collapsibles")
        time.sleep(1)

        # Extract page-level header metadata (version, model, date)
        page_meta = page.evaluate("""() => {
            const allEls = Array.from(document.querySelectorAll('*'));
            const vEl = allEls.find(el => el.children.length === 0 && el.innerText && el.innerText.trim().match(/^v\\d+\\.\\d+\\.\\d+$/));
            if (!vEl) return '';
            // Walk up to find the container with version + model + date all together
            let el = vEl.parentElement;
            for (let i = 0; i < 5 && el; i++) {
                const t = el.innerText?.trim() || '';
                if (t.includes('\\n')) {
                    return t.split('\\n').map(s => s.trim()).filter(Boolean).join(' · ');
                }
                el = el.parentElement;
            }
            return vEl.innerText.trim();
        }""")
        print(f"  Page meta: {page_meta}")

        # Extract all turns
        turns = page.evaluate("""() => {
            const container = document.querySelector('.flex.flex-col.gap-15') ||
                              document.querySelector('[class*="gap-15"]');
            if (!container) return [];

            const turnEls = Array.from(container.children);
            const results = [];

            for (const turnEl of turnEls) {
                // User message text — use dedicated text slot to avoid pulling in meta
                const userEl = turnEl.querySelector('[data-component="user-message"]');
                const userTextEl = userEl ? userEl.querySelector('[data-slot="user-message-text"]') : null;
                const userMsg = userTextEl ? userTextEl.innerText.trim()
                              : (userEl ? userEl.querySelector('span')?.innerText?.trim() || '' : '');

                // Meta line — agent · model · time from dedicated meta-wrap slot
                const metaWrap = userEl ? userEl.querySelector('[data-slot="user-message-meta-wrap"]') : null;
                const meta = metaWrap ? metaWrap.innerText.trim() : '';

                // Assistant parts
                const parts = [];
                const partEls = turnEl.querySelectorAll(
                    '[data-component="reasoning-part"], ' +
                    '[data-component="tool-part-wrapper"], ' +
                    '[data-component="text-part"], ' +
                    '[data-component="compaction-part"], ' +
                    '[data-component="session-changes"]'
                );

                for (const partEl of partEls) {
                    const comp = partEl.getAttribute('data-component');

                    if (comp === 'reasoning-part') {
                        const mdEl = partEl.querySelector('[data-component="markdown"]');
                        parts.push({
                            type: 'reasoning',
                            html: mdEl ? mdEl.innerHTML : ''
                        });

                    } else if (comp === 'tool-part-wrapper') {
                        const titleEl = partEl.querySelector('[data-slot="basic-tool-tool-title"]');
                        const subEl = partEl.querySelector('[data-slot="shell-submessage-value"]');
                        const outputEl = partEl.querySelector('pre[data-slot="bash-pre"]');
                        // toolType from aria-label on the shimmer span to avoid duplicate text
                        const shimmerSpan = titleEl ? titleEl.querySelector('[data-component="text-shimmer"]') : null;

                        // For file tools (Read/Write/Edit), use message-part-title-text shimmer
                        const fileTitleTextEl = partEl.querySelector('[data-slot="message-part-title-text"]');
                        const fileShimmer = fileTitleTextEl ? fileTitleTextEl.querySelector('[data-component="text-shimmer"]') : null;

                        let toolType = '';
                        if (shimmerSpan) {
                            toolType = shimmerSpan.getAttribute('aria-label') || '';
                        } else if (fileShimmer) {
                            toolType = fileShimmer.getAttribute('aria-label') || fileShimmer.querySelector('[data-slot="text-shimmer-char-base"]')?.innerText || '';
                        } else if (titleEl) {
                            toolType = titleEl.innerText.split('\\n')[0].trim();
                        }

                        // name is only the submessage (description), not the title
                        const name = subEl ? subEl.innerText.trim() : '';

                        // Build outputText for file tools from path + filename + diff stats
                        let outputText = outputEl ? outputEl.innerText : '';
                        if (!outputText && !subEl) {
                            // File tool (Read/Write/Edit): construct outputText like \u202a{dir}{filename}+N-M\u202c
                            const filenameEl = partEl.querySelector('[data-slot="message-part-title-filename"]');
                            const dirEl = partEl.querySelector('[data-slot="message-part-directory"]');
                            const addEl = partEl.querySelector('[data-slot="diff-changes-additions"]');
                            const delEl = partEl.querySelector('[data-slot="diff-changes-deletions"]');
                            if (filenameEl) {
                                const filename = filenameEl.innerText.trim();
                                const dir = dirEl ? dirEl.innerText.trim() : '';
                                const adds = addEl ? addEl.innerText.trim() : '';
                                const dels = delEl ? delEl.innerText.trim() : '';
                                const diff = (adds || dels) ? adds + dels : '';
                                outputText = '\u202a' + dir + '\u202c' + filename + (diff ? diff : '');
                            }
                        }

                        parts.push({
                            type: 'tool',
                            name: name,
                            toolType: toolType,
                            outputText: outputText
                        });

                    } else if (comp === 'text-part') {
                        // Use full partEl innerHTML to preserve text-part-meta (agent/model/elapsed)
                        parts.push({
                            type: 'text',
                            html: partEl.innerHTML
                        });

                    } else if (comp === 'compaction-part') {
                        parts.push({
                            type: 'compaction',
                            label: partEl.innerText.trim()
                        });

                    } else if (comp === 'session-changes') {
                        parts.push({
                            type: 'session-changes',
                            html: partEl.innerHTML
                        });
                    }
                }

                results.push({
                    userMessage: userMsg,
                    meta: meta,
                    assistantContent: parts
                });
            }
            return results;
        }""")

        # ── DOM auto-detection (方案2): dump all slot/component frequencies ──────
        dom_map = page.evaluate("""() => {
            const slots = {}, comps = {};
            document.querySelectorAll('[data-slot]').forEach(el => {
                const s = el.getAttribute('data-slot');
                slots[s] = (slots[s] || 0) + 1;
            });
            document.querySelectorAll('[data-component]').forEach(el => {
                const c = el.getAttribute('data-component');
                comps[c] = (comps[c] || 0) + 1;
            });
            return { slots, components: comps };
        }""")

        # ── Schema validation (方案4): check each tool-part-wrapper ──────────
        unknown_tools = page.evaluate("""() => {
            const wrappers = document.querySelectorAll('[data-component="tool-part-wrapper"]');
            const unknown = [];
            wrappers.forEach((w, i) => {
                const hasShellSub   = !!w.querySelector('[data-slot="shell-submessage-value"]');
                const hasBashPre    = !!w.querySelector('pre[data-slot="bash-pre"]');
                const hasFile       = !!w.querySelector('[data-slot="message-part-title-filename"]');
                const hasCalled     = !!w.querySelector('[data-slot="basic-tool-tool-subtitle"], [data-slot="basic-tool-tool-arg"]');
                const hasBasicTitle = !!w.querySelector('[data-slot="basic-tool-tool-title"]');
                const hasFileArea   = !!w.querySelector('[data-slot="message-part-title-area"]');
                const isKnown = hasShellSub || hasBashPre || hasFile || hasCalled
                             || (hasBasicTitle && !hasFileArea)
                             || hasFileArea;
                if (!isKnown) {
                    const slots = [...w.querySelectorAll('[data-slot]')]
                        .map(el => el.getAttribute('data-slot'))
                        .filter((v, idx, arr) => arr.indexOf(v) === idx);
                    const titleText = w.querySelector('[data-slot="collapsible-trigger"]')?.innerText?.substring(0, 60) || '';
                    unknown.push({ index: i, slots, titleText });
                }
            });
            return unknown;
        }""")

        if unknown_tools:
            print(f"  ⚠️  WARNING: {len(unknown_tools)} tool-part-wrapper(s) with UNKNOWN structure (may be new tool types):")
            for u in unknown_tools:
                print(f"     tool #{u['index']}: title={u['titleText']!r}")
                print(f"       slots: {u['slots']}")
            print(f"  → Check dom_map.json and update scripts/run.py + references/dom-selectors.md")
        else:
            print(f"  ✓  All tool-part-wrappers match known structures (shell / file / called)")

        browser.close()
        return turns, page_meta, dom_map, unknown_tools

data, page_meta, dom_map, unknown_tools = scrape(SHARE_URL)

# Add turnIndex
for i, t in enumerate(data):
    t['turnIndex'] = i

print(f"  Extracted {len(data)} turns, "
      f"{sum(len(t['assistantContent']) for t in data)} parts total")

dom_map_path = os.path.join(OUTPUT_DIR, "dom_map.json")
with open(dom_map_path, "w", encoding="utf-8") as f:
    json.dump(dom_map, f, ensure_ascii=False, indent=2)

# Save JSON
json_path = os.path.join(OUTPUT_DIR, "conversation_final.json")
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"  Saved {json_path}")

# ── Phase 2: Generate HTML ────────────────────────────────────────────────────

print(f"[2/3] Generating chat.html ...")

turns_html = []
toc_items = []

for i, turn in enumerate(data):
    user_msg = turn.get("userMessage", "")
    meta = turn.get("meta", "")
    assistant_parts = turn.get("assistantContent", [])

    # Sanitize both link text and title attribute: replace newlines/tabs with spaces
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
            content = process_html(part.get("html", ""))
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
            name = part.get("name", "")
            tool_type = clean_tool_name(part.get("toolType", "Shell"))
            label = f"{tool_type}: {name}" if name else tool_type
            output_text = part.get("outputText", "")
            if skip_empty_tool(part.get("toolType", ""), output_text):
                continue
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
            content = process_html(part.get("html", ""))
            if content:
                assistant_html_parts.append(f'''
            <div class="part text-part">
                <div class="part-content text-content">{content}</div>
            </div>''')

        elif ptype == "compaction":
            label = esc(part.get("label", "Compacted"))
            assistant_html_parts.append(f'''
            <div class="compaction-divider">
                <span class="compaction-line"></span>
                <span class="compaction-label">{label}</span>
                <span class="compaction-line"></span>
            </div>''')

        elif ptype == "session-changes":
            sch = process_html(part.get("html", ""))
            assistant_html_parts.append(f'''
            <div class="part changes-part">
                <div class="part-header changes-header" onclick="this.parentElement.classList.toggle('collapsed')">
                    <span class="part-icon">&#x1F4DD;</span>
                    <span class="part-label">Session Changes</span>
                    <span class="toggle-hint">click to toggle</span>
                </div>
                <div class="part-content changes-content">{sch}</div>
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
total_parts = sum(len(t.get('assistantContent', [])) for t in data)
share_id = SHARE_URL.rstrip('/').split('/')[-1]

page = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenCode Session - {esc(share_id)}</title>
<style>
:root {{
    --bg: #0f0e0e; --bg2: #181616; --bg3: #201d1d; --bg4: #2a2626;
    --text: #e8e4e0; --text2: #b0a8a0; --text3: #807870; --text4: #605850;
    --border: #2a2525; --border2: #3a3535;
    --user-accent: #4a9a4a; --user-bg: #141e14; --user-border: #1e2e1e;
    --assistant-accent: #6b8afd;
    --reasoning-accent: #8b7afd; --reasoning-bg: #16141e; --reasoning-border: #28203a;
    --tool-accent: #5ba85b; --tool-bg: #141e14; --tool-border: #1e3a1e;
    --changes-accent: #da8a3a; --changes-bg: #1e1a14; --changes-border: #3a2e1e;
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
.changes-header .part-label {{ color:var(--changes-accent); }}
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
.text-part-meta {{ font-size:11px; color:var(--text4); display:block; margin-top:6px; }}
.text-12-regular.text-text-weak {{ font-size:11px; color:var(--text4); display:block; margin-top:6px; cursor:default; }}
.cursor-default {{ cursor:default; }}
.compaction-divider {{ display:flex; align-items:center; gap:12px; margin:12px 0; color:var(--text4); font-size:11px; text-transform:uppercase; letter-spacing:0.5px; }}
.compaction-line {{ flex:1; height:1px; background:var(--border); }}
.changes-part {{ border:1px solid var(--changes-border); border-radius:6px; padding:8px 10px; background:var(--changes-bg); }}
.changes-content {{ font-size:13px; overflow-x:auto; font-family:'SF Mono','Fira Code',monospace; }}
.part.collapsed .part-content {{ display:none; }}
.search-box {{ margin-bottom:20px; }}
.search-box input {{ width:100%; padding:8px 12px; background:var(--bg2); border:1px solid var(--border); border-radius:6px; color:var(--text); font-size:13px; outline:none; }}
.search-box input:focus {{ border-color:var(--assistant-accent); }}
.search-box input::placeholder {{ color:var(--text4); }}
.stats {{ display:flex; gap:12px; margin-bottom:20px; flex-wrap:wrap; }}
.stat {{ background:var(--bg2); border:1px solid var(--border); border-radius:6px; padding:6px 12px; font-size:13px; }}
.stat-value {{ font-weight:700; color:var(--text); }}
.stat-label {{ color:var(--text3); margin-left:4px; }}
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
    <h1>OpenCode Session {esc(share_id)}</h1>
    <div class="meta">{esc(page_meta) if page_meta else esc(SHARE_URL)}</div>
</div>
<div class="stats">
    <div class="stat"><span class="stat-value">{len(data)}</span><span class="stat-label">turns</span></div>
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

# JSON copy
json_copy = os.path.join(OUTPUT_DIR, "conversation.json")
shutil.copy2(json_path, json_copy)

# ── Phase 3: Summary ──────────────────────────────────────────────────────────

print(f"[3/3] Done.")
print(f"  Turns     : {len(data)}")
print(f"  Parts     : {total_parts}")
print(f"  JSON      : {json_path}")
print(f"  HTML      : {html_path}")
print(f"  DOM map   : {dom_map_path}")
if unknown_tools:
    print(f"  ⚠️  Unknown tool structures: {len(unknown_tools)} (see warnings above)")
