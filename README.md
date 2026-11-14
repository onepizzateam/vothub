<div align="center">

```
██╗   ██╗ ██████╗ ████████╗██╗  ██╗██╗   ██╗██████╗
██║   ██║██╔═══██╗╚══██╔══╝██║  ██║██║   ██║██╔══██╗
██║   ██║██║   ██║   ██║   ███████║██║   ██║██████╔╝
╚██╗ ██╔╝██║   ██║   ██║   ██╔══██║██║   ██║██╔══██╗
 ╚████╔╝ ╚██████╔╝   ██║   ██║  ██║╚██████╔╝██████╔╝
  ╚═══╝   ╚═════╝    ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═════╝
      D E E P   R E P O   L I S T E N I N G   P O S T
```

![status](https://img.shields.io/badge/STATUS-LISTENING-72f5a2?style=flat-square&labelColor=040806)
![sweeps](https://img.shields.io/badge/SWEEPS-07%3A00_%2F_19%3A00-ffb84a?style=flat-square&labelColor=040806)
![scan](https://img.shields.io/github/actions/workflow/status/onepizzateam/vothub/scan.yml?style=flat-square&label=CLOUD%20SCAN&labelColor=040806&color=72f5a2)
![shell](https://img.shields.io/badge/SHELL-TAURI_%2B_RUST-72f5a2?style=flat-square&labelColor=040806)

**A small green terminal in the corner of your screen that listens to GitHub<br>and tells you which open issues are actually worth your time.**

</div>

```
> STATION LOG // FIRST CONTACT
> 64 trending repos located. 18 rejected: closed to outsiders.
> 1133 unclaimed signals received. 240 kept. docs sunk to the bottom.
> strongest signal: vllm-project/vllm // score 96
> _
```

## `>` WHAT IT IS

Twice a day a cloud job sweeps GitHub for repositories that are gaining stars fast, in two lanes:

| LANE | LISTENING FOR |
|---|---|
| `ai-infra` | agents, inference serving, model infra: crewAI, pydantic-ai, vLLM, SGLang, Ray, Mooncake, TensorRT and whatever is breaking out this week |
| `systems` | bleeding-edge Rust, C++ and Zig, plus research implementations: databases, compilers, runtimes, GPU kernels |

It throws away every repo that does not merge outside contributors, keeps only issues nobody has claimed, scores them for how much real engineering they need, and beams a 20 KB feed down to a tab that takes one sixteenth of your screen.

```
┌──────────────────────────────────────────────────────────┐
│ ● VOTHUB   LISTENING                            [ HALT ] │
├──────────────────────────────────────────────────────────┤
│                                                          │
│      █            █                   █                  │
│     ▟█▙     ▟▙   ▟█▙        ▟▙       ▟█▙      ▟▙         │
│ ▁▂▁▟███▙▁▂▁▟██▙▁▟███▙▁▁▂▁▁▁▟██▙▁▂▁▁▁▟███▙▁▁▂▁▟██▙▁▂▁▁▂▁  │
├──────────────────────────────────────────────────────────┤
│     240           240            96            74        │
│   SIGNALS         NEW           TOP          REPOS       │
├──────────────────────────────────────────────────────────┤
│ > vllm-project/vllm: [RFC]: Kernel-owned LoRA fusion...  │
│ NEXT SCAN 04:21:07                         SIGNAL LOCKED │
└──────────────────────────────────────────────────────────┘
```

Click the tab and it opens into the full console: the ranked list, tags for language, sector, kind and effort, filters, and a log of the last four days of sweeps. Click any signal to open the issue.

## `>` SIGNAL PATH

```
  GITHUB ACTIONS  (06:15 + 18:15 IST)                 YOUR LAPTOP
 ┌───────────────────────────────────────┐          ┌──────────────────────┐
 │ 1 DISCOVER   star velocity, 2 lanes   │          │  07:00 + 19:00       │
 │ 2 GATE       outsiders get merged?    │          │                      │
 │ 3 FILTER     open, unassigned, no PR, │  feed    │  busy?  wait 1 hour  │
 │              nobody said "I'll take"  │ ───────▶ │  calm?  pull 20 KB   │
 │ 4 SCORE      embedding model + cache  │  .gz     │                      │
 │ 5 RANK       substance first,         │          │  mini tab, 1/16 of   │
 │              docs always last         │          │  the screen          │
 └───────────────────────────────────────┘          └──────────────────────┘
        published to the `data` branch                 %APPDATA%, 4 days max
```

| STAGE | RULE |
|---|---|
| **DISCOVER** | GitHub search across ~20 topic and language queries, ranked by stars per day rather than total stars, plus the fixed list in `scanner/seeds.json` |
| **GATE** | repo is dropped if archived, if fewer than 2 outside PRs were merged in 90 days, or if CONTRIBUTING closes the door and outsiders rarely get merged |
| **FILTER** | issue must be open, under 45 days old, unassigned, with no open or merged PR linked and no "I'll take this" in the comments |
| **SCORE** | `bge-small-en-v1.5` embeddings place each issue by kind, sector and substance; blended with body size, reactions, labels, repo velocity and freshness |
| **RANK** | substance first. Anything labelled docs is forced to the bottom. Questions are cut by half |
| **CACHE** | verdicts are keyed by the issue's `updated_at`, so unchanged issues are never scored twice |

No API keys. The model runs on the Actions runner for free. Adding an `ANTHROPIC_API_KEY` repo secret switches scoring to Claude; leave it out and nothing changes.

## `>` STATION CONTROLS

```
┌──────────────────────────────────────────────────────────┐
│ HALT ALL OPERATIONS                                      │
│ For how long?                                            │
│                                                          │
│   [ 1 HOUR ]      [ 4 HOURS ]     [ 12 HOURS ]           │
│   [ UNTIL 7 AM ]  [ UNTIL I RESUME IT ]                  │
├──────────────────────────────────────────────────────────┤
│ ARE YOU SURE?                                            │
│ Everything stops until you press RESUME.                 │
│                                                          │
│   [ YES, HALT ]   [ NO, KEEP LISTENING ]                 │
└──────────────────────────────────────────────────────────┘
```

- **HALT** stops everything on the laptop in one click: no syncing, no system probing, no animation. Pick a duration, confirm, done. **RESUME** is also one click.
- **Busy guard.** Before each sweep the tab checks the machine. CPU over 60%, memory over 90%, or battery under 20% unplugged, and it stands down for an hour.
- **Storage.** One gzipped feed and a small state file. Nothing older than four days survives, locally or in the cloud cache.
- **Footprint.** A 4 MB executable, about 30 MB of RAM for the app itself.

## `>` BRING THE STATION ONLINE

```
1. fork or push this repo (it must be public)
2. Actions tab  ->  vothub-scan  ->  Run workflow      # first sweep only
3. build the tab:
       cd app
       cargo build --release --features custom-protocol
4. run app/target/release/vothub.exe
5. click the tab  ->  STATION  ->  FEED REPO  ->  owner/name
```

After the first manual run the sweep is on a schedule and needs nothing from you. Building needs Rust and the Visual Studio C++ Build Tools; the tab is Windows-only.

## `>` TUNING

| DIAL | LOCATION |
|---|---|
| repos always scanned | `scanner/seeds.json` |
| discovery queries, issue window, ranking weights, reference phrases | top of `scanner/scan.py` |
| sweep times | `cron` in `.github/workflows/scan.yml` (UTC) and `SLOT_HOURS` in `app/src/main.rs` |
| busy thresholds | constants at the top of `app/src/main.rs` |
| Claude model, if a key is set | repo variable `VOTHUB_MODEL` |

## `>` FIELD NOTES

- HALT silences the laptop, not the cloud. The Action keeps its schedule; disable the workflow on GitHub to stop that too.
- GitHub's scheduler runs late, often by 5 to 30 minutes. The sweep is set 45 minutes ahead of the tab, and the tab rechecks every 10 minutes if the feed is not there yet.
- GitHub pauses scheduled workflows on repos with no commits for 60 days and emails a one-click re-enable.
- An embedding model is a blunt instrument. It ranks well at the top and gets vague in the middle. If the list drifts, tune the reference phrases.

```
> END OF TRANSMISSION
> _
```

<sub>The look is a tribute to lonely-signal-station games. Not affiliated with any of them.</sub>
