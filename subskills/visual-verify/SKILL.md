---
name: visual-verify
description: >
  Subskill of opencode-share-archiver. Renders new and old chat.html in headless
  Chromium, extracts structured DOM fields, takes screenshots of key regions,
  and produces a structured compare_report.json with automatic PASS/FAIL per check.
  Visual checks use look_at (AI image summary) by default; pixelmatch is optional.
  Called by the main skill after each run to verify output quality has not regressed.
---

# visual-verify

Subskill of `opencode-share-archiver`. Provides automated HTML rendering comparison.

## Invocation (by main skill)

```bash
python ~/.config/opencode/skills/opencode-share-archiver/subskills/visual-verify/scripts/verify.py \
  --new  /workspace/opencode_skill_test/chat.html \
  --old  ~/.config/opencode/skills/opencode-share-archiver/subskills/visual-verify/assets/baseline/chat.html \
  --outdir /workspace/opencode_skill_test/compare \
  --new-dom-map /workspace/opencode_skill_test/dom_map.json \
  --baseline-dom-map ~/.config/opencode/skills/opencode-share-archiver/subskills/visual-verify/assets/baseline/dom_map.json
```

To enable pixelmatch (optional, strict visual regression):
```bash
  --pixel-diff --pixel-threshold 0.05
```

To update baseline after a confirmed-good run:
```bash
  --update-baseline
```

## Outputs

| File | Description |
|------|-------------|
| `<outdir>/compare_report.json` | Structured PASS/FAIL report |
| `<outdir>/screenshots/new_<region>.png` | New HTML screenshots per region |
| `<outdir>/screenshots/old_<region>.png` | Old HTML screenshots per region |
| `<outdir>/screenshots/diff_<region>.png` | Pixel diff images (if --pixel-diff) |

## Checks performed

| Check | Rule | Result type |
|-------|------|-------------|
| Header Meta | new meta contains `v\d+\.\d+` | PASS/FAIL |
| Stats: parts count | new parts >= old parts | PASS/WARN |
| User separation | userText does not contain userMeta | PASS/FAIL |
| Shell tool label | no duplicate tokens | PASS/FAIL |
| Called tool labels | no Shell: prefix, no duplicates | PASS/FAIL |
| File tool outputText | contains U+202A path marker | PASS/FAIL |
| Reasoning block | present and collapsible | PASS/WARN |
| Text part meta | text-part-meta spans present | PASS/WARN |
| Visual: \<region\> | look_at keyword check per region | PASS/INFO |
| Pixel diff: \<region\> | diff fraction <= threshold | PASS/FAIL (optional) |
| DOM map diff | added/removed slot/component keys | INFO/WARN |

## Visual check strategy

The report has two layers:
- The `HTML 渲染层` table is generated automatically from Playwright screenshots,
  DOM extraction, and Python-side checks.
- Visual conclusions are a separate step. When a visual tool/agent is available,
  the caller iterates `visual_specs`, inspects each screenshot, and injects the
  summaries back into the report.

When a baseline exists, the visual subagent compares the new and old screenshots
for the same region. The caller should provide the cropped region name and the
expected behavior, and the subagent should return a `检测结果分析表` plus a
final verdict.

Default visual tool: `look_at` (AI image summary) or an equivalent visual agent.
The caller should check for expected keywords (e.g., "purple border" for
reasoning, "path" for file tools).

Optional: `--pixel-diff` adds pixelmatch comparison. Requires consistent
Chromium binary and fonts across runs to avoid noise. Default threshold: 0.05 (5%).

## Baseline management

Baseline files live in `assets/baseline/`:
- `chat.html` — reference HTML
- `dom_map.json` — reference DOM slot map
- `screenshots/` — reference screenshots

Run `--update-baseline` explicitly after a confirmed-good run to refresh.

## Exit codes

- `0` — all checks passed (fail_count == 0)
- `1` — one or more FAIL checks
