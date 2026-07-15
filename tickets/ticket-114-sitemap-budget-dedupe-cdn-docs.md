# Ticket 114: Sitemap budget dedupe and cross-host Sitemap docs

**Status:** proposed (2026-07-15 MERGE+REMEDIATE from ticket 087 / PR #26)
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

- Dedupe sitemap page locs (and/or count unique locs) before applying the
  remaining frontier budget cap; keep provenance for rejected duplicates if
  useful.
- Add a regression where repeated locs under a small `--max-pages` still leave
  room for distinct URLs.
- Document that CDN/`Sitemap:` hosts need `--allowed-hosts` (or equivalent
  offsite allow) after ticket 087; include a short example.

## Definition of Done

Duplicate locs do not waste frontier budget; docs state how to allow
cross-host sitemap hosts; unit coverage green; ruff + mypy clean.
