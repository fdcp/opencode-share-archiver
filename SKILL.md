---
name: opencode-share-archiver
description: Archive any opncd.ai/share/<ID> conversation into a structured JSON file and a self-contained dark-theme HTML page for offline viewing. Triggered when a user provides an opncd.ai share URL and asks to download, archive, or convert the shared conversation.
license: MIT
compatibility: opencode
---

# OpenCode Share Archiver

## Skill Responsibilities

Convert a live `opncd.ai/share/<ID>` shared conversation (SPA, JS-rendered) into:
1. `conversation_final.json` — structured JSON with all turns and parts
2. `chat.html` — self-contained offline-viewable HTML with dark theme, TOC, search, collapsible sections

## Trigger Phrases

- "Archive / download / save this share link: https://opncd.ai/share/..."
- "Convert opncd.ai/share/... to HTML"
- "Make a local copy of this OpenCode session"
- Any URL matching `opncd.ai/share/<ID>`

## Prerequisites

```bash
# Python packages
pip install playwright

# Playwright browser (Chromium headless shell)
python -m playwright install chromium

# CJK font support (for Chinese content)
apt-get install -y fonts-noto-cjk
```

## Execution Steps

### Step 1: Scrape the share page

```bash
python3 ~/.config/opencode/skills/opencode-share-archiver/scripts/run.py \
    https://opncd.ai/share/<ID> \
    /path/to/output_dir
```

This single script performs both scraping and HTML generation, producing:
- `<output_dir>/conversation_final.json`
- `<output_dir>/chat.html`
- `<output_dir>/conversation.json` (copy of JSON)

### Step 2: Optional verification

Run the visual-verify subskill only when you explicitly want to verify output quality:

```bash
python3 ~/.config/opencode/skills/opencode-share-archiver/subskills/visual-verify/scripts/verify.py \
  --new  <output_dir>/chat.html \
  --old  ~/.config/opencode/skills/opencode-share-archiver/subskills/visual-verify/assets/baseline/chat.html \
  --outdir <output_dir>/compare \
  --new-dom-map <output_dir>/dom_map.json \
  --baseline-dom-map ~/.config/opencode/skills/opencode-share-archiver/subskills/visual-verify/assets/baseline/dom_map.json
```

Or run the combined helper with verification enabled:

```bash
python3 ~/.config/opencode/skills/opencode-share-archiver/scripts/orchestrate_verify.py \
  https://opncd.ai/share/<ID> \
  /path/to/output_dir \
  --verify
```

The subskill:
1. Renders both HTMLs in headless Chromium
2. Extracts structured DOM fields (`h1`, `meta`, `stats`, `shellLabel`, `calledLabels`, `fileTools`, etc.)
3. Screenshots key regions (header, toc, turn1_user, shell_tool, file_tool, reasoning, text_part)
4. Runs automatic PASS/FAIL checks on DOM fields
  5. Produces `<output_dir>/compare/compare_report.json` and a Markdown summary table
    from the extracted DOM fields and run output; this table is generated automatically,
    not manually summarized
 6. Runs visual checks per region only as a separate step when a visual tool/agent is available
    (`look_at` or equivalent), then injects those summaries back into the report
 7. Diffs `dom_map.json` against baseline to detect structural changes in the share page

When baseline HTML is available, the visual subagent compares the new and old
screenshots for the same region. It should receive the cropped region name and
the expected behavior, then return a `检测结果分析表` plus a final verdict.

Exit code 0 = all checks passed. Exit code 1 = one or more FAILs.

After a confirmed-good run, update the baseline explicitly:
```bash
  --update-baseline
```

For strict pixel-level regression testing (optional):
```bash
  --pixel-diff --pixel-threshold 0.05
```

See `subskills/visual-verify/SKILL.md` for full documentation.

## Output Standards

### JSON Schema (`conversation_final.json`)

```json
[
  {
    "turnIndex": 0,
    "userMessage": "string — raw user text",
    "meta": "string — model/date metadata line",
    "assistantContent": [
      {
        "type": "reasoning | tool | text | compaction | session-changes",
        "html": "string — cleaned inner HTML (for reasoning/text/session-changes)",
        "name": "string — tool display name (for tool type)",
        "toolType": "string — raw tool type (for tool type)",
        "outputText": "string — raw CLI output text (for tool type)",
        "label": "string — compaction label (for compaction type)"
      }
    ]
  }
]
```

### HTML Standards

- Self-contained single file, no external CDN dependencies
- Dark theme with CSS variables (see references/html-style-guide.md)
- Table of contents (2-column `<ol>`) with anchor links
- Stats bar: turn count, part count
- Search box: real-time `.turn` visibility filtering
- Per-turn: `#N` number, User (green), Assistant (blue)
- Thinking parts: purple label, collapsible, left purple border
- Tool parts: green label, collapsible, CLI output with syntax coloring
  - `$ cmd` lines → cyan
  - `+line` → green (diff added)
  - `-line` → red (diff removed)
  - normal → muted
- Text parts: rendered HTML with full markdown styles
- Compaction: horizontal divider line with label
- Session Changes: orange label, collapsible, monospace content

## Key Technical Notes

- The share page is a SPA (SolidJS). Must use Playwright with `wait_until="networkidle"`.
- Collapsible items (`[data-component="collapsible"][data-closed=""]`) must be clicked open in two passes with scroll in between to trigger lazy loading.
- Tool output is in `pre[data-slot="bash-pre"]` inside `[data-slot="collapsible-content"]`.
- See `references/dom-selectors.md` for full selector map.
