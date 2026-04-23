# Output Format Specification

## conversation_final.json

Top-level: JSON array of turn objects.

```json
[
  {
    "turnIndex": 0,
    "userMessage": "Raw user text (no HTML)",
    "meta": "Model/date metadata line from page",
    "assistantContent": [ ... ]
  }
]
```

## assistantContent part types

### reasoning

```json
{
  "type": "reasoning",
  "html": "<p>cleaned inner HTML of reasoning markdown</p>"
}
```

### tool

```json
{
  "type": "tool",
  "name": "Shell: ls -la /workspace  (combined title + submessage)",
  "toolType": "Shell  (from title element only)",
  "outputText": "raw CLI output text (newline-separated)"
}
```

### text

```json
{
  "type": "text",
  "html": "<p>cleaned inner HTML of markdown text</p>"
}
```

### compaction

```json
{
  "type": "compaction",
  "label": "Conversation compacted. Context window refreshed."
}
```

### session-changes

```json
{
  "type": "session-changes",
  "html": "<cleaned HTML of file change summary>"
}
```

## File outputs

| File | Description |
|------|-------------|
| `conversation_final.json` | Primary structured data |
| `conversation.json` | Copy of primary JSON (for convenience) |
| `chat.html` | Self-contained HTML viewer |

## Verification checklist

- Turn count should match visible turns on share page
- No turns should have empty `userMessage` (empty turns indicate extraction gap)
- Tool parts with actual output should have non-empty `outputText`
- JSON file size for a 42-turn session with ~400 tool calls: ~700-900 KB
- HTML file size for same: ~700-800 KB
