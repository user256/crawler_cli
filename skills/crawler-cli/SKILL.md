---
name: crawler-cli
description: Run crawler_cli — an authorised technical-SEO evidence crawler. Use when you need to crawl a site or a fixed URL list, extract canonical/robots/hreflang/schema/analytics signals, persist a resumable crawl into PostgreSQL, print audit reports (orphans, indexability, redirect chains, CWV, analytics coverage), compare two crawls or a migration mapping CSV, compare raw versus rendered HTML, or generate a sitemap from a completed crawl.
---

# crawler_cli — running crawls and reading the evidence

Repo: `/home/user256/GitRepos/crawler_cli` (git, branch work happens here).
Entry point: the `crawler-cli` console script; in-repo use
`/home/user256/GitRepos/crawler_cli/.venv/bin/crawler-cli`.
Full flag reference lives in that repo's `README.md`; this file is the operating guide.

## What it is, and what it will not do

`crawler_cli` is an **evidence crawler for technical SEO**. It does not trust the
CMS: it observes what a site actually serves and compares independent sources of
evidence against each other — HTML against HTTP headers, both against the
sitemaps, one client against a second client, and a raw response against a
rendered one. Where those sources disagree it records the disagreement as a
candidate for manual review rather than asserting a verdict.

It is **not** an evasion crawler and **not** a pentest scanner. Never propose or
build: identity/IP rotation in order to defeat bot management or rate limits,
CAPTCHA or WAF solving, crawling in spite of `Disallow` as the happy path, or
injection / IDOR / credential-stuffing / hidden-admin fuzzing.

The dual-use flags — `--impersonate`, `--obscura-stealth`, `--custom-ua`,
`--ignore-robots`, the proxy flags, and challenge escalation — exist for
authorised measurement of how a CDN or origin treats a browser-like client. A
spoofed search-engine User-Agent tells you only how the site answered *your*
request carrying that string; it is never evidence of how that search engine
treats the site, and must not be reported as if it were.

Use the words "observe", "inventory", "compare", "candidate", "manual review" in
reports and commits. Avoid "bypass", "beat", "exploit", "prove vulnerable".

## Defaults worth knowing before the first run

- `robots.txt` is checked and honoured (5xx or unreachable → session disallow per
  RFC 9309; 4xx → allow-all). Host `Crawl-delay` is honoured when present.
- A bare `crawler-cli <url>` open crawl is **bounded at 200 URLs**. Unlimited
  crawling needs an explicit `--max-pages 0`, which expands aggressively via
  links and discovered sitemaps — only use it deliberately.
- Default concurrency is 15 workers with a per-host cap of 4
  (`--max-workers` / `--concurrency`, `--per-host-concurrency`).
- Page HTML is gzip-compressed in `pages.html_compressed`. `--no-html-compression`
  is for debugging only.
- Per-response cap is 25 MB (`--max-response-bytes`); very large Magento or
  WooCommerce sitemaps need it raised or they truncate mid-XML and are skipped.
- Cross-host sitemap documents are rejected unless the host is allowed with
  `--allowed-hosts` (hostnames only, comma-separated).
- The first positional argument is optional: a bare hostname or URL is routed to
  `crawl`, so `crawler-cli example.com` and `crawler-cli crawl https://example.com`
  are the same run.

## Subcommands

`crawl`, `generate-embeddings`, `backfill-signatures`, `hreflang-groups`,
`intent-overlap`, `render-report`, `report`, `compare`, `compare-urls`,
`compare-renders`, `compact-html`, `delete-crawl`, `compact-crawl`,
`generate-sitemap`, `install-obscura`.

## Crawling

```bash
# Bounded open crawl (defaults to 200 URLs)
crawler-cli crawl https://www.example.com --max-pages 500

# Several hosts in one run
crawler-cli https://www.example.com --seed-url https://app.example.com --max-pages 1000

# A fixed list instead of an open crawl
crawler-cli --csv-file urls.csv --csv-column url

# JS rendering, lab Core Web Vitals, content hashes, saved artifact
crawler-cli https://www.example.com --js --web-vitals --content-hashing \
  --save-to prod.json

# Skip storing raw HTML, keep structured fields and hashes
crawler-cli https://www.example.com --no-store-html --content-hashing
```

Persistence and resume:

```bash
# Named run into PostgreSQL
crawler-cli https://www.example.com --postgres-dsn "$DSN" --crawl-run-id crawl-a

# Resume that exact run — pending rows from other runs are never claimed
crawler-cli https://www.example.com --postgres-dsn "$DSN" --resume crawl-a
```

Open-crawl summaries expose `persist_error_count` and
`frontier_mark_done_error_count`. Either one records the run as
`complete_with_errors`; URLs listed in `frontier_mark_done_failed_urls` were
persisted but are still pending, so re-run with `--resume RUN_ID` to finish the
frontier. `--allow-persist-failures` does not hide failed frontier completion.

A resume whose seed/scope/config fingerprint differs is refused;
`--allow-run-config-mismatch` waives that, but never waives a changed
scope-manifest digest.

