# Ticket 095: Add run-aware page snapshots and historical reporting semantics

## Goal
Support repeat crawls and historical comparisons without overwriting the only
stored page state or mixing unrelated domains/runs in reports.

## Background
Most persisted page data is unique by `url_id` and updated in place. Reports
query global tables with no run filter. This works as a one-database/current-state
cache, but the product also advertises refreshes, comparisons, audits, and
periodic re-runs. Users cannot reliably ask what changed between two database
runs, and analytics/report counts can mix sites when a database is reused.

Ticket 086 provides the urgent crawl-run identity/frontier isolation. This
ticket builds durable snapshot semantics on top of that identity.

## Tasks
- Define which data is immutable per fetch/run versus current URL identity or
  deduplicated lookup data.
- Associate page metadata, extracted content, hashes, detections, links, schema,
  canonicals/hreflang, and indexability with a crawl run or snapshot as needed.
- Preserve a convenient current-state view while retaining historical rows.
- Require/report a run selector for reporting, embeddings, sitemap generation,
  compaction, and comparison commands where ambiguity exists.
- Design migration, retention, pruning, and storage-cost controls.
- Add two-run integration tests proving historical values remain queryable and
  reports never mix runs accidentally.
- Concrete instances found while merging ticket 086 (2026-07-15): `reports.py`
  `site_hub_pages` aggregates `FROM frontier` with no `run_id` filter, so hub
  outlink counts inflate/double-count across a multi-run database; and
  `__main__.py` `_run_delete_crawl` calls `frontier_stats()` with no run id, so
  its printed frontier counts reflect only the `legacy` run and can disagree
  with the raw `frontier` row count shown alongside. Run-scope or explicitly
  aggregate both under this ticket's run-aware reporting semantics.

## Definition of Done
- Two crawls of the same URL retain distinguishable snapshots.
- Every report/enrichment command has deterministic run semantics.
- Current-state convenience and historical retention are both documented.

## Status
held (rework in PR #44; blocked on ticket 120) — 2026-07-16.

PR #33 was rejected because it filtered snapshot membership but still read
analysis fields from current-state tables and shipped a nonfunctional
`hreflang-groups` run selector with a red suite. The rework on branch
`agent/095-run-aware-snapshots` (PR #44) fixes all three: analysis/report reads
are snapshot-backed (`fetch_analysis_rows` reads `page_run_snapshots` +
`run_url_identity`/`run_intent_signatures`/`run_page_embeddings`), the
`hreflang-groups` selector threads `run_id` end-to-end, and the full suite is
green (670 passed against a real Postgres, including the new two-run historical
proof). The two named concrete instances are addressed (`reports.py`
`site_hub_pages` is `WHERE f.run_id = $1`; `_run_delete_crawl` aggregates via
`frontier_stats_all_runs()`).

**Not merged.** The rework regressed AMP-variant exclusion: `fetch_analysis_rows`
hardcodes `NULL::text AS variant_kind`, so `compute_exclusion` no longer returns
`"amp-variant"` and AMP variants leak back into intent-overlap pairing — the
defect ticket 103 fixed, uncaught by tests. Tracked as **ticket 120**. Re-review
PR #44 for merge only once 120 restores run-scoped `variant_kind`.
