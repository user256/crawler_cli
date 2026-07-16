## Ticket queue
A list of tickets, their status and the md file which summarises action taken for subsequent review.

**Authoritative register** for status, acceptance notes, and delivery order.
Ticket files remain the source of truth for scope and DoD.

### Current position (2026-07-15)

- Batch review of open PRs **#22–#26** complete: all five merged to `master`
  (087 / 088 / 089 / 092 / 108). Pre-merge CI blockers fixed in-branch (088
  ruff format; 089 integration fixture `h2` key).
- Next lane claimed for parallel worktrees: **095 / 106→107** (see Open work).
  **093**, **096**, **098**, **100**, **112**, and **113** are done. Leftovers
  **114 / 115 / 116** remain unclaimed.
- Tickets **101–105** + **108** form the intent-overlap reporting baseline;
  **106** / **107** are unblocked on AMP evidence.
- Ticket **110** remains unused/rejected; next free number is **117**.

### Ordering rules

- Correctness and evidence hardening precede presentation work that consumes
  the affected fields.
- Ticket **107** cannot start before **106** defines and tests the JSON contract;
  **106** may proceed now that **108** is on master (production AMP recount is
  **116**, not a 106 blocker).
- External/manual evidence is recorded as a blocker; it is never inferred from
  unit tests.
- New remediation work uses the next free number (**117**); do not reuse **110**.

- `001` `done` [ticket-001-crawler-modularisation.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-001-crawler-modularisation.md)
- `002` `done` [ticket-002-bounded-crawler-behaviour.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-002-bounded-crawler-behaviour.md)
- `003` `done` [ticket-003-resumable-frontier.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-003-resumable-frontier.md)
- `004` `done` [ticket-004-content-hashing.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-004-content-hashing.md)
- `005` `done` [ticket-005-circuit-breaker.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-005-circuit-breaker.md)
- `006` `done` [ticket-006-crawl-comparison.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-006-crawl-comparison.md)
- `007` `done` [ticket-007-historical-discovery.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-007-historical-discovery.md)
- `008` `done` [ticket-008-reporting-views.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-008-reporting-views.md)
- `009` `done` [ticket-009-frontier-priority.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-009-frontier-priority.md)
- `010` `done` [ticket-010-cms-detection.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-010-cms-detection.md) — CMS detection module; debt closed: `--cms-detection` CLI flag now wired in `__main__.py` (alongside ticket-038)

### Mini SEO audit expansion (driven by `/home/user256/Canonicals/TechAuditRedux`)

- `011` `done` [ticket-011-cli-entry-point.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-011-cli-entry-point.md) — `__main__.py` + argparse + pyproject.toml entry point
- `012` `done` [ticket-012-archive-org-audit-report.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-012-archive-org-audit-report.md) — `audit_archive_urls()` with CSV output
- `013` `done` [ticket-013-url-provenance.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-013-url-provenance.md) — `url_sources` table + `record_source` helpers
- `014` `done` [ticket-014-sitemap-auto-discovery.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-014-sitemap-auto-discovery.md) — engine fetches robots.txt + well-known sitemaps
- `015` `done` [ticket-015-archive-url-hygiene.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-015-archive-url-hygiene.md) — `_normalize_url` + `_clean_url` with configurable filters
- `016` `done` [ticket-016-soft-404-utilities.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-016-soft-404-utilities.md) — `soft_404_fingerprint` + `simhash_neighbours`
- `017` `done` [ticket-017-url-variant-probes.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-017-url-variant-probes.md) — `generate_variants` + `probe_variant`
- `018` `done` [ticket-018-robots-rule-introspection.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-018-robots-rule-introspection.md) — `_RobotsRules` + `RobotsDecision` + `check()`
- `019` `done` [ticket-019-render-comparison.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-019-render-comparison.md) — `compare_renders` + `compare_renders_sampled`

### Expanded Scope (Ported from WIP)

- `020` `done` [ticket-020-schema-extraction.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-020-schema-extraction.md) — Schema.org extraction (JSON-LD, Microdata, RDFa)
- `021` `done` [ticket-021-advanced-link-analysis.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-021-advanced-link-analysis.md) — Advanced Link Graph (Anchor Text & XPath)
- `022` `done` [ticket-022-path-restrictions.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-022-path-restrictions.md) — `--path-restriction` and `--path-exclude`
- `023` `done` [ticket-023-vector-embeddings.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-023-vector-embeddings.md) — Vector Embeddings Generation
- `024` `done` [ticket-024-cli-csv-auth.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-024-cli-csv-auth.md) — CLI CSV Ingestion & HTTP Authentication
- `025` `done` [ticket-025-deep-crawl-comparison.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-025-deep-crawl-comparison.md) — Deep Crawl Comparison Engine
- `032` `done` [ticket-032-persistence-performance-fixes.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-032-persistence-performance-fixes.md) — Persistence Layer Performance & Race Conditions Fixes
- `033` `done` [ticket-033-session-crawl-logic.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-033-session-crawl-logic.md) — Session Crawl Logic & Limits Fixes

