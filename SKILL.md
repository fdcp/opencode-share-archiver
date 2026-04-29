---
name: opencode-share-archiver
description: Archive any opncd.ai/share/<ID> conversation into a structured JSON file and a self-contained dark-theme HTML page for offline viewing. Triggered when a user provides an opncd.ai share URL and asks to download, archive, or convert the shared conversation.
license: MIT
compatibility: opencode
---

# OpenCode Share Archiver

## Skill Responsibilities

Convert a live `opncd.ai/share/<ID>` shared conversation or a **local OpenCode session DB** into:
1. `conversation_final.json` — structured JSON with all turns and parts
2. `chat.html` — self-contained offline-viewable HTML with dark theme, TOC, search, collapsible sections

## Trigger Phrases

- "Archive / download / save this share link: https://opncd.ai/share/..."
- "Convert opncd.ai/share/... to HTML"
- "Make a local copy of this OpenCode session"
- "Archive a local OpenCode session with oc-archive"
- Any URL matching `opncd.ai/share/<ID>`

## Prerequisites

```bash
pip install playwright
python -m playwright install chromium
apt-get install -y fonts-noto-cjk
```

## Execution Steps

### Flow A: Archive from share URL

```bash
python3 ~/.config/opencode/skills/opencode-share-archiver/scripts/run.py \
    https://opncd.ai/share/<ID> \
    /path/to/output_dir
```

Produces:
- `<output_dir>/conversation_final.json`
- `<output_dir>/chat.html`
- `<output_dir>/conversation.json`

### Flow B: Archive from local session DB (preferred)

```bash
python3 ~/.config/opencode/skills/opencode-share-archiver/scripts/run_db.py \
  <session_id> \
  <output_dir>
```

Or via the wrapper:

```bash
oc-archive <session_id> <output_dir>
```

Which internally calls `oc_archive.py` → `run_db.py`. Reads the local OpenCode SQLite DB directly — no share URL or network access required.

Produces the same artifacts as Flow A under `<output_dir>/`.

Optional flag `--validate` triggers the `validate-db` subskill immediately after archiving:

```bash
python3 run_db.py <session_id> <output_dir> --validate
```

### Step 2: Validate output (optional, validate-db subskill)

Run only when you want to explicitly verify the generated `chat.html`:

```bash
python3 ~/.config/opencode/skills/opencode-share-archiver/subskills/validate-db/scripts/validate_html.py \
  <output_dir>/chat.html \
  --json-out <output_dir>/validate_report.json \
  --md-out   <output_dir>/validate_report.md
```

Three validation layers:
1. **Static** (9 checks) — pure Python `html.parser`: structure, turns, TOC links, duplicates, search box
2. **DOM** (14 checks) — Playwright + `compare.py`: header meta, shell label, file tool markers, reasoning block, etc.
3. **Visual** (5 regions) — Playwright screenshots → `look_at.py` (gpt-4o): toc, user message, tool block, text part, reasoning

Exits 0 if no `fail` results. Outputs `validate_report.json` + `validate_report.md` + `validate_screenshots/`.

Use `--skip-dom` or `--skip-visual` to run only a subset of layers.

See `subskills/validate-db/SKILL.md` for full documentation.

### Step 3: Visual regression verify (optional, visual-verify subskill)

Use only when comparing a new HTML against a known-good baseline (regression testing):

```bash
python3 ~/.config/opencode/skills/opencode-share-archiver/subskills/visual-verify/scripts/verify.py \
  --new  <output_dir>/chat.html \
  --old  ~/.config/opencode/skills/opencode-share-archiver/subskills/visual-verify/assets/baseline/chat.html \
  --outdir <output_dir>/compare \
  --new-dom-map <output_dir>/dom_map.json \
  --baseline-dom-map ~/.config/opencode/skills/opencode-share-archiver/subskills/visual-verify/assets/baseline/dom_map.json
```

Or with the orchestrator (Flow A only):

```bash
python3 ~/.config/opencode/skills/opencode-share-archiver/scripts/orchestrate_verify.py \
  https://opncd.ai/share/<ID> \
  /path/to/output_dir \
  --verify
```

See `subskills/visual-verify/SKILL.md` for full documentation.

## Subskills

| Subskill | Purpose | When to use |
|---|---|---|
| `validate-db` | Validate a single `chat.html` (3 layers: static + DOM + visual) | After `run_db.py`, on explicit request |
| `visual-verify` | Regression compare new vs baseline HTML | After `run.py` (share URL flow), on explicit request |

## Entry Points and Validation Triggers

| Scenario | Entry point | Validation triggered |
|---|---|---|
| Share URL archive (no verify) | `run.py <url> <outdir>` | None |
| Share URL archive + regression verify | `orchestrate_verify.py <url> <outdir> --verify` | `--verify` flag → visual-verify subskill |
| Share URL archive + single validation | `validate_html.py <chat.html>` | Manual call after `run.py` |
| Local DB archive (no verify) | `oc_archive.py <session_id> <outdir>` or `run_db.py <session_id> <outdir>` | None |
| Local DB archive + validation | `run_db.py <session_id> <outdir> --validate` | `--validate` flag → validate-db subskill |
| Any chat.html standalone validation | `validate_html.py <chat.html>` | Manual call at any time |

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
- `run_db.py` reads the OpenCode SQLite DB directly via `opencode db path`. A new turn starts on each user message; consecutive assistant parts are merged into the same turn.
- See `references/dom-selectors.md` for full selector map.
