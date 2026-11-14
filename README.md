# VOTHUB

A small always-on-top listening post for open-source issues worth picking up.

- **Cloud sweep** (`scanner/`, `.github/workflows/scan.yml`): a GitHub Action runs at 06:15 and 18:15 IST. It finds fast-rising repos in two lanes (AI/ML/agents/infra and bleeding-edge systems work in Rust, C++, Zig), drops repos that do not merge outside PRs, keeps open issues that are unassigned, have no linked PR and no "I'll take this" comment, scores and tags them with an ML model, and publishes one gzipped feed to the `data` branch.
- **Desktop tab** (`app/`, `ui/`): a Tauri window covering 1/16 of the screen. It pulls the feed at 07:00 and 19:00, waits an hour if the laptop is busy, and expands to a full console on click.

## One-time setup

1. Create a **public** GitHub repo and push this folder to it.
2. In the repo: Actions tab -> `vothub-scan` -> Run workflow (the first sweep; later ones are on cron).
3. Start `app/target/release/vothub.exe`, click the tab, and enter `owner/name` under STATION.

Optional: add an `ANTHROPIC_API_KEY` repo secret to score with Claude instead of the built-in embedding model. Set the repo variable `VOTHUB_MODEL` to pick the model (default `claude-opus-5-5`; `claude-haiku-5-5` is far cheaper).

## Build

```
cd app
cargo build --release --features custom-protocol
```

## Knobs

| What | Where |
|---|---|
| Repos always scanned | `scanner/seeds.json` |
| Discovery queries, issue window, ranking weights | top of `scanner/scan.py` |
| Scan times | `cron` in `.github/workflows/scan.yml` (UTC) and `SLOT_HOURS` in `app/src/main.rs` |
| Busy thresholds (CPU 60%, RAM 90%, battery 20%) | constants at the top of `app/src/main.rs` |

Local data lives in `%APPDATA%\dev.vothub.app`: `state.json` plus the latest `feed.json.gz`. Nothing older than 4 days is kept, locally or in the cloud cache.
