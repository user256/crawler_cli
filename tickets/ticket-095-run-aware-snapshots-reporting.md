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
open — rework required after PR #33 was rejected on 2026-07-16. The attempted
implementation filtered snapshot membership but still read analysis fields from
current-state tables, which cannot support historical reporting; its
`hreflang-groups` run selector was also nonfunctional. Reopen only with
snapshot-backed data paths, functional scope enforcement, and a green suite.