### Crawler feature enhancements (ported from WIP backlog)

These were tracked as standalone `ticket-026`..`ticket-031` files but never listed in the
queue. Closed in the 2026-06-07 batch pass — see
[DECISIONS-2026-06-07.md](/home/user256/GitRepos/crawler_cli/tickets/DECISIONS-2026-06-07.md).

- `026` `done` [ticket-026-custom-extraction.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-026-custom-extraction.md) — Custom data extraction (CSS/XPath/regex) → `content.custom_data` JSONB
- `027` `done` [ticket-027-proxy-support.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-027-proxy-support.md) — `--proxy`/`--proxy-auth` across aiohttp/curl_cffi/playwright (rotation deferred)
- `028` `done` [ticket-028-session-cookies.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-028-session-cookies.md) — `--cookie`/`--cookies-file` (JSON + Netscape) injected as Cookie header
- `029` `done` [ticket-029-performance-metrics.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-029-performance-metrics.md) — TTFB + total duration → `page_metadata`; `slowest_pages` report (CWV deferred)
- `030` `done` [ticket-030-sitemap-generation.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-030-sitemap-generation.md) — `generate-sitemap` subcommand with >50k index splitting
- `031` `done` [ticket-031-js-wait-conditions.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-031-js-wait-conditions.md) — `--wait-for-selector` + `--wait-for-network-idle` for SPAs

### Future Enhancements (Low Priority)

- `034` `done` [ticket-034-playwright-memory-bounds.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-034-playwright-memory-bounds.md) — Playwright Context Recycling & Memory Bounds
- `035` `proposed (deferred)` [ticket-035-redis-frontier-queue.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-035-redis-frontier-queue.md) — Redis-Backed Frontier Queue. **Deferred from 2026-06-07 batch**: architectural refactor needing a Redis dependency + infra and touching the hot crawl loop; warrants a dedicated reviewed PR. See DECISIONS-2026-06-07.md.

### GuardGeese Integration

- `036` `done` [ticket-036-guardgeese-fetch-extract-bridge.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-036-guardgeese-fetch-extract-bridge.md) — Standalone fetch/extract bridge for `guardgeese-worker`
- `037` `done` [ticket-037-guardgeese-monitoring-boundary.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-037-guardgeese-monitoring-boundary.md) — README boundary docs complete (ticket header marks it Done). Only the external GuardGueeseRedux `blockers.md`/WORKER-003 metadata is out of this repo's scope.

### Audit Coverage

- `038` `done` [ticket-038-analytics-tag-manager-detection.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-038-analytics-tag-manager-detection.md) — Analytics/tag-manager/pixel/A-B detection (detector, CLI flags, persistence, four reports, tests). Status corrected to `done` on 2026-06-07 — was already fully implemented but mismarked.

### Storage & lifecycle

- `039` `done` [ticket-039-expose-circuit-breaker-tuning.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-039-expose-circuit-breaker-tuning.md) — Circuit-breaker thresholds on CLI + env vars; 429 trigger + OPEN-transition logging
- `040` `done` [ticket-040-html-compression.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-040-html-compression.md) — **P0:** gzip HTML on write; fix misleading `html_compressed` column; backfill command
- `041` `done` [ticket-041-crawl-delete-command.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-041-crawl-delete-command.md) — **P1:** `delete-crawl` subcommand (truncate or drop database) with `--confirm`
- `042` `done` [ticket-042-compact-crawl-drop-html-keep-fingerprints.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-042-compact-crawl-drop-html-keep-fingerprints.md) — **P1:** `compact-crawl` — purge stored HTML, retain content hashes + audit metadata; wire `--content-hashing`

### JS backend enhancements

- `043` `done` [ticket-043-obscura-managed-backend-default-stealth.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-043-obscura-managed-backend-default-stealth.md) — First-class Obscura backend with managed lifecycle and stealth on by default

### Cross-repo

