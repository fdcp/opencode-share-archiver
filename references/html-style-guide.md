# HTML Style Guide

## Design principles

- Self-contained single file (no external CDN, no external fonts)
- Dark theme by default
- CSS variables for all colors (easy theming)
- Mobile-responsive

## Color palette (CSS variables)

```css
--bg: #0f0e0e;          /* page background */
--bg2: #181616;         /* cards, containers */
--bg3: #201d1d;         /* hover states */
--bg4: #2a2626;         /* subtle elements */
--text: #e8e4e0;        /* primary text */
--text2: #b0a8a0;       /* secondary text */
--text3: #807870;       /* muted labels */
--text4: #605850;       /* very muted, hints */
--border: #2a2525;      /* default borders */
--border2: #3a3535;     /* stronger borders */

/* User messages */
--user-accent: #4a9a4a;
--user-bg: #141e14;
--user-border: #1e2e1e;

/* Assistant */
--assistant-accent: #6b8afd;

/* Thinking/Reasoning */
--reasoning-accent: #8b7afd;
--reasoning-bg: #16141e;
--reasoning-border: #28203a;

/* Tool calls */
--tool-accent: #5ba85b;
--tool-bg: #141e14;
--tool-border: #1e3a1e;

/* Session changes */
--changes-accent: #da8a3a;
--changes-bg: #1e1a14;
--changes-border: #3a2e1e;

/* CLI output coloring */
--added: #4a9a4a;       /* diff +lines */
--removed: #da4a4a;     /* diff -lines */
--cmd: #7adfb8;         /* $ command lines */
--prompt: #5ba85b;      /* $ prompt symbol */
```

## Layout

- Max width: 900px, centered
- Turn number: absolute positioned, left side, `#N` format
- Turn padding-left: 40px (space for number)

## Part rendering rules

| Part type | Visual style |
|-----------|-------------|
| reasoning | Left purple border (3px), purple label, collapsible |
| tool | Green border box, collapsible, CLI output max-height 500px with scroll |
| text | Plain rendered HTML with full markdown styles |
| compaction | Centered horizontal divider with text label |
| session-changes | Orange border box, monospace font, collapsible |

## Collapsible behavior

- `.part-header` has `onclick="this.parentElement.classList.toggle('collapsed')"`
- `.part.collapsed .part-content { display: none; }`

## Search

- `<input>` calls `filterTurns(value)` on `oninput`
- Hides `.turn` elements whose `textContent` doesn't include query (case-insensitive)

## Font stack

```
-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans SC', Roboto, sans-serif
```
'Noto Sans SC' covers Chinese characters if system font missing.
Monospace: `'SF Mono', 'Fira Code', monospace`
