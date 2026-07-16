# Ticket 120: Restore AMP-variant exclusion under run-aware snapshot reads (095 blocker)

**Status:** open (blocker for merging Ticket 095)
**Priority:** P1 — silent analysis regression
**Depends on:** Ticket 095 rework branch (`agent/095-run-aware-snapshots`, PR #44)
**Re-opens:** Ticket 103 (AMP-variant awareness / exclusion)

## Problem

The Ticket 095 rework (PR #44) correctly moves analysis/report reads onto
snapshot-backed tables, but in doing so it drops the AMP `variant_kind` signal
from the intent-overlap analysis path. `fetch_analysis_rows` hardcodes
`NULL::text AS variant_kind` (persistence.py:3374), while `compute_exclusion`
(intent_overlap.py:902) and `classify_url` (intent_overlap.py:937) still rely on
`variant_kind == "amp"`. `classify_amp_variants` continues to write
`urls.variant_kind = 'amp'` (persistence.py:3330-3333), but nothing reads it
back: `run_url_identity` has no `variant_kind` column, so the value never
reaches the analysis rows.

Confirmed empirically against a real database during PR #44 review: an AMP page
missing a canonical is classified `amp` in `urls.variant_kind` and flagged
`missing-canonical` by hygiene, yet `fetch_analysis_rows` returns
`variant_kind = None` and `compute_exclusion` returns `None` instead of
`"amp-variant"`. Effect: **AMP variants (especially those missing canonicals)
leak back into intent-overlap pairing as noise — the exact defect Ticket 103
fixed.** The `amp_variants` summary count still looks correct (it is sourced
from `amp_hygiene`), which masks the breakage. No test catches it:
`test_classify_amp_variants_marks_variant_kind_and_hygiene` only asserts the
write to `urls`, never the flow through `fetch_analysis_rows`.

This regression is why Ticket 095 / PR #44 is held rather than merged.

## Tasks

- Persist `variant_kind` run-scoped: add a column to `page_run_snapshots` (or
  `run_url_identity`) and have `classify_amp_variants` write it with the
  `run_id`, so the value survives per run.
- Change `fetch_analysis_rows` (persistence.py:3374) to read the run-scoped
  `variant_kind` instead of `NULL::text`.
- Add an integration test asserting `compute_exclusion` returns `"amp-variant"`
  through `fetch_analysis_rows` for an AMP page missing a canonical (i.e. the
  full flow, not just the write to `urls`).

### Minor items found in the same review (fold in here)

- Remove the stale/misleading comment at intent_overlap.py:1531
  ("so variant_kind is populated before the analysis rows are loaded") — it no
  longer describes the behaviour.
- `CrawlReports._run_id()` uses `store._resolve_run_id` (falls back to
  `active_run_id='legacy'`), not the multi-run `resolve_reporting_run_id`. In a
  multi-run DB the DB-backed report methods (`site_hub_pages`, `orphan_pages`,
  etc.) will silently report the legacy run. Low impact today (not CLI-exposed
  with a selector) — guard or document it.

## Definition of Done

`compute_exclusion` returns `"amp-variant"` for AMP variants through the
snapshot-backed `fetch_analysis_rows` path, an integration test proves the full
flow, and the minor items above are resolved. Once green, Ticket 095 / PR #44
can be re-reviewed for merge.