- `044` `done` [ticket-044-port-obscura-to-postgresqlcrawlerwip.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-044-port-obscura-to-postgresqlcrawlerwip.md) — Port Obscura managed backend + default stealth back into PostgreSQLCrawlerWIP. Done 2026-06-13 in that repo (git-init'd first; commit abaed4b): BrowserRuntime + PlaywrightBackend with managed-Obscura lifecycle in fetch.py, obscura_cli.py for testable CLI validation, config/CLI/runtime-logging wired, 19 new tests (29 total pass). Known follow-up: that repo's BFS loop still fetches over HTTP regardless of use_js (pre-existing; JS backend reachable via fetch_js/fetch_many) — wiring JS into the loop is out of this ticket's "extend, don't replace" scope.

> **HTTP API note:** the `crawler_api` FastAPI service lives in its **own repo**
> (`/home/user256/GitRepos/crawler_api`, which depends on `crawler_cli`), with its own
> ticket system (sprints 1–4: 201–204, 301–305, 401–403). API work — durable job
> persistence (204), auth hardening (304), concurrency limits (301), report/compare
> endpoints (201/202) — is tracked there, **not** here. A stray `src/crawler_api/` copy was
> briefly committed to this repo on 2026-06-07 and removed on 2026-06-08.

### Deferred stretch goals (split out of completed tickets, 2026-06-08)

- `045` `done` [ticket-045-proxy-rotation.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-045-proxy-rotation.md) — Proxy rotation / pool (stretch of ticket-027); round-robin + per-host strategies, failure eviction
- `046` `done` [ticket-046-core-web-vitals.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-046-core-web-vitals.md) — Core Web Vitals (LCP/CLS/INP) via Playwright PerformanceObserver (stretch of ticket-029)
- `047` `done` [ticket-047-curl-cffi-ttfb.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-047-curl-cffi-ttfb.md) — TTFB for the curl_cffi backend via streaming first-chunk timing (gap from ticket-029)
- `048` `done` [ticket-048-cookie-scoping.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-048-cookie-scoping.md) — Per-domain/path cookie scoping (limitation from ticket-028)

### 2026-06-11 audit findings

Full-codebase audit (engine, backends, robots, CLI, persistence, project tooling).

- `049` `done` [ticket-049-unlimited-crawl-link-enqueue.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-049-unlimited-crawl-link-enqueue.md) — **P0:** `--max-pages 0` (the default) never enqueues discovered links — frontier budget `max(0, 0 - total)` is always 0
- `050` `done` [ticket-050-robots-rfc9309-compliance.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-050-robots-rfc9309-compliance.md) — **P1:** robots.txt fixes: hardcoded https scheme (http sites get allow-all), last-match-wins precedence, exact-string UA matching, 5xx → permanent allow-all
- `051` `done` [ticket-051-cli-arg-and-dsn-hygiene.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-051-cli-arg-and-dsn-hygiene.md) — **P1:** `--concurrency` silently ignored (max-workers default always wins); DSN credentials not URL-escaped; bare-domain argv confusion
- `052` `done` [ticket-052-persistent-http-sessions.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-052-persistent-http-sessions.md) — **P1:** aiohttp/curl_cffi create a new session per request — no keep-alive, TLS handshake every fetch
- `053` `done` [ticket-053-curl-cffi-impersonation.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-053-curl-cffi-impersonation.md) — **P2:** curl_cffi backend never passes `impersonate=` — advertised TLS fingerprinting is not wired
- `054` `done` [ticket-054-streaming-body-cap-content-type-gate.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-054-streaming-body-cap-content-type-gate.md) — **P2:** `max_response_bytes` applied after full read (OOM risk); binaries fully downloaded though never parsed
- `055` `done` [ticket-055-logging-and-persist-error-visibility.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-055-logging-and-persist-error-visibility.md) — **P2:** 51 `print()`s → logging with `--verbose`/`--quiet`; persist failures (`persist_error`) currently invisible in CLI output
- `056` `done` [ticket-056-ci-lint-typecheck.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-056-ci-lint-typecheck.md) — **P2:** no CI, no lint, no typecheck — add GH Actions + ruff + gradual mypy
- `057` `done` [ticket-057-crawl-loop-throughput.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-057-crawl-loop-throughput.md) — **P3:** lock-step batch `gather` head-of-line blocking; N+1 `record_source_by_url` writes during sitemap ingestion

### 2026-06-12 follow-up audit

Re-evaluation after the 049–057 batch (engine scope/memory/CPU hot paths, retry hygiene, ops, CI debt).

- `058` `done` [ticket-058-allowed-hosts-link-discovery.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-058-allowed-hosts-link-discovery.md) — **P1:** `allowed_hosts` is dead config — `extract_links` drops cross-host links before the engine's `is_host_allowed` check can run
- `059` `done` [ticket-059-open-crawl-memory-retention.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-059-open-crawl-memory-retention.md) — **P1:** open crawls hold every page's `raw_html` in RAM for the whole job; `save_to` buffers one giant JSON — drop HTML after persist, stream JSONL
- `060` `done` [ticket-060-single-parse-lxml.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-060-single-parse-lxml.md) — **P2:** each page parsed 2–3× with `html.parser` despite lxml dependency; parse once, use lxml, offload big pages off the event loop
- `061` `done` [ticket-061-crawl-many-continuous-pool.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-061-crawl-many-continuous-pool.md) — **P2:** `crawl_many` (list/CSV mode) still lock-step batches — port the ticket-057 continuous pool
- `062` `done` [ticket-062-retry-results-budget-hygiene.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-062-retry-results-budget-hygiene.md) — **P2:** transient-error retries consume `--max-pages` budget and leave failed attempts in saved results
- `063` `done` [ticket-063-per-host-politeness.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-063-per-host-politeness.md) — **P3:** no per-host concurrency cap — full worker pool can burst a single origin
- `064` `done` [ticket-064-graceful-shutdown.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-064-graceful-shutdown.md) — **P3:** SIGINT/SIGTERM drain: finish in-flight, write partial output, summary + `interrupted` marker instead of a traceback
- `065` `done` [ticket-065-sitemap-ingestion-throughput.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-065-sitemap-ingestion-throughput.md) — **P3:** sitemap shards fetched serially; `_persist_sitemap_hreflang` still N+1 and pokes private store methods
- `066` `done` [ticket-066-ci-hardening.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-066-ci-hardening.md) — **P3:** enforce mypy (currently can't fail), add coverage floor, integration-test `persistence.py` against real Postgres in CI

### 2026-06-12 review of the 058–066 batch

Post-implementation review found two regressions and two completeness gaps.

- `067` `done` [ticket-067-ci-coverage-regression.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-067-ci-coverage-regression.md) — **P0:** coverage floor in `addopts` breaks single-file pytest runs and makes the new integration CI job permanently red
- `068` `done` [ticket-068-jsonl-skipped-results.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-068-jsonl-skipped-results.md) — **P1:** robots-blocked/fetch-error results never written to the JSONL `save_to` file; counts disagree with contents
- `069` `done` [ticket-069-finish-batch-dod-gaps.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-069-finish-batch-dod-gaps.md) — **P2:** unbuilt DoD items: to_thread parse offload (060), `keep_html_in_results` (059), stop-flag drain in `crawl_many` (064); + per-host cap visibility log
- `070` `done` [ticket-070-mypy-persistence.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-070-mypy-persistence.md) — **P2:** remove `persistence.py` from the mypy `ignore_errors` blanket; fix its errors for real

### Cross-repo follow-up

- `071` `done` [ticket-071-wip-js-loop-wiring.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-071-wip-js-loop-wiring.md) — **(PostgreSQLCrawlerWIP repo):** wire the JS/Obscura backend into that repo's BFS crawl loop so `--js`/`--obscura` actually render pages (follow-up to ticket-044). Done 2026-06-14 (commit 01a78ad): use_js threaded through fetch_many_with_delay/fetch_with_delay, JS branch adapts 5-tuple→6-tuple, shared backend torn down once at crawl end. Also fixed a latent `import json` shadowing bug in fetch_with_delay's except block. 3 new routing tests; 32 total pass.

### Hard-site crawling (proxies + anti-bot), 2026-06-15

Driven by the casino.org/Cloudflare investigation: make crawler_cli a real
proxied hard-site crawler. User uses a residential rotating gateway (primary).

- `072` `done` [ticket-072-gateway-proxy-mode.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-072-gateway-proxy-mode.md) — rotating-gateway proxy mode (single endpoint, IP rotates server-side per request, never evicted, retried on failure); `--proxy-mode gateway|list` (commit 3918431)
- `073` `done` [ticket-073-proxy-browser-backend.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-073-proxy-browser-backend.md) — route the proxy pool (gateway/list) through the Playwright/Obscura backend; managed Obscura `--proxy` falls back to the gateway (commit 3918431)
- `074` `done` [ticket-074-challenge-detect-escalate.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-074-challenge-detect-escalate.md) — bot-challenge detection (Cloudflare/Datadome/PerimeterX/Akamai/Imperva) + escalate HTTP→browser through a fresh IP; blocked pages recorded, not stored as content (commit 1153328)
- `075` `proposed` [ticket-075-casino-guru-review-ingestion.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-075-casino-guru-review-ingestion.md) — ingest Casino Guru reviews from `en-sitemap.xml` into the shared casino dataset, solve access/fetch path first, then cluster and merge into factfiles

### Intent_Overlap integration, 2026-07-04

Bake `/home/user256/GitRepos/Intent_Overlap` (URL intent-overlap / de-canonicalisation
risk finder: sitemap crawl → trafilatura signatures → sentence-transformer embeddings →
hreflang-aware similarity analysis → CSV reports) into crawler_cli, replacing its
standalone SQLite crawler with this engine + Postgres store. Upstream remediation
Sprints 2 AND 3 (IO tickets 108–117) were completed and merged on 2026-07-04 (PRs
#8–#10), so these tickets port the fixed implementations and their tests verbatim —
nothing is "fix during port" anymore (tickets updated accordingly same day).
Order: 076 → 077, 078 in parallel, then 079; 080 independent; 081 last.

**STATUS 2026-07-04: ALL DONE.** Tickets 076–081 implemented, tested, and each
shipped as a stacked PR (#1→#6, base master via `io-integration-base`). User
overrides applied: NO Screaming Frog CSV import (078) and NO `--gsc` join (079)
— 100% crawler-powered. Parity signed off: the port matches upstream v2.1.0
byte-for-byte on casino_org (1221 pairs) and whiskipedia (198 pairs), Jaccard
1.0000. Standalone Intent_Overlap repo marked superseded. Batch reviewed
2026-07-05; three follow-ups filed as 082–084 (see next section). Tickets later
continued through the 2026-07-15 intent-overlap review batch; 110 remains
unused (ticket 110 explicitly out of scope / rejected). Next free number: **117**.
**LANDED ON MASTER 2026-07-05 (ticket 082):** the whole stack is now on `master`
base-first — `io-integration-base` roll-up as PR #7, then 076–081 as PRs #8/#2–#6
in order, 24 base commits kept linear (no history rewrite). Suite green on master
(367 passed / 13 skipped); all `io-integration-base` and 076–081 feature branches
deleted.
**Start here:** [briefs.md](/home/user256/GitRepos/crawler_cli/tickets/briefs.md) — the
handoff brief with cross-instance context, upstream state, anchors, and constraints.

- `076` `done` [ticket-076-intent-signature-extraction.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-076-intent-signature-extraction.md) — **P1:** trafilatura main text + per-site boilerplate stripping + intent signature via upstream's unified `signature_text()`/`signature_hash()` (IO 109/114, fixed upstream)
- `077` `done` [ticket-077-local-embedding-provider.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-077-local-embedding-provider.md) — **P1:** embedding-provider seam: local sentence-transformers (multilingual MiniLM default, normalized float32) alongside OpenAI; hash-gated re-embed skip
- `078` `done` [ticket-078-hreflang-groups-url-identity.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-078-hreflang-groups-url-identity.md) — **P1:** union-find hreflang groups over the three existing hreflang tables + Screaming Frog CSV import, reciprocity issues, URL-variant folding with tracking-param denylist (ports upstream IO-108 fix)
- `079` `done` [ticket-079-intent-overlap-analyse.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-079-intent-overlap-analyse.md) — **P1:** `intent-overlap` subcommand: language-partitioned block-wise cosine pairing, hreflang suppression, clustering + cohesion QC, risk + suggested canonical, GSC join, threshold calibration, six-CSV report set (ports upstream IO-110/111/115/117 fixes)
- `080` `done` [ticket-080-crawl-parity-refresh-ua-map.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-080-crawl-parity-refresh-ua-map.md) — **P2:** crawl parity gaps: `--refresh-days` staleness refetch + `--ua DOMAIN=UA` per-domain user-agent map for portfolio crawls
- `081` `done` [ticket-081-intent-overlap-scale-eval-parity.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-081-intent-overlap-scale-eval-parity.md) — **P2:** ANN scale path (hnswlib, recall-checked), block-wise calibration, ported eval fixture + goldens, parity sign-off vs regenerated casino_org/whiskipedia goldens, retire the standalone repo (ports upstream IO-112/113/116)

### 2026-07-05 review of the 076–081 batch (Intent_Overlap follow-ups)

Review of the shipped Intent_Overlap stack (six stacked PRs #1–#6, all green,
parity signed off). Three items the implementer flagged in the handoff become
follow-up tickets. The per-domain-UA netloc-vs-hostname bug they caught is NOT
ticketed — it was fixed in the stack itself (tickets 080/081).

- `082` `done` (2026-07-05) [ticket-082-io-stack-merge-to-master.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-082-io-stack-merge-to-master.md) — **P1:** landed the stack to `master` base-first — `io-integration-base` (24 commits) merged as its own roll-up PR #7, then 076 (PR #8, retargeted-by-reopen), 077 (#2), 078 (#3), 079 (#4), 080 (#5), 081 (#6) merged in order, each per-ticket diff clean; 24 base commits linear on master, no rebase/history-rewrite. Verified against DoD: suite green on master (367 passed / 13 skipped), all io/076–081 branches deleted. 083-dependency moot (083 done, on master)
- `083` `done` (2026-07-05) [ticket-083-any-widening-typecheck-debt.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-083-any-widening-typecheck-debt.md) — **P2:** retired the `object→Any` typecheck stopgaps (42 `# type: ignore[arg-type]` in `__main__.py` deserializers + `Any`-typed `persistence.py` query rows). Added TypedDicts for the saved-crawl JSON + the seven query-row helpers, retyped three concrete-store consumers, kept `persistence.py` out of the mypy blanket (ticket-070 invariant). `__main__.py` now has zero `type: ignore`; mypy/ruff clean. F821 was `CrawlJobResult` (fixed via TYPE_CHECKING import), covered by existing + two new `_load_saved_crawl` tests. Split out ticket 085 (intent_overlap `store: Any`)
- `084` `done` (2026-07-05) [ticket-084-cli-hygiene-test-env-isolation.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-084-cli-hygiene-test-env-isolation.md) — **P1 (test-only):** `test_cli_hygiene.py` DSN/config tests failed when the shell exports `CRAWLER_CLI_POSTGRES_*` / `PostgreSQLCrawler_*` (as the maintainer's does). Added an autouse `_clear_postgres_env` fixture in `tests/conftest.py` clearing the full DSN family across both prefixes incl. `*_POSTGRES_DSN`; scoped to the DSN family only so `CRAWLER_CLI_TEST_DSN` is untouched. No runtime change. Verified with the vars exported: module 27 passed (was 8 failed), full suite 367 passed / 13 skipped
- `085` `done` (2026-07-05) [ticket-085-intent-overlap-store-typing.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-085-intent-overlap-store-typing.md) — **P3:** finished the ticket-083 consumer typing: `run_intent_overlap` now takes `store: AsyncpgStore` and the analysis pipeline type-checks against the row TypedDicts. Added `AnalysedRow(AnalysisRow, total=False)` (one computed key `excluded`; `total=False` not `NotRequired` because the latter isn't honoured at runtime under `from __future__ import annotations`) + `VariantReportRow`; retyped `compute_exclusion`/`_count_reasons`/`_variant_rows_from_store`/`write_reports` off `dict[str, Any]`; widened `_write_csv` to `Mapping`. No computed keys leak into the DB-column `AnalysisRow`, no new `type: ignore`/`cast`. mypy + ruff clean, suite 367 passed / 13 skipped

### 2026-07-15 full-tool audit follow-ups

Read-only audit of crawl correctness, scope/politeness, persistence semantics,
security, CLI behavior, CI, packaging, and documentation. Implementation order:
086 first; 087–090 next; 091–094 independently; 095 after 086; 096–098 can
proceed independently except where their DoD references earlier behavior.

- `086` `done` (2026-07-15, PR #13) [ticket-086-crawl-run-isolation.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-086-crawl-run-isolation.md) — **P0:** isolate frontier/metadata by crawl run; explicit new-vs-resume semantics so old rows cannot suppress unrelated seeds. Reviewed MERGE+REMEDIATE: P0 fix sound, suite green (393 passed / 19 skipped on merged master), ruff+mypy clean; pg integration tests run separately (need `CRAWLER_CLI_TEST_DSN`). Minor follow-ups filed as ticket 099; run-aware reporting owned by 095
- `087` `done` (2026-07-15, PR #26; leftovers → 114) [ticket-087-sitemap-scope-budget-politeness.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-087-sitemap-scope-budget-politeness.md) — **P0:** enforce host scope and run-global budget on sitemap URLs; route sitemap fetches through bounded politeness controls. Reviewed MERGE+REMEDIATE: DoD met; CI green
- `088` `done` (2026-07-15, PR #22) [ticket-088-robots-rfc9309-follow-up.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-088-robots-rfc9309-follow-up.md) — **P0:** fix robots fail-open contradiction, query matching, consecutive UA groups, per-domain UA selection, and proxy routing. Reviewed MERGE: DoD met; format fix landed before merge
- `089` `done` (2026-07-15, PR #24) [ticket-089-challenge-hard-stop-persistence.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-089-challenge-hard-stop-persistence.md) — **P0:** unresolved challenges must not be extracted, persisted as content, linked, or counted as crawled. Reviewed MERGE: DoD met; integration fixture `h2` fixed before merge
- `090` `done` (2026-07-15, PR #12) [ticket-090-safe-default-crawl-bound.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-090-safe-default-crawl-bound.md) — **P1:** restore a finite default open-crawl bound and align config/CLI/docs. Reviewed MERGE: default open crawl now bounded at 200, `--max-pages 0` still explicitly unlimited, fixed-list/CSV uncapped; all DoD met (370 passed). Minor dead-`config.max_pages`-field note → ticket 112 (via 099)
- `091` `done` (2026-07-15, PR #9) [ticket-091-real-digest-auth.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-091-real-digest-auth.md) — **P1:** implement real Digest authentication across supported backends or remove the misleading option. Reviewed MERGE: chose the ticket-permitted removal path — `digest` gone from CLI/type surface, legacy programmatic use fails clearly, no silent Basic downgrade; added `--auth-password-env/-file`. 30 passed
- `092` `done` (2026-07-15, PR #25; leftovers → 115) [ticket-092-persist-failure-exit-policy.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-092-persist-failure-exit-policy.md) — **P1:** terminal persistence failures produce a non-zero automation result and durable/partial output metadata. Reviewed MERGE+REMEDIATE: DoD met; CI green
- `093` `done` [ticket-093-cli-config-numeric-validation.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-093-cli-config-numeric-validation.md) — **P2:** validate numeric and cross-field config at CLI/library boundaries; no raw tracebacks
- `094` `done` (2026-07-15, PR #11) [ticket-094-obscura-installer-verification.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-094-obscura-installer-verification.md) — **P1 security:** checksum/signature verification, safe staged archive extraction, and atomic install. Reviewed MERGE: adversarial security review found no exploitable holes — real-path containment (not string prefix), pre-extraction symlink/hardlink/device rejection, fail-closed digest verify, atomic replace with rollback; 42 passed. Test-coverage hardening + digest cross-check filed as ticket 100
- `095` `in_progress` [ticket-095-run-aware-snapshots-reporting.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-095-run-aware-snapshots-reporting.md) — **P2, depends on 086:** retain per-run snapshots and require deterministic run selection in reports/enrichment — claimed by `agent/ticket-095-run-aware-snapshots-reporting`
- `096` `done` (2026-07-15) [ticket-096-persistence-coverage-gate.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-096-persistence-coverage-gate.md) — **P2:** combine/gate PostgreSQL integration coverage and exercise migrations/concurrency/failure paths
- `097` `done` (2026-07-15, PR #10) [ticket-097-real-playwright-ci-smoke.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-097-real-playwright-ci-smoke.md) — **P2:** install and launch real Chromium in a required CI smoke job. Reviewed MERGE: dedicated `playwright-smoke` job installs `.[test,playwright]` + pinned/cached Chromium with `continue-on-error` removed (hard-fails on broken browser); real JS-rendered end-to-end crawl through `CrawlEngine`, cleanup-on-success/failure asserted; heavy tests marker-gated so local unit runs stay fast. Real browser ran in review (2 passed)
- `098` `done` (2026-07-15) [ticket-098-packaging-docs-release-hygiene.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-098-packaging-docs-release-hygiene.md) — **P3:** fix nonexistent `[api]` extra docs; add license/project metadata/install-matrix/release checks — MIT LICENSE + pyproject metadata; README install matrix; CHANGELOG/RELEASING; CI packaging + extras jobs

### 2026-07-15 PR-review remediation follow-ups

Batch review + merge of the five 2026-07-15 audit PRs (#9–#13, tickets
091/097/094/090/086). All five merged to master (suite green: 393 passed / 19
skipped, ruff + mypy clean). Larger follow-ups already had homes (095 run-aware
reporting, 096 pg coverage gating); these capture the remaining small items.
An unrelated uncommitted bulk-insert deadlock fix found in the working tree was
committed separately (not a ticket).

- `099` `done` (2026-07-15, PR #20; leftovers → 112) [ticket-099-crawl-run-isolation-followups.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-099-crawl-run-isolation-followups.md) — **P2:** drop no-op `--new-run`, `CrawlRunSelectionError` (no broad RuntimeError swallow), remove dead legacy-run backfill SQL, resume mismatch/not-found tests
- `100` `done` (2026-07-15, PR #32) [ticket-100-obscura-installer-test-hardening.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-100-obscura-installer-test-hardening.md) — **P3 security:** ticket-094 test hardening — direct rejection tests for tar symlink/absolute/device/FIFO + zip-symlink members; one-time cross-check confirmed all 5 pinned `v0.1.8` SHA-256 digests match published GitHub release assets (fail-closed verify unchanged)
- `112` `done` (2026-07-15) [ticket-112-run-isolation-hygiene-leftovers.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-112-run-isolation-hygiene-leftovers.md) — **P3:** 099 leftovers — removed dead `CrawlConfig.max_pages`; auth-password guard names supplied source flag; `--resume` plain arg (mutex collapsed)

### Intent-overlap case handling (from thompsons-scotland.co.uk run review, 2026-07-15)

First real single-locale production run (3942 pages) surfaced four classes of
finding the analysis mislabels or handles only incidentally. Evidence and
counts in each ticket; run outputs in `runs/thompsons-scotland-20260715/`.
Merged in dependency order: 101 first, then 102/103/104, then 105. All remain
constrained to crawler-owned evidence.

- `101` `done` (2026-07-15, PR #16) [ticket-101-overlap-pair-relationship-classification.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-101-overlap-pair-relationship-classification.md) — **P1:** pair URL relationships, parent-child risk guidance, cluster relation/canonical policy, and relation counts
- `102` `done` (2026-07-15, PR #15) [ticket-102-parameterised-url-classification.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-102-parameterised-url-classification.md) — **P1:** parameterised URL class, signature-confirmed base folding, missing-canonical action, and default-document normalisation
- `103` `done` (2026-07-15, PR #18; remediation 108) [ticket-103-amp-variant-awareness.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-103-amp-variant-awareness.md) — **P1:** explicit AMP extraction/classification/exclusion, canonical-hygiene report, and optional crawl-budget skip
- `104` `done` (2026-07-15, PR #17; remediation 109→113) [ticket-104-thin-content-vs-duplicate.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-104-thin-content-vs-duplicate.md) — **P1:** signature-thinness classification, reporting, and duplicate-gate policy
- `105` `done` (2026-07-15, PR #14) [ticket-105-time-sequenced-section-policy.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-105-time-sequenced-section-policy.md) — **P2:** opt-in time-sequenced sections with cross-section and thin-content precedence preserved

### Interactive HTML report (2026-07-15)

Webpage rendering of the intent-overlap results: hoverable cluster map with
match-type toggles + the core report data as filterable tables, from a JSON
data export. Land after 101–105 (+108 AMP evidence) so tag fields are stable.

- `106` `done` (2026-07-15, PR #28) [ticket-106-report-data-json-export.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-106-report-data-json-export.md) — **P2:** `--json-report` → `report_data.json` (pages/pairs/clusters + 2D UMAP/PCA coords via `[viz]` extra, crawler-native cluster labels, centroid-similarity metric); the data layer for 107. Unblocked by 108 ✓; schema polish notes in 113
- `107` `done` (2026-07-15) [ticket-107-interactive-html-cluster-report.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-107-interactive-html-cluster-report.md) — **P2, depends on 106:** `render-report` subcommand → single self-contained offline HTML — canvas cluster map (hover/zoom/pin), match-type filter toggles (parent-child, time-sequenced, thin, parameterised, amp...), sortable pages/pairs/clusters tables, URL search

### 2026-07-15 review remediations for tickets 103–104 + CI

- `108` `done` (2026-07-15, PR #23; production recount → 116) [ticket-108-amp-classification-evidence-hardening.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-108-amp-classification-evidence-hardening.md) — **P1, depends on 103:** remove base-exists-only AMP confirmation, use intent-signature evidence, and recompute stale variant labels. Reviewed MERGE: DoD met; CI green
- `109` `done` (2026-07-15, PR #21; leftovers → 113) [ticket-109-thin-content-diagnostic-completeness.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-109-thin-content-diagnostic-completeness.md) — **P2:** `main_text_*` / `signature_chars` diagnostics in `pages.csv`; missing-vs-zero evidence; thin policy unchanged
- `111` `done` (2026-07-15, PR #19) [ticket-111-ci-artifact-action-runtime-hygiene.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-111-ci-artifact-action-runtime-hygiene.md) — **P3:** non-empty coverage artifacts + GitHub actions off deprecated Node 20 runtimes
- `113` `done` (2026-07-15) [ticket-113-thin-diagnostic-schema-calibration.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-113-thin-diagnostic-schema-calibration.md) — **P3:** 109 leftovers — 106 `pages[]` diagnostic length contract + `/videos` calibration (`word_count` 820–1042 vs `main_text_words=52` / `signature_words=77`)

### 2026-07-15 batch review remediations (PRs #22–#26)

Review + merge of tickets **087 / 088 / 089 / 092 / 108** (PRs #26 / #22 / #24 /
#25 / #23). All merged MERGE or MERGE+REMEDIATE; none rejected.

- `114` `proposed` [ticket-114-sitemap-budget-dedupe-cdn-docs.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-114-sitemap-budget-dedupe-cdn-docs.md) — **P2:** 087 leftovers — dedupe sitemap locs against frontier budget + document cross-host `Sitemap:` allowlisting
- `115` `proposed` [ticket-115-persist-frontier-incompleteness-signaling.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-115-persist-frontier-incompleteness-signaling.md) — **P2:** 092 leftovers — signal mark-done failure to automation; align crawl-run status with persist incompleteness
- `116` `proposed` [ticket-116-amp-evidence-production-recount.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-116-amp-evidence-production-recount.md) — **P3:** 108 follow-up — fresh thompsons-scotland evidence-backed AMP / missing-canonical counts

### Open work — priority order (2026-07-15)

Implement in this order unless a ticket's dependency blocks it.

**1. Run-aware reporting and verification**

1. **P2** `095` `in_progress` [run-aware snapshots/reporting](./ticket-095-run-aware-snapshots-reporting.md) — depends 086 ✓ — `agent/ticket-095-run-aware-snapshots-reporting`
2. **P2** `096` `done` [persistence coverage gate](./ticket-096-persistence-coverage-gate.md)
3. **P2** `093` `done` [CLI/config numeric validation](./ticket-093-cli-config-numeric-validation.md)
4. **P2** `114` [sitemap budget dedupe / CDN docs](./ticket-114-sitemap-budget-dedupe-cdn-docs.md) — from 087
5. **P2** `115` [persist/frontier incompleteness signaling](./ticket-115-persist-frontier-incompleteness-signaling.md) — from 092
6. **P3** `112` `done` [run-isolation hygiene leftovers](./ticket-112-run-isolation-hygiene-leftovers.md) — from 099
7. **P3** `113` `done` [thin-diagnostic schema/calibration](./ticket-113-thin-diagnostic-schema-calibration.md) — from 109
7. **P3** `116` [AMP evidence production recount](./ticket-116-amp-evidence-production-recount.md) — from 108

**2. Interactive intent-overlap reporting**

9. **P2** `106` `done` [report_data.json export](./ticket-106-report-data-json-export.md) — after 108 ✓ — PR #28
10. **P2** `107` `done` [interactive HTML cluster report](./ticket-107-interactive-html-cluster-report.md) — after 106 PR (same agent)

**3. Lower-priority hardening**

11. **P3** `098` `done` [packaging/docs/release hygiene](./ticket-098-packaging-docs-release-hygiene.md)
12. **P3** `100` `done` [Obscura installer test hardening](./ticket-100-obscura-installer-test-hardening.md)

**Deferred lanes**

12. **deferred** `035` [Redis frontier](./ticket-035-redis-frontier-queue.md) — architectural/infra
13. **proposed** `075` [Casino Guru review ingestion](./ticket-075-casino-guru-review-ingestion.md) — blocked on reliable authorised fetch path
