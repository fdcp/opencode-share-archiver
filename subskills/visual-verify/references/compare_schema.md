# compare_report.json Schema

## Top-level structure

```json
{
  "metadata": { ... },
  "summary":  { ... },
  "checks":   [ ... ],
  "visual_specs": [ ... ],
  "dom_diff": { ... },
  "images":   { ... },
  "raw":      { ... }
}
```

---

## metadata

| Field | Type | Description |
|-------|------|-------------|
| new_html | string | Absolute path to new chat.html |
| old_html | string \| null | Absolute path to old/baseline chat.html |
| timestamp | string | ISO 8601 UTC timestamp of run |
| options | object | CLI options used for this run |

---

## summary

| Field | Type | Description |
|-------|------|-------------|
| passed | bool | true if fail_count == 0 |
| pass_count | int | Number of checks with result="pass" |
| fail_count | int | Number of checks with result="fail" |
| warn_count | int | Number of checks with result="warn" |

---

## checks (array)

Each element:

| Field | Type | Description |
|-------|------|-------------|
| id | string | Unique check identifier (e.g. "header_meta") |
| name | string | Human-readable check name |
| result | enum | "pass" \| "fail" \| "warn" \| "info" |
| new_value | string | Extracted value from new HTML |
| old_value | string | Extracted value from old HTML (or "n/a") |
| explanation | string | Auto-generated explanation of result |

### Check IDs and rules

| id | Name | Rule | Fail condition |
|----|------|------|----------------|
| header_meta | Header Meta | new meta contains `v\d+\.\d+` | pattern not found |
| stats_parts | Stats: parts count | new parts >= old parts | new < old |
| user_separation | User message / meta separation | userText does not contain userMetaEl prefix | prefix found in text |
| shell_label | Shell tool label | no duplicate tokens in label | duplicate token found |
| called_labels | Called tool labels | no "Shell:" prefix, no duplicate tokens | any bad label found |
| file_tool_output | File tool outputText | outputText contains U+202A (path marker) | marker missing |
| reasoning | Thinking/Reasoning block | hasReasoning == true | not found (warn only) |
| text_part_meta | Text part meta spans | textPartMeta == true | not found (warn only) |
| visual_\<region\> | Visual: \<region\> | look_at summary contains expected keywords | keywords absent (info) |
| pixel_\<region\> | Pixel diff: \<region\> | diff fraction <= threshold | exceeds threshold |

---

## visual_specs (array)

Specs for regions that need look_at verification. The calling agent iterates
these and calls look_at on each path, then calls `record_visual_result()`.

| Field | Type | Description |
|-------|------|-------------|
| region | string | Region name (e.g. "header", "reasoning") |
| new_path | string \| null | Path to new screenshot |
| old_path | string \| null | Path to old screenshot |
| goal | string | What to look for / verify |

### Regions

| region | goal |
|--------|------|
| header | 页面顶部 header meta + 统计条 |
| toc | 目录区域 |
| turn1_user | 用户消息区（turn 0）|
| shell_tool | 第一个 Shell 工具 |
| file_tool | 第一个文件工具 |
| reasoning | Thinking/Reasoning 区（紫色边框、可折叠）|
| text_part | Text 区（markdown 渲染）|

---

## dom_diff

| Field | Type | Description |
|-------|------|-------------|
| added | string[] | data-slot/data-component keys in new but not baseline |
| removed | string[] | keys in baseline but not in new |

---

## images

```json
{
  "new": { "header": "/path/new_header.png", "toc": null, ... },
  "old": { "header": "/path/old_header.png", ... }
}
```

---

## raw

```json
{
  "new_fields": { "h1": "...", "meta": "...", "stats": [...], ... },
  "old_fields": { ... } | null
}
```

### Extracted DOM fields

| Field | Description |
|-------|-------------|
| h1 | Page title (`<h1>` text) |
| meta | `.page-header .meta` text |
| stats | Array of `.stat` texts (e.g. `["42turns", "575parts"]`) |
| userRole | Turn-0 user role label |
| userMetaEl | Turn-0 user meta (agent · model · time) |
| userText | Turn-0 user message text (first 80 chars) |
| shellLabel | First `.tool-part` with label starting "Shell:" |
| calledLabels | First 3 `.tool-part` labels matching called tool patterns |
| fileTools | First 3 file tool entries: `{label, output}` |
| hasReasoning | bool — any `.reasoning-part` present |
| reasoningCollapsible | bool — reasoning has details/collapsible element |
| textPartMeta | bool — any `.text-part-meta` span present |