Convention across this user's work: **one PostgreSQL database per site**.
DSNs belong in the environment (`CRAWLER_CLI_POSTGRES_*`, or
`--postgres-dsn`/`--postgres-host`/…), not on the command line where they land in
shell history and the process list. CLI flags override env vars.

### Backends

Default is HTTP (`aiohttp`, or `--http-backend curl_cffi`). `--js` switches to
Playwright; `--obscura` uses the Obscura browser and implies `--js`.
`--playwright-cdp-port 9222` attaches to an already-running Chrome/Edge started
with `--remote-debugging-port`. For SPAs, `--wait-for-selector` waits for
hydration before the DOM snapshot.

When combining `--obscura` with `--analytics-detection` you must state
`--obscura-stealth` or `--no-obscura-stealth` explicitly — stealth blocks
trackers and would otherwise manufacture false "missing tag" findings.

### Auth, cookies, proxies

```bash
export CRAWLER_AUTH_PASSWORD='secret'
crawler-cli --csv-file urls.csv --auth-type basic --auth-username admin \
  --auth-password-env CRAWLER_AUTH_PASSWORD
```

Basic and Bearer only (no Digest negotiation, and Digest credentials are never
downgraded to Basic). Prefer `--auth-password-env/--auth-token-env` or the
`-file` variants so secrets stay out of argv. Credentials are stripped on
cross-origin redirects. `--cookie` / `--cookies-file` (storageState JSON or
Netscape cookies.txt) get past a login wall; `--proxy` accepts HTTP or SOCKS.

### Scope manifest

Ordinary SEO crawling needs no manifest. When the declared scope must be
recorded and enforced, `--scope-manifest PATH` takes a
`crawler-cli/scope-manifest/1` JSON document with an authorisation reference,
operator, a mandatory UTC validity window, exact `scheme://host:port` origins
(no wildcards, and a parent domain does not authorise a subdomain), path
prefixes, and methods. One compiled predicate governs seeds, anchors, hreflang
targets, sitemaps and their locs, robots.txt, redirect hops, and probes; a
refusal reports `scope_manifest_denied:<reason>` and no request is made.
`--ignore-robots` requires both `allow_ignore_robots` in the manifest and an
explicit `--confirm-ignore-robots`.

The manifest is the operator's own attestation. It is not proof of legal
permission and does not verify ownership of the target.

## Reading the results

```bash
# Every flag-free report as aligned tables
crawler-cli report --postgres-dsn "$DSN" --crawl-run-id crawl-a

# Specific reports, tuned
crawler-cli report slowest cwv --limit 20 --postgres-dsn "$DSN" --crawl-run-id crawl-a
crawler-cli report hub-pages --min-outlinks 10 --postgres-dsn "$DSN" --crawl-run-id crawl-a
crawler-cli report missing-analytics --vendor ga4 --postgres-dsn "$DSN" --crawl-run-id crawl-a

# Machine-readable
crawler-cli report --format json --out report.json --postgres-dsn "$DSN" --crawl-run-id crawl-a
crawler-cli report --format csv  --out ./reports/ --postgres-dsn "$DSN" --crawl-run-id crawl-a
```

Reports: `orphans`, `indexability`, `redirect-chains`, `hub-pages`, `slowest`,
`cwv` (needs a crawl run with `--web-vitals`), `analytics-inventory`,
`missing-analytics`, `missing-expected-id`, `schema-compatibility`. Passing no
names runs all except `missing-expected-id`, which joins only when
`--expected-id` is given.

Each fetch is kept as an immutable per-run snapshot; `pages`/`content` are the
latest-state view, while historical reporting and enrichment read snapshots.
When a database holds more than one run these commands **require**
`--crawl-run-id` and refuse to guess — that applies to `report`,
`backfill-signatures`, `generate-embeddings`, `hreflang-groups`,
`intent-overlap`, `generate-sitemap`, and `compact-crawl`.

Technical-audit extension reports are `image-issues`,
`internal-link-quality`, `tracking-parameter-links`, `near-duplicates`, and
`internal-authority`. Image evidence is collected on new v8 crawls from `src`,
`srcset`, and `<picture>` candidates; older artifacts load normally but cannot
answer `image-issues`. Near-duplicate analysis requires content hashing and can
be bounded with `--similarity-limit` and tuned with `--simhash-threshold`.

## Comparing

```bash
# Two crawls, artifacts or stored runs
crawler-cli compare baseline.json candidate.json --compare-links --persist

export CRAWLER_CLI_BASELINE_POSTGRES_DSN=postgresql://…/dev_site
export CRAWLER_CLI_CANDIDATE_POSTGRES_DSN=postgresql://…/prod_site
crawler-cli compare --baseline-run crawl-a --candidate-run crawl-b
```

Each side resolves its DSN as `--<side>-store DSN` > `--<side>-store-env VAR` >
the well-known variable (`CRAWLER_CLI_{BASELINE,CANDIDATE,SOURCE,TARGET}_POSTGRES_DSN`).
`--<side>-store-env` errors on an unset variable rather than silently falling
back to a JSON artifact.

