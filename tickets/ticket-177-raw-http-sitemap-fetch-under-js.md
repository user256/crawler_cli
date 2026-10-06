# Ticket 177: Fetch sitemaps as raw HTTP under browser page backends

## Goal

Make sitemap discovery parse the publisher's XML/text response regardless of
the selected page-rendering backend. `--js` must not turn an XML sitemap into a
Chromium viewer DOM and silently discover zero URLs.

## Background

`CrawlEngine._bounded_fetch_response()` calls the configured backend for
`purpose="sitemap"`. `PlaywrightBackend.fetch()` serialises `page.content()`,
which is the browser's XML viewer document rather than the sitemap response.
`SitemapParser._parse_xml()` consequently finds no sitemap nodes. The
Obscura one-shot path has a raw-document special case, but Playwright does not,
so the result currently depends on the page backend.

## Tasks

- Add an explicit raw-HTTP sitemap transport path for Playwright and any other
  rendered page backend; use it for sitemap indexes, XML, gzip XML, and text
  sitemaps only.
- Preserve the crawl's configured request identity, proxy policy, response
  byte cap, redirect evidence, destination guard, scope predicate, robots
  decision, rate limit, host concurrency, and circuit-breaker accounting. A
  bare side-session that bypasses ticket 149 or ticket 087 is not acceptable.
- Keep ordinary HTML page fetches under `--js` rendered as today.
- Make an explicit unsupported-combination error if a browser-only setting
  cannot faithfully apply to the raw sitemap request; never return an empty
  sitemap as though it had parsed successfully.

## Definition of Done

- A fixture XML sitemap and nested index discover the same URLs with the HTTP
  and Playwright page modes.
- The raw sitemap body, not an XML viewer HTML document, reaches `SitemapParser`.
- Scope/destination denial and response-cap behaviour are covered on the raw
  path.
- A rendered page crawl remains rendered.

## Status

proposed (2026-09-23, Priority: **P1**) — correctness; found in Shopify crawls.
