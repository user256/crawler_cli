# Ticket 120: Restore AMP-variant exclusion under run-aware snapshot reads (095 blocker)

**Status:** done — folded into and merged with PR #44 on 2026-07-16
**Priority:** P1 — silent analysis regression
**Depends on:** Ticket 095 rework branch (`agent/095-run-aware-snapshots`, PR #44)
**Re-opened:** Ticket 103 (AMP-variant awareness / exclusion)

## Problem

The Ticket 095 rework moved analysis reads onto snapshot-backed tables but
initially dropped the AMP `variant_kind` signal. That allowed AMP variants,
including those missing a canonical, back into intent-overlap pairing.

## Resolution

- `page_run_snapshots.variant_kind` retains the classification per run.
- `classify_amp_variants` clears and writes the selected run's label while
  retaining `urls.variant_kind` as the mutable convenience projection.
- `fetch_analysis_rows` reads the snapshot label.
- The integration suite covers the complete path from AMP classification through
  `fetch_analysis_rows` to `compute_exclusion == "amp-variant"`.
- `CrawlReports` resolves reporting runs through the multi-run guard, and the
  stale intent-overlap comment was replaced.

## Definition of Done

`compute_exclusion` returns `"amp-variant"` for AMP variants through the
snapshot-backed `fetch_analysis_rows` path, an integration test proves the full
flow, and report selection cannot silently fall back to `legacy` in a multi-run
database.
