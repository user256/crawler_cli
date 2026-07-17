# Ticket 124: crawler_gui crawl management — run selector in the UX + working "+ New Crawl"

## Goal
Turn crawler_gui from a viewer into a local crawl manager:

1. **Crawl selector in the current UX** — a dropdown (header area) listing the
   crawl runs in the connected database, switching the viewed run in-place;
   history-modal cards switch runs too. Today the only way to change run is
   hand-editing the `?run=` URL parameter.
2. **"+ New Crawl" that actually crawls** — the existing New Crawl modal
   submits to the local bridge, which starts a real `crawler_cli` crawl and
   shows its progress; on completion the new run appears in the selector.

## Background — current state (evidence, 2026-07-17)

- `crawler_gui/server.py` (local WIP, untracked — landed by ticket 125) is a
  **deliberately read-only** loopback bridge: `GET /api/live/runs` +
  `GET /api/live/snapshot?run=…&limit=…`. Its docstring and the README keep
  crawl submission/cancel/delete out of the bridge "until owned by
  `crawler_api`". This ticket **consciously extends that boundary** for
  local-first use: submission via the loopback bridge is acceptable; delete
  stays out (see Constraints).
- `app.js` live mode (`?live=1`) fetches one snapshot at load; run choice is
  URL-param only; the history modal renders run cards (with a `viewing`
  highlight) but clicking them does not switch runs; the New Crawl / Schedule
  modals are prototype-only (toasts, no submission).
- Everything needed to run a crawl already exists in `crawler_cli`:
  `python -m crawler_cli crawl <url> --postgres-dsn … [--max-pages N]
  [--backend …] [--respect-robots …]` etc. The bridge only has to map the
  modal's existing config fields onto CLI flags and spawn a subprocess.

## Tasks

### A. Run selector
- Header dropdown in live mode listing runs (`/api/live/runs`): domain,
  date, status, URL count; selecting one re-fetches the snapshot for that
  run and updates the `?run=` param (shareable URLs keep working).
- History-modal cards become clickable to switch runs (same path).
- Prototype (fixture) mode keeps current behaviour; the dropdown renders
  from `data.history` with switching disabled.

### B. Crawl submission via the bridge
- `POST /api/live/crawls` on server.py: seed URL or URL-list, and the config
  fields the New Crawl modal already exposes (mode, max pages, concurrency,
  robots, backend) mapped to `crawler_cli` CLI flags. Spawn
  `python -m crawler_cli crawl …` as a subprocess against the bridge's DSN.
- Job tracking: `GET /api/live/crawls/<job_id>` (state, started/finished,
  exit code, tail of log output). The run selector/history refreshes to show
  the new run as soon as `crawl_runs` has it (poll `/api/live/runs`).
- One running job at a time in v1: a second submission while one is active
  returns 409 with the active job id. Queueing is a follow-up.
- Wire the New Crawl modal to submit, disable while running, and surface
  progress (poll) + terminal state (success / non-zero exit with stderr tail).

### C. Docs + decision record
- README: document the boundary change (bridge = local viewer **+ local
  submission**; delete/cancel remain out until `crawler_api` owns jobs), the
  security posture (loopback only, no auth), and the run-selector UX.

## Definition of Done
- With the bridge running against a multi-run DB: the dropdown lists all runs,
  switching updates tables/overview in place, and the URL stays shareable.
- "+ New Crawl" on a small real site produces a completed run visible in the
  selector without restarting the bridge; a failing crawl surfaces its error
  in the UI rather than silently disappearing.
- Concurrent-submission guard returns 409 and the UI explains it.
- Prototype (non-live) mode is unchanged for all of the above.
- Node GUI tests + any bridge tests green; README updated.

## Constraints
- Bridge stays loopback-only (`127.0.0.1`), no auth added — do not expose it
  beyond localhost; this is explicitly not the `crawler_api` control plane.
- **No delete** from the GUI (the `delete-crawl` footgun stays CLI/API-only).
- Crawls go through the `crawler_cli` CLI (subprocess), not by importing the
  engine into the aiohttp process — keeps the bridge disposable and the crawl
  isolated/killable.
- Depends on ticket 125 (bridge landed in-repo, all-runs access solid).

## Follow-up (not in scope)
- Chrome/Chromium personal-profile crawling from the GUI: the engine already
  supports it end-to-end (`--playwright-user-data-dir`,
  `--playwright-profile-directory`, `--playwright-channel chrome`, `--headed`;
  `launch_persistent_context` in backends.py). Once B lands, a follow-up
  ticket adds the GUI profile picker: OS profile auto-discovery (Chrome
  `Local State` → `profile.info_cache`), a locked-profile pre-flight
  ("close Chrome first"), dedicated-profile guidance (Chrome 136+ blocks
  automation on the default profile dir), and mutual exclusion with the
  Obscura backend. Windows app-bound cookie encryption is the known risk.

## Status
open (2026-07-17) — depends on ticket 125.