**Dev versus prod** comparisons drown in host-derived noise unless remapped.
Supply ordered literal `--replace FROM=TO` substitutions (applied to page text
before re-hashing and to canonical/link/path URLs before diffing);
`--simhash-threshold N` (default 4) classifies each page by Hamming distance on
its simhash as `identical` / `near` / `changed`:

```bash
crawler-cli compare dev.json prod.json --compare-links \
  --replace 'dev.domain.com=domain.com' \
  --replace 'https://dev.=https://' \
  --simhash-threshold 4 --output near-site-diff.json
```

**Migration / redirect validation** from a `source_url,target_url` mapping CSV.
Each side resolves as saved JSON artifact → PostgreSQL store → live fetch with
`--fetch-missing` (one batched crawl per side through the real engine, so robots,
throttling, and backend all still apply):

```bash
crawler-cli compare-urls --pairs mapping.csv --target-run crawl-b --fetch-missing \
  --output migration-report.csv --fail-on redirect_mismatch
```

Rows carry both statuses, a redirect verdict (`redirect_ok`,
`redirect_wrong_target`, `redirect_temporary`, `redirect_chain`, `no_redirect`,
`error_status`, `not_crawled`) with the hop chain, `sha256_equal`,
`simhash_distance`, `content_verdict`, and title/h1/meta/word-count deltas.
`--fail-on` accepts `redirect_mismatch`, `content_changed`, or `any`.

**Raw versus rendered** parity from a single Playwright navigation:
`crawler-cli compare-renders …` — use it when the question is what JavaScript
changes about the served HTML, not what two crawls disagree about.

JSON outputs use versioned envelopes — `crawler-cli/compare-urls/1`,
`crawler-cli/compare/1`, crawl artifacts `crawler-cli/crawl-artifact/8` — frozen
by golden files in `tests/contract/` and documented in
`docs/portal-integration-contract.md`. Treat those shapes as a contract.

## Sitemap and storage lifecycle

```bash
crawler-cli generate-sitemap --postgres-dsn "$DSN" --crawl-run-id crawl-a \
  -o sitemap.xml --base-url https://example.com   # splits into an index above 50k URLs

crawler-cli compact-html   --postgres-dsn "$DSN" --dry-run
crawler-cli compact-crawl  --postgres-dsn "$DSN" --crawl-run-id crawl-a --confirm crawler_db_example
crawler-cli delete-crawl   --postgres-dsn "$DSN" --confirm crawler_db_example
```

Destructive commands take an explicit `--confirm <database name>`; run
`--dry-run` first. Run `generate-embeddings` **before** `compact-crawl` — compact
removes the HTML embeddings need. Deleting a crawl truncates all runs and
snapshots together. Never LIKE-match database names when cleaning up: an earlier
incident dropped seven unrelated operator databases that way, and a re-crawl was
the only repair.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Complete success |
| 1 | Persistence or frontier-bookkeeping incompleteness, or total crawl failure |
| 2 | Validation / usage error (bad args, missing config, run selection) |
| 3 | `--fail-on` findings gate tripped (`compare-urls`, `intent-overlap`) — the run itself succeeded |
| 130 | Interrupted (SIGINT/SIGTERM drain) |

Precedence: interruption beats persistence failure; validation errors are
returned before the crawl runs; findings are only reported after a clean run. So
automation can distinguish "the tool could not do its job" (1/2) from "the job
ran and the data failed the gate" (3).

## Using it as a library

```python
from crawler_cli import AsyncpgStore, CrawlConfig, CrawlEngine

store = AsyncpgStore("postgresql://user:pass@localhost:5432/crawler_db")
await store.initialize()
engine = CrawlEngine(CrawlConfig(backend="aiohttp"), store=store)
result = await engine.crawl("https://example.com")
job = await engine.crawl_open(["https://example.com/"], max_urls=200,
                              save_to="output/open-crawl.json")
await store.close()
```

`result.extracted` carries `canonical`, `x_canonical`, `meta_robots.raw`,
`x_robots_tag.raw`, and `hreflang_links` (each with `hreflang`, `href`, and the
`source` that produced it — HTTP `Link` header, HTML head link, or sitemap
alternate). For monitoring integrations the supported surface is just
`fetch_page()` and `extract_page()`; there is no worker subcommand.

The HTTP API is a separate sibling repository, `crawler_api`, which wraps this
engine in a token-authenticated FastAPI service. There is no `[api]` extra here.

## Practical notes

- Install extras deliberately: base, then `playwright` (plus
  `playwright install chromium`), `intent`, `embeddings-local`, `ann`, `test`.
- Long crawls belong in the background with output to a file; the run id is what
  you need afterwards, so pass `--crawl-run-id` rather than hunting for a
  generated one.
- `-v` exposes frontier, robots, and circuit-breaker detail when a crawl stalls
  or returns fewer URLs than expected; `-q` leaves only warnings and the summary.
- If a crawl returns far fewer pages than the site has, check in this order:
  robots disallow, the 200-URL default cap, a truncated sitemap
  (`--max-response-bytes`), cross-host sitemaps needing `--allowed-hosts`, and
  the per-host circuit breaker.
