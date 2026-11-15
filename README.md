<div align="center">

<img src="docs/header.svg" width="100%" alt="VOTHUB: deep repo listening post. Station log: 64 trending repos located, 18 rejected, 1133 unclaimed signals received, 240 kept, strongest signal vllm-project/vllm at score 96.">

<br>

![status](https://img.shields.io/badge/STATUS-LISTENING-72f5a2?style=for-the-badge&labelColor=040806)
![sweeps](https://img.shields.io/badge/SWEEPS-07%3A00_%2F_19%3A00-ffb84a?style=for-the-badge&labelColor=040806)
![scan](https://img.shields.io/github/actions/workflow/status/onepizzateam/vothub/scan.yml?style=for-the-badge&label=CLOUD%20SCAN&labelColor=040806&color=72f5a2)
![shell](https://img.shields.io/badge/SHELL-TAURI_%2B_RUST-72f5a2?style=for-the-badge&labelColor=040806)

**A small green terminal in the corner of your screen that listens to GitHub<br>and tells you which open issues are actually worth your time.**

[`WHAT IT IS`](#-what-it-is) · [`SIGNAL PATH`](#-signal-path) · [`STATION CONTROLS`](#-station-controls) · [`GO ONLINE`](#-bring-the-station-online) · [`TUNING`](#-tuning)

</div>

## `>` WHAT IT IS

Twice a day a cloud job sweeps GitHub for repositories that are gaining stars fast, in two lanes. It throws away every repo that does not merge outside contributors, keeps only issues you could actually pick up, puts the ones maintainers have asked for help on first, and beams a 20 KB feed down to a tab that takes one sixteenth of your screen.

<p align="center">
<img src="docs/tab.svg" width="62%" alt="The mini tab: live waveform, 240 signals, 12 ready, top score 96, 74 repos, and a ticker of the top-ranked issues.">
</p>

| LANE | LISTENING FOR |
|---|---|
| `ai-infra` | agents, inference serving, model infra: crewAI, pydantic-ai, vLLM, SGLang, Ray, Mooncake, TensorRT, and whatever is breaking out this week |
| `systems` | bleeding-edge Rust, C++ and Zig, plus research implementations: databases, compilers, runtimes, GPU kernels |

Click the tab and it opens into the full console: the ranked list, tags for readiness, language, sector, kind and effort, filters, and a log of the last four days of sweeps. Click any signal to open the issue.

## `>` SIGNAL PATH

<img src="docs/pipeline.svg" width="100%" alt="Signal path: GitHub Actions runs discover, gate, filter, score and rank at 06:15 and 18:15 IST, then a 20 KB feed goes to the laptop, which pulls it at 07:00 and 19:00 unless the machine is busy.">

<details>
<summary><b><code>&gt; DECODE STAGE 01 // DISCOVER</code></b></summary>
<br>

GitHub search across about 20 topic and language queries, ranked by **stars per day** rather than total stars, so a three-month-old repo at 9k outranks a ten-year-old one at 40k. A fixed list in `scanner/seeds.json` is always scanned on top of that.

</details>

<details>
<summary><b><code>&gt; DECODE STAGE 02 // GATE</code></b></summary>
<br>

A repo is dropped if it is archived, if fewer than 4 pull requests from outsiders were merged in the last 90 days, or if it reads as an end-user app rather than infrastructure or systems software. Each surviving repo gets a **credibility** score: how often outsiders really get merged, how recognisable and how established it is, with a little credit for early traction. Repos in `seeds.json` are always kept.

</details>

<details>
<summary><b><code>&gt; DECODE STAGE 03 // FILTER</code></b></summary>
<br>

An issue survives only if it is open, under 45 days old, unassigned, with no open or merged PR linked and nobody saying "I'll take this". It is also thrown out when it is not something you could pick up:

- the author says they are doing it themselves (a prototype, a branch, "happy to submit a PR", a ticked "willing to contribute" box)
- it is an RFC, proposal, tracking issue, benchmark report or question
- maintainers marked it `needs triage`, `needs info`, `needs design`, `unconfirmed`, `in progress`, `duplicate` and the like
- a maintainer replied that it is already fixed or being handled internally
- a bot filed it

</details>

<details>
<summary><b><code>&gt; DECODE STAGE 04 // SCORE</code></b></summary>
<br>

`bge-small-en-v1.5`, a small embedding model, places each issue by kind, sector and substance. That is blended with body size, reactions, labels, how fast the repo is rising and how fresh the issue is. Verdicts are cached by the issue's `updated_at`, so an unchanged issue is never scored twice.

No API keys: the model runs on the Actions runner for free.

</details>

<details>
<summary><b><code>&gt; DECODE STAGE 05 // RANK</code></b></summary>
<br>

Every surviving issue is placed in one of three tiers, and the tier counts for more than anything in the text:

| TIER | MEANS |
|---|---|
| `READY` | maintainers asked for help: `help wanted`, `good first issue`, `community-backlog`, `ready-for-implementation`, `E-mentor`… |
| `VETTED` | triaged, confirmed or reproduced by the project, given a priority, or answered by a maintainer |
| `RAW` | nobody from the project has looked at it yet; capped, and only admitted as a short tail |

Within that: repo credibility, then substance, then freshness. Docs are forced to the bottom, tiny fixes lose points, at most 5 issues per repo.

</details>

## `>` STATION CONTROLS

<p align="center">
<img src="docs/halt.svg" width="62%" alt="Halt sequence: click HALT, pick a duration, confirm, and the station goes amber and silent until resumed.">
</p>

**HALT** stops everything on the laptop in one click: no syncing, no system probing, no animation. Pick a duration, confirm, done. **RESUME** is one click too.

| | |
|---|---|
| **BUSY GUARD** | CPU over 60%, memory over 90%, or battery under 20% unplugged: the tab stands down for an hour |
| **STORAGE** | one gzipped feed and a small state file; nothing older than four days survives |
| **FOOTPRINT** | a 4 MB executable, about 30 MB of RAM for the app itself |
| **STARTUP** | launches with Windows; toggle it under STATION |

## `>` BRING THE STATION ONLINE

```console
$ git clone https://github.com/onepizzateam/vothub && cd vothub/app
$ cargo build --release --features custom-protocol
$ ./target/release/vothub.exe
```

1. Push the repo to your own **public** GitHub repo.
2. `Actions` → `vothub-scan` → `Run workflow`. Only the first sweep is manual.
3. Point the tab at your repo: click it → `STATION` → `FEED REPO` → `owner/name`. Until you do, it listens to `onepizzateam/vothub` (`DEFAULT_REPO` in `app/src/main.rs`).

> [!TIP]
> After that first run the sweep is on a schedule and needs nothing from you.

> [!NOTE]
> Building needs Rust and the Visual Studio C++ Build Tools. The tab is Windows-only.

## `>` TUNING

<details>
<summary><b><code>&gt; OPEN DIAL PANEL</code></b></summary>
<br>

| DIAL | LOCATION |
|---|---|
| repos always scanned | `scanner/seeds.json` |
| discovery queries, issue window, ranking weights, reference phrases | top of `scanner/scan.py` |
| sweep times | `cron` in `.github/workflows/scan.yml` (UTC) and `SLOT_HOURS` in `app/src/main.rs` |
| busy thresholds | constants at the top of `app/src/main.rs` |
| these panels | `python docs/make_panels.py` |

</details>

<details>
<summary><b><code>&gt; READ FIELD NOTES</code></b></summary>
<br>

> [!WARNING]
> HALT silences the laptop, not the cloud. The Action keeps its schedule; disable the workflow on GitHub to stop that too.

- GitHub's scheduler runs late, often by 5 to 30 minutes. The sweep is set 45 minutes ahead of the tab, and the tab rechecks every 10 minutes if the feed is not there yet.
- GitHub pauses scheduled workflows on repos with no commits for 60 days and emails a one-click re-enable.
- An embedding model is a blunt instrument. It ranks well at the top and gets vague in the middle. If the list drifts, tune the reference phrases.

</details>

<div align="center">
<br>

```
> END OF TRANSMISSION
```

<sub>The look is a tribute to lonely-signal-station games. Not affiliated with any of them.</sub>

</div>
