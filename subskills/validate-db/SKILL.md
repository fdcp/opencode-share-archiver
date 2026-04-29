---
name: validate-db
description: Validate a locally-generated chat.html (from run_db.py) with three layers — static HTML parser, Playwright DOM checks, and gpt-4o visual checks. Triggered when the user explicitly asks to validate or verify a chat.html produced by the local DB archiver.
---

# validate-db

Standalone validator for a single `chat.html` produced by `run_db.py`.
Does **not** require a baseline or a second HTML — this is not a regression comparator.

## Three Validation Layers

| Layer | Tool | Checks |
|---|---|---|
| Static | Python `html.parser` | Structure, turns, TOC links, duplicates, search box, user messages (9 checks) |
| DOM | Playwright + `compare.py` | Header meta, parts count, user separation, shell label, called labels, file tool markers, reasoning block, TOC integrity (14 checks) |
| Visual | Playwright screenshots → `look_at.py` (gpt-4o) | toc, turn0_user, shell_tool, text_part, reasoning regions (5 checks) |

## Usage

```bash
python3 ~/.config/opencode/skills/opencode-share-archiver/subskills/validate-db/scripts/validate_html.py \
  /path/to/chat.html \
  [--json-out /path/to/validate_report.json] \
  [--md-out   /path/to/validate_report.md] \
  [--skip-dom] \
  [--skip-visual]
```

Exits 0 if no `fail` results, exits 1 if any `fail`.

## Output

- `validate_report.json` — full check list with id/name/result/detail per check
- `validate_report.md`  — markdown table summary
- `validate_screenshots/` — per-region PNG screenshots (created alongside `--json-out` or next to `chat.html`)

## Result Values

| Value | Meaning |
|---|---|
| `pass` | Check passed |
| `fail` | Check failed — needs attention |
| `warn` | Expected absence or unverifiable (not a failure) |
| `info` | Informational — no JS interaction possible in screenshot |

## Dependencies

Same as the parent skill: `playwright`, Chromium, `look_at.py` (uses `github-copilot/gpt-4o`).

```bash
pip install playwright
python -m playwright install chromium
```

## Integration with run_db.py

`run_db.py` does **not** auto-trigger this validator. Call it explicitly after archiving:

```bash
python3 ~/.config/opencode/skills/opencode-share-archiver/scripts/run_db.py \
  <session_id> <output_dir>

python3 ~/.config/opencode/skills/opencode-share-archiver/subskills/validate-db/scripts/validate_html.py \
  <output_dir>/chat.html \
  --json-out <output_dir>/validate_report.json \
  --md-out   <output_dir>/validate_report.md
```
