# opencode-share-archiver

Development branch for the OpenCode share archiver skill.

## What this repo contains

- `scripts/run.py`: scrape a shared session and generate `conversation_final.json` + `chat.html`
- `scripts/orchestrate_verify.py`: run the full verify pipeline
- `subskills/visual-verify/`: DOM, screenshot, and visual regression checks
- `VERSION`: release version for this development branch

## Development flow

1. Edit in this repo.
2. Update `VERSION` when preparing a release.
3. Use `skill-release-manager` to package, publish, and switch the installed skill.

## Notes

- This repository is the source of truth for development.
- The installed global skill points to a released snapshot.
