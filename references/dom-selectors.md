# DOM Selectors — opncd.ai/share/<ID>

Page tech stack: **SolidJS + Tailwind CSS**, fully client-side rendered SPA.
Must use Playwright with `wait_until="networkidle"` + `time.sleep(3)` before extraction.

## Top-level container

```
.flex.flex-col.gap-15
```
Direct children are conversation turns.

## Per-turn elements

| Content | Selector | Notes |
|---------|----------|-------|
| User message text | `[data-slot="user-message-text"]` → `.innerText` | Do NOT use `[data-component="user-message"]` directly — its `.innerText` includes the meta block |
| User meta (agent · model · time) | `[data-slot="user-message-meta-wrap"]` → `.innerText` | Full meta string with NBSP separators |
| Page header (version/model/date) | Find leaf element with text matching `/^v\d+\.\d+\.\d+$/`, then walk up to find parent with `\n` in innerText | Gives `"v1.4.6\nminimax-m2.5-free\n21 Apr 2026, 05:29"` |

## Assistant content parts

All part elements are direct or nested descendants of the turn container.

| Part type | data-component value | Content location |
|-----------|---------------------|-----------------|
| Reasoning/thinking | `reasoning-part` | `[data-component="markdown"]` → `.innerHTML` |
| Tool call wrapper | `tool-part-wrapper` | see below |
| Text/markdown | `text-part` | `[data-component="markdown"]` → `.innerHTML` |
| Compaction marker | `compaction-part` | `.innerText` for label |
| Session file changes | `session-changes` | `.innerHTML` |

## Tool part details

All tool types share the outer wrapper `[data-component="tool-part-wrapper"]`. The inner structure differs by tool type.

### Shell tools (toolType = "Shell")

```
[data-component="tool-part-wrapper"]
  [data-slot="basic-tool-tool-title"]
    [data-component="text-shimmer"][aria-label="Shell"]   → toolType (use aria-label, NOT innerText which duplicates)
  [data-slot="shell-submessage-value"]                    → command description (name field)
  [data-slot="collapsible-content"]
    [data-component="bash-output"]
      pre[data-slot="bash-pre"]                           → raw CLI output text
```

**Important**: `[data-slot="basic-tool-tool-title"]` `.innerText` returns `"Shell\nShell"` due to shimmer animation spans. Use `aria-label` on the inner `[data-component="text-shimmer"]` span instead.

### Called tools (toolType = "Called `xxx`", e.g. call_omo_agent, session_read, etc.)

```
[data-component="tool-part-wrapper"]
  [data-slot="basic-tool-tool-title"]
    [data-component="text-shimmer"][aria-label="Called `xxx`"]  → toolType
  [data-slot="basic-tool-tool-subtitle"]                        → short description
  [data-slot="basic-tool-tool-arg"]                             → one per argument (multiple)
```

No `shell-submessage-value` or `bash-pre`. These tools have no CLI output shown in the UI.

### File tools (toolType = "Write" / "Edit" / "Read")

Identified in the fourth DOM inspection pass. These use a completely different slot structure — no `basic-tool-tool-title`, no `bash-pre`.

```
[data-component="tool-part-wrapper"]
  [data-slot="message-part-title-area"]
    [data-slot="message-part-title"]
      [data-slot="message-part-title-text"]
        [data-component="text-shimmer"][aria-label="Write"]  → toolType
          [data-slot="text-shimmer-char-base"]               → fallback if no aria-label
      [data-slot="message-part-title-filename"]              → filename only (e.g. "run.py")
    [data-slot="message-part-path"]
      [data-slot="message-part-directory"]                   → directory path (e.g. "/workspace/foo/")
  [data-slot="message-part-actions"]
    [data-slot="diff-changes-additions"]                     → e.g. "+29"
    [data-slot="diff-changes-deletions"]                     → e.g. "-32"
```

**outputText reconstruction**: combine as `\u202a{dir}\u202c{filename}+N-M`

Examples:
```
\u202a/\u202csft_ckpt.sh                          (Write, no diff)
\u202a/workspace/foo/\u202cbar.py+29-32            (Edit with diff)
```

**Detection**: a tool-part-wrapper is a file tool if it has `[data-slot="message-part-title-filename"]` but no `[data-slot="shell-submessage-value"]`.

## Collapsible expansion

Items with `[data-component="collapsible"][data-closed=""]` are collapsed.
Trigger: `[data-slot="collapsible-trigger"]` inside the collapsible.

**Must expand in two passes** (with full-page scroll between) to handle lazy loading:
1. Click all closed collapsibles
2. Scroll page top-to-bottom (1000px steps, 80ms delay)
3. Click remaining closed collapsibles

## Text part HTML extraction

Use `[data-component="text-part"]` `.innerHTML` (the **full outer** HTML), not just the inner markdown div.

The full HTML contains:
- `[data-slot="text-part-body"] > [data-component="markdown"]` — the rendered markdown
- `[data-slot="text-part-copy-wrapper"]` — contains copy button (strip this) + `[data-slot="text-part-meta"]` span

In `process_html()`:
1. Extract `data-slot="text-part-meta"` text before stripping
2. Remove copy-wrapper div: `re.sub(r'<div\s[^>]*text-part-copy-wrapper[^>]*>.*', '', h, flags=re.DOTALL)`
3. After cleaning, append meta as `<span class="text-part-meta">...</span>`

Remove these before embedding HTML in output:
- `data-slot`, `data-component`, `data-closed`, `data-icon`, `data-size`
- `data-variant`, `data-active`, `data-run`, `data-message`, `data-hk`
- `aria-label`, `aria-hidden`
- `id="collapsible*"` (causes anchor conflicts)
- `<svg>` elements entirely
- `<button>` elements entirely
- `text-shimmer` spans/styles (loading skeleton artifacts)
