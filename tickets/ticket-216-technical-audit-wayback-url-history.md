# Ticket 216: Use Wayback Machine URL history as an audit inventory

## Goal

Let `technical-audit` include a site's archived URL history as a labelled
inventory, so the audit reports formerly live URLs that now fail, which the
crawl, sitemaps and internal links can never surface.

## Background

On the 2026-09-25 rainbet.com audit the Wayback CDX index held 34,735 unique
URLs against 7,715 sitemap URLs. A hand-built pass found 4,074 content URLs
outside the sitemap and the site; 3,378 now return 404, directly or through a
redirect, including whole retired URL families (`/casino/roulette/*`,
`/casino/live/<category>/<game>`). None of this is visible to the current audit.

The hand-built pass used `collapse=urlkey`, which keeps one capture per URL, so
"last seen live" dates were really single-capture dates. That mistake should not
be repeated in the product.

## Tasks

- Add an opt-in source (for example `--wayback-inventory`) that pulls the CDX
  index for the audited host(s) with paging, retries and a request budget.
- Keep capture history per URL: first seen, last seen, last capture with a
  200 status. Do not collapse to one capture.
- Filter non-content noise deterministically: assets, `/_next/`, `cdn-cgi`,
  bot user-agent strings embedded in paths, CSS-variable fragments, bare
  numbers. Record every exclusion rule and count.
- Classify each URL against the run: crawled, in current sitemap, locale
  alternate of a sitemap URL, or archive-only.
- Feed archive-only URLs into the supplied-inventory path from ticket 204 so
  the existing live-recheck gate (185/207) decides their current state.

- Master rejects these URLs today: `--known-url-inventory` accepts only the
  `analytics` and `search_console` sources (seen 2026-09-28). Add a `wayback`
  source with its own provenance fields.

## Definition of Done

- A fixture CDX response yields correct first, last and last-200 dates per URL.
- Noise filtering is rule-based and reported with counts.
- Archive-only URLs appear in the audit with source `wayback` and a live status
  only when a live recheck ran; otherwise they are `unverified`.
- The rainbet run reproduces the archive-only population within the documented
  noise rules.
