---
name: frontier-tracker
description: Manage and operate the FrontierWildWatch GoWild tracker (scan, dry-run, probe, schedule one-shot runs, and summarize health). Use when asked for Frontier GoWild checks, airport-group scans (e.g., LA area to SF area), scheduled wake-and-run tasks, tracker status, or route probing.
---

# Frontier Tracker

Repo root: `./`
Skill dir: `./skills/frontier-tracker`
Groups file: `./skills/frontier-tracker/groups.json`
Wrapper script: `./skills/frontier-tracker/scan.sh`

## Safety Rules (mandatory)

- Never run more than one scan at a time.
- Respect cooldown in `state.json`: if `metrics.cooldown_until_utc` is in the future, do not scan; report cooldown instead.
- Do not mutate `config.json` directly for ad-hoc scans. Use a temp config copy (`/tmp/frontier_scan_tmp.json`).
- For requests that say “don’t run real scan”, use `--dry-run` only.

## Airport groups

Load/edit `groups.json` for aliases. Defaults:
- `LA_AREA = LAX,SNA,ONT,BUR,LGB`
- `SF_AREA = SFO,SJC,OAK`
- `DEN_AREA = DEN`
- `NYC_AREA = EWR,JFK,LGA`

When asked for “LA area to SF area”, expand to all combinations of origins in `LA_AREA` and destinations in `SF_AREA`.

## Setup (mandatory first step)

Before running scans for the first time, the repository configuration must be initialized. The project comes with anonymous mobile SDK tokens (not tied to any personal identity) that bypass bot protection out of the box.

```bash
python3 setup_config.py
```

## Run scan workflow

Preferred command (handles lock + cooldown + temp config):

```bash
./skills/frontier-tracker/scan.sh \
  --origins LAX,SNA,ONT,BUR,LGB \
  --destinations SFO,SJC,OAK
```

Dry run:

```bash
./skills/frontier-tracker/scan.sh --dry-run
```

Repo-native direct run (only when no route override needed):

```bash
python3 scanner.py --config config.json
```

## Output policy for scans/probes (mandatory)

When reporting scan or probe results, always provide full flight details up front.

For each flight, include:
- route (origin → destination)
- date
- departure time
- arrival time
- number of stops
- layover airport(s) and layover duration(s) when present
- price

If no flights are found, state that explicitly.

## Recommendation rule (mandatory)

After listing full flight details, add a **Recommended flight** section:
- Primary choice: lowest layover duration among flights with a valid GoWild price.
- Tie-breaker #1: lowest GoWild price.
- Tie-breaker #2: earliest departure.
- If no flights have a valid GoWild price, choose lowest layover overall, then earliest departure.
- Include one-line reason.

## Probe a route

For requests like “test LAX to SFO for 2026-03-05”:

```bash
python3 scanner.py --config config.json --probe LAX SFO 2026-03-05 --probe-output probe.json
```

Always return full flight details first, then probe diagnostics:
- status (ok/blocked/error)
- status_code/reason/body_snippet when relevant

## Check tracker status

Read and summarize:
- `run-report.json`
- `state.json`

Include:
- planned/ok/blocked/error query counts
- new flights found
- cooldown status (`cooldown_until_utc`)
- recent run history entries (timestamp + ok/blocked/error)

## Schedule one-shot scans

For requests like “wake up Thursday at 11:50pm and check LAX to SFO”:

1. Convert local time to ISO timestamp.
2. Create a one-shot cron job with `sessionTarget="isolated"`, `payload.kind="agentTurn"`, and `delivery.mode="announce"`.
3. Include run instructions and enforce cooldown/lock rules.

Suggested job message:
- “Run Frontier tracker one-shot now. Enforce single-scan lock and cooldown check. Use ORIGINS=... DESTINATIONS=.... Run scan via scan.sh and post full flight details (depart/arrive/stops/layovers/price), then concise run status.”

## Intent parsing

- “check flights from X to Y” → run scan with route override
- “dry run” / “test plan” → `--dry-run`
- “test/probe X to Y date” → `--probe`
- “how’s tracker doing / last scan” → read `run-report.json` + `state.json`
- “wake up <time> and run” → schedule via cron isolated announce
