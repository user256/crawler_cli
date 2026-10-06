# Ticket 164: Retain sitemap hreflang in run snapshots

## Goal
Stop crawling a page from wiping sitemap-sourced hreflang, and make run
snapshots (the source of truth for intent-overlap) carry those edges.

## Background (2026-07-22 wiring audit)

Sitemap xhtml:link edges are written only to the mutable `hreflang_sitemap`
table (`engine.py` → `persist_sitemap_hreflang_bulk`). On HTML persist,
`_clear_page_snapshot` **DELETE**s `hreflang_sitemap` for that `url_id`
(`persistence.py`). The immutable snapshot’s `hreflang_json` is built only from
`extracted.hreflang_links` (HTML head / HTTP header) — sitemap edges are never
merged in.

`fetch_hreflang_edges` (ticket **078** / intent-overlap) reads **only**
`page_run_snapshots.hreflang_json`, not the mutable tables. So for sites that
publish hreflang mainly in sitemaps, those edges vanish from analysis after
the page is crawled.

Related gap (same root cause class): `hreflang_data` is collected before the
frontier budget trim, then `persist_sitemap_hreflang_bulk(hreflang_data)` runs
on the **untrimmed** list while enqueue uses the trimmed set — never-crawled
URLs still pollute the mutable table. Fix both in this ticket or split the
budget filter into a small sub-task if preferred.

## Tasks
- Merge sitemap xhtml:link into the run snapshot `hreflang_json` (with a clear
  `source` marker), and/or stop deleting sitemap-only edges without replacement.
- Filter bulk sitemap hreflang persist to the effective accepted URL set after
  frontier-budget trimming, `--refresh-days`, and existing-frontier dedupe. The
  current enqueue API returns only a count, so either precompute the exact set
  once or change the helper to return accepted URLs; filtering only against the
  pre-enqueue `frontier_data` list is insufficient.
- Keep HTML/header hreflang behaviour unchanged.
- Regression: sitemap-only hreflang → `fetch_hreflang_edges` / intent-overlap
  groups after the page has been crawled.

## Definition of Done
- A finished run’s snapshot retains sitemap hreflang when present.
- `_clear_page_snapshot` does not drop sitemap-only edges without writing them
  into the snapshot.
- `fetch_hreflang_edges(run_id=…)` returns those edges for a completed crawl.
- Tiny-`max_pages` test: hreflang is not bulk-written for URLs dropped by
  frontier budget (or is documented as intentional if retained for another
  consumer — default should be filter).
- Refresh-skipped and already-present frontier URLs do not gain mutable
  sitemap-hreflang rows merely because they were present in the pre-enqueue
  candidate list.

## Status
proposed (Priority: **P0**) — intent-overlap / international correctness;
found in 2026-07-22 audit.
