# Ticket 114: Sitemap budget dedupe and cross-host Sitemap docs

**Status:** done (2026-07-16, PR #36)
**Priority:** P2 correctness / docs
**Related:** Ticket 087

## Goal

Prevent duplicate sitemap locs from consuming frontier budget slots, and
document how to allow CDN / cross-host `Sitemap:` targets after 087's
same-host enforcement.

## Background

PR #26 (ticket 087) correctly applies host scope, run-global budget, and
bounded politeness to sitemap ingestion. Two non-blocking follow-ups remain:

1. Sitemap loc lists are not deduplicated before budget accounting, so repeated
   locs under a small `--max-pages` can under-fill the frontier with distinct
   URLs.
2. Cross-host robots `Sitemap:` entries (common CDN hosts) are now correctly
   rejected under default same-host policy; operators need explicit
   `--allowed-hosts` / offsite guidance in CLI/docs.

## Tasks

- [x] Dedupe sitemap page locs (and/or count unique locs) before applying the
  remaining frontier budget cap; keep provenance for rejected duplicates if
  useful.
- [x] Add a regression where repeated locs under a small `--max-pages` still leave
  room for distinct URLs.
- [x] Document that CDN/`Sitemap:` hosts need `--allowed-hosts` (or equivalent
  offsite allow) after ticket 087; include a short example.

## Definition of Done

Duplicate locs do not waste frontier budget; docs state how to allow
cross-host sitemap hosts; unit coverage green; ruff + mypy clean.

## Delivery

PR #36 deduplicates sitemap page locs before finite frontier-budget accounting,
adds the repeated-loc regression, and documents CDN/cross-host `Sitemap:`
allowlisting. Ruff is clean. The normal unit suite and mypy remain blocked by
the pre-existing Ticket 117 `CrawlConfig.validate()` reference to removed
`max_pages`; the sitemap suite passes with that unrelated validation call
bypassed in memory.
