# Ticket 087: Enforce host scope, page budget, and politeness during sitemap ingestion

## Goal
Make sitemap discovery obey the same scope, budget, and request-control rules as
ordinary link discovery.

## Background
`_discover_and_enqueue_sitemaps()` currently checks path restrictions but does
not apply `same_host_only` / `allowed_hosts` before enqueueing sitemap page URLs.
An external URL listed by an in-scope sitemap is therefore crawled even under
the default same-host policy. This was reproduced with `good.example` enqueueing
`evil.example/private`.

The method receives the crawl limit but enqueues the full sitemap result before
the main loop applies its page budget. Multiple 50k-URL shards can fill the
frontier during a `--max-pages 10` crawl. Sitemap and child-index fetches also
call the backend directly, bypassing the engine rate limiter, crawl delay,
per-host semaphore, circuit breaker, resilient fetch wrapper, and normal
challenge handling.

## Tasks
- Apply the engine's canonical host-scope decision to sitemap children, page
  URLs, and sitemap hreflang targets before fetching/enqueueing.
- Reject unsupported schemes and malformed/credential-bearing sitemap URLs.
- Apply a run-global frontier/page budget before bulk enqueue; avoid inserting
  thousands of rows that cannot be consumed in the current run.
- Route sitemap fetches through a bounded request path that honours proxy
  selection, retries, per-host concurrency, rate limiting, crawl delay, response
  caps, circuit breaking, and challenge handling where applicable.
- Record rejected sitemap URLs as out-of-scope provenance without fetching them.
- Add tests for external sitemap entries, `allowed_hosts`, external child
  indexes, small `max_pages`, and per-host request controls.

## Definition of Done
- Default same-host crawls never fetch an offsite sitemap URL or page unless it
  is explicitly allowed.
- Sitemap ingestion cannot exceed the active run's frontier budget.
- Sitemap concurrency is bounded by the same operational controls as page fetches.

## Status
done (2026-07-15, PR #26) (Priority: **P0**) — `agent/ticket-087-sitemap-scope-budget-politeness`; scope/security/politeness; found in 2026-07-15 audit.

