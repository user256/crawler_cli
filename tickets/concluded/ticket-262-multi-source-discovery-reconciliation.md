# Ticket 262: Multi-source discovery provenance and reconciliation

**Status:** Concluded with remediation 265 — merged to `master` after review on 2026-09-29.
**State:** Needs closing
**Priority:** P2
**Module:** reports

## Delivered

- `crawler-cli reconcile-sources` joins a selected run's link graph with local/current sitemap, GSC, and backlink sources.
- Produces deterministic JSON and optional CSV partitions, source-overlap counts, coverage qualifications, URL evidence, and remediation guidance.
- Keeps out-of-scope hosts separate rather than fetching or silently joining them.

## Deferred

Recipient Google Sheets delivery is not wired; ticket 265 owns that optional output path.

## Review evidence

`tests/test_source_reconciliation.py` passed; full integrated suite: 1,615 passed, 60 skipped.
