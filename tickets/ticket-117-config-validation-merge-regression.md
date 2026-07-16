# Ticket 117: Restore CrawlConfig validation after ticket-093/112 integration

**Status:** done (2026-07-16, PR #39)
**Priority:** P1 regression
**Related:** Tickets 093 and 112

## Problem

The merged ticket-093 `CrawlConfig.validate()` still validates `self.max_pages`,
but ticket 112 correctly removed that dead field in favour of
`default_open_crawl_limit`. This makes `mypy src/crawler_cli` fail with:

```text
"CrawlConfig" has no attribute "max_pages"
```

## Tasks

- Remove the stale `max_pages` validation and retain validation of the sole
  crawl-limit field, `default_open_crawl_limit`.
- Add or adjust a direct-library validation test that proves zero remains the
  explicit unlimited sentinel for that field.
- Run ruff, mypy, and the non-integration test suite.

## Definition of Done

The combined ticket-093/112 behaviour type-checks, validates the active crawl
limit field only, and has a green unit suite.

## Acceptance notes

- Removed validation of the deleted `max_pages` field.
- Direct-library coverage keeps `default_open_crawl_limit=0` as the explicit
  unlimited sentinel.
- Ruff and mypy passed; the non-integration suite was run before merge.
