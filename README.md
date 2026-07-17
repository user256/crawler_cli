# crawler_cli

`crawler_cli` is a reusable async crawler module extracted from `PostgreSQLCrawler` and narrowed into a smaller package for resumable bounded crawling, extraction, sitemap parsing, robots-aware fetch control, and asyncpg persistence.

## What It Does

- Fetch pages with:
  - `aiohttp`
  - `curl_cffi`
  - `playwright`
  - existing CDP-compatible browsers via Playwright, such as Obscura
- Crawl asynchronously with:
  - `asyncio`
  - `Semaphore`-based concurrency control
  - simple per-request rate limiting
  - bounded open crawl from one or more seed URLs
  - resumable PostgreSQL-backed frontier state
  - default robots.txt enforcement
- Extract:
  - HTML title, description, headings, lang, text, word count
  - canonical from HTML
  - `X-Canonical` from HTTP headers
  - robots directives from `<meta name="robots">`
  - `X-Robots-Tag` from HTTP headers
  - hreflang from `Link` headers
  - hreflang from HTML `<link rel="alternate">`
- Parse sitemaps:
  - `sitemap.xml`
  - sitemap indexes
  - `.gz` sitemap files
  - `sitemap.txt`
- Detect CMS platforms:
  - WordPress, Shopify, Drupal, Joomla, Squarespace, Wix
  - Pattern-based detection via headers, meta tags, and content
  - Configurable detection with confidence scoring
- Detect analytics, tag managers, marketing pixels & A/B-test platforms:
  - GTM, GA4, Universal Analytics, Meta Pixel, Adobe Launch/Analytics, Hotjar, Microsoft Clarity, and 20+ more
  - Identifier extraction (container IDs, measurement IDs) for audit reporting
  - Per-page hit list persisted to PostgreSQL for SQL-driven "missing tag" reports
  - `--analytics-detection` to enable; `--analytics-expected-id` to flag missing primary tags
  - **Known limitation**: JS-injected tags (e.g. GTM-loaded pixels) are only visible with the Playwright (`--js`) backend
- Persist normalized crawl data into PostgreSQL with `asyncpg`

## Install

Requires **Python 3.11+**. Supported platforms are POSIX-like (Linux/macOS);
Windows is best-effort. License: MIT (see `LICENSE`).

### Install matrix

| Extra | Command | Provides |
|---|---|---|
| *(base)* | `pip install -e .` | Core crawl/fetch/extract/persist stack |
| `playwright` | `pip install -e ".[playwright]"` | JS rendering via Playwright (then `playwright install chromium`) |
| `intent` | `pip install -e ".[intent]"` | Intent-signature extraction (`trafilatura`) |
| `embeddings-local` | `pip install -e ".[embeddings-local]"` | Local sentence-transformers embeddings (pulls torch) |
| `ann` | `pip install -e ".[ann]"` | Approximate NN pairing for intent-overlap (`hnswlib`) |
| `test` | `pip install -e ".[test]"` | pytest stack for the unit/integration suite |

Common combinations:

```bash
# Base (editable)
pip install -e .

# Playwright support
pip install -e ".[playwright]"
playwright install chromium

# Intent-overlap pipeline (signatures + local embeddings; add ann for --ann)
pip install -e ".[intent,embeddings-local]"
pip install -e ".[intent,embeddings-local,ann]"

# Tests
pip install -e ".[test]"

# Real browser smoke path used by CI
pip install -e ".[test,playwright]"
pytest -m "not playwright_smoke"
pytest --run-playwright-smoke -m playwright_smoke tests/test_playwright_smoke.py
```

There is **no** `[api]` extra. The HTTP API lives in the separate sibling
repository `crawler_api` (checkout alongside this repo and follow that project's
README). See [HTTP API](#http-api).

Release metadata, versioning, and publish steps: [RELEASING.md](./RELEASING.md).
Changelog: [CHANGELOG.md](./CHANGELOG.md).

## GuardGeese Monitoring

`crawler_cli` exposes a small bridge for GuardGeese-style monitoring without running `CrawlEngine`, the CLI, or PostgreSQL persistence:

```python
from crawler_cli import extract_page, fetch_page

response = await fetch_page(
    "https://example.com/health",
    user_agent="GuardGeeseBot/1.0",
    headers={"X-Monitor": "1"},
)
extracted = extract_page(response.text, response.headers, response.url)
```

This boundary is intentional:

- `fetch_page()` and `extract_page()` are the supported integration surface for `guardgeese-worker`
- `AsyncpgStore` and the resumable frontier are for standalone crawl jobs in this repo
- portal MariaDB state and scheduling remain authoritative in `GuardGueeseRedux`, not in `crawler_cli`
- there is no `crawler-cli worker` subcommand in this package unless the architecture changes

For `guardgeese-worker[crawler]`, depend on the base package with `pip install -e ../../crawler_cli`. Add the `playwright` extra only if JS rendering is actually required.

## CLI Usage

The CLI supports multiple subcommands. The default command is `crawl` if you just pass a URL.

### 1. Crawl

```bash
# Basic crawl (plain open crawls default to 200 URLs)
crawler-cli crawl https://www.example.com

# Larger bounded crawl
crawler-cli crawl https://www.example.com --max-pages 500

# Multi-seed crawl across related hosts
crawler-cli https://www.example.com \
  --seed-url https://app.example.com \
  --max-pages 1000

# Explicit unlimited crawl (use with care: follows links and discovered sitemaps)
crawler-cli https://www.example.com --max-pages 0

# Crawl with Playwright (JS), 15 workers, and an archive.org audit
crawler-cli https://www.example.com \
  --max-workers 15 --concurrency 20 --js \
  --max-requests-per-context 50 \
  --memory-high-watermark 85 \
  --archive-org-check --custom-ua "...Googlebot..."

# Attach to an already-running Edge/Chrome launched with --remote-debugging-port
crawler-cli https://www.example.com --playwright-cdp-port 9222

# Crawl with Obscura (managed — starts/stops automatically)
crawler-cli https://www.example.com --obscura

# Crawl with Obscura exposed over CDP (unmanaged — connect to existing instance)
crawler-cli https://www.example.com \
  --obscura --obscura-unmanaged \
  --obscura-host 127.0.0.1 --obscura-port 9222

# Obscura with explicit stealth choice (stealth is on by default when managed)
crawler-cli https://www.example.com --obscura --no-obscura-stealth

# Crawl with analytics detection and expected-ID audit
# Note: when using --obscura with --analytics-detection you must explicitly
# choose --obscura-stealth or --no-obscura-stealth, because stealth blocks
trackers and can produce false "missing tag" findings.
crawler-cli https://www.example.com \
  --analytics-detection \
  --analytics-expected-id GTM-PROD123 \
  --analytics-expected-id G-PROD456 \
  --content-hashing \
  --js

# Skip storing raw HTML (structured fields + optional hashes only)
crawler-cli https://www.example.com --no-store-html --content-hashing

# Crawl with CSV ingestion and HTTP Auth. Use env/file inputs to avoid putting
# passwords in process arguments.
export CRAWLER_AUTH_PASSWORD='secret'
crawler-cli --csv-file urls.csv --auth-type basic --auth-username admin --auth-password-env CRAWLER_AUTH_PASSWORD
```

HTTP authentication supports Basic and Bearer credentials. Digest authentication
is not advertised because the crawler does not perform Digest challenge/nonce
negotiation and will not downgrade Digest credentials to Basic.

Page HTML is **gzip-compressed by default** in `pages.html_compressed`. Use `--no-html-compression` only for debugging. Legacy uncompressed rows can be migrated with `compact-html`.

#### Advanced crawl options

```bash
# Tune the per-host circuit breaker (or disable it). Also via env vars
# CRAWLER_CLI_CB_THRESHOLD / CRAWLER_CLI_CB_RECOVERY_SECONDS / CRAWLER_CLI_CB_ENABLED.
crawler-cli https://example.com --circuit-breaker-threshold 25 --circuit-breaker-recovery-seconds 60
crawler-cli https://example.com --no-circuit-breaker

# Route every backend through a proxy (HTTP or SOCKS); credentials may be
# embedded in the URL or passed separately.
crawler-cli https://example.com --proxy socks5://127.0.0.1:1080 --proxy-auth user:pass

# Inject session cookies to crawl behind a login wall. --cookies-file accepts a
# dev-tools/storageState JSON export or a Netscape cookies.txt.
crawler-cli https://example.com --cookie "session=abc; csrf=xyz"
crawler-cli https://example.com --cookies-file cookies.json

# Raise the per-response byte cap so very large sitemaps parse intact
# (default 25 MB). Some Magento/WooCommerce sitemaps exceed the old 5 MB cap
# and would otherwise be truncated mid-XML and skipped.
crawler-cli https://example.com --max-response-bytes 50000000

# A robots.txt `Sitemap:` may point to a CDN or another host. Cross-host
# sitemap documents and their page locs are rejected by default, so allow the
# known host explicitly (hostnames only; comma-separate more than one).
crawler-cli https://www.example.com --allowed-hosts sitemap-cdn.example.net

# Use --offsite only when intentionally allowing sitemap and page URLs from
# any host rather than maintaining an explicit allowlist.
crawler-cli https://www.example.com --offsite

# JS (Playwright) wait conditions for SPAs that hydrate asynchronously.
crawler-cli https://example.com --js --wait-for-selector "div.app-ready"
crawler-cli https://example.com --js --wait-for-network-idle 8

# Custom data extraction (CSS / XPath / regex) into content.custom_data (JSONB).
crawler-cli https://example.com --extraction-rules rules.json
```

Per-page timing (TTFB + total duration) is recorded automatically in `page_metadata`
for the aiohttp and Playwright backends. `extraction_rules.json` looks like:

```json
{
  "rules": [
    {"name": "price",   "type": "css",   "selector": ".price", "attr": "text"},
    {"name": "sku",     "type": "xpath", "selector": "//*[@id='sku']/text()"},
    {"name": "authors", "type": "css",   "selector": "a.author", "multiple": true},
    {"name": "phone",   "type": "regex", "pattern": "\\+?\\d[\\d ]{7,}\\d"}
  ]
}
```

### 2. Generate Embeddings

Generate vector embeddings for the crawled pages. Two providers:

```bash
# OpenAI (default, unchanged)
crawler-cli generate-embeddings --api-key sk-... --model text-embedding-3-small

# Local sentence-transformers — no API key, multilingual, free to re-run.
# Needs the [embeddings-local] extra. Embeds the intent signature (see below)
# and skips pages whose signature hasn't changed since the last run.
crawler-cli generate-embeddings --provider sentence-transformers --postgres-dsn ...
```

### 2b. Intent-overlap / de-canonicalisation analysis

Find pages competing for the same search intent (a common cause of
de-canonicalisation on large multilingual sites). The pipeline is
**crawl → signatures → embeddings → hreflang groups → analyse**, all backed by
the crawl's Postgres store (ported from the standalone `Intent_Overlap` tool,
which this supersedes):

```bash
# 1. Crawl (optionally compute signatures inline with --intent-signatures)
crawler-cli crawl https://example.com --postgres-dsn ... --intent-signatures

# 1b. Or backfill signatures over an existing crawl (trafilatura main text +
#     boilerplate stripping + a unified content hash so unchanged pages are skipped)
crawler-cli backfill-signatures --postgres-dsn ...

# 2. Embed the signatures locally (multilingual, no API key)
crawler-cli generate-embeddings --provider sentence-transformers --postgres-dsn ...

# 3. Build hreflang alternate groups + resolve URL variants (100% from the
#    crawler's own captured hreflang edges — no external import)
crawler-cli hreflang-groups --postgres-dsn ...

# 4. Analyse: pairwise cosine similarity with hreflang suppression, clustering,
#    de-canonicalisation risk, suggested canonicals, threshold calibration.
crawler-cli intent-overlap --postgres-dsn ... --out ./out
```

`intent-overlap` writes seven CSVs plus `run_manifest.json` to `--out`:
`pages.csv`, `overlap_pairs.csv`, `clusters.csv`, `hreflang_issues.csv`,
`url_variants.csv`, `amp_issues.csv`, `similarity_distribution.csv`.

**Machine-readable JSON (`--json-report`).** Pass `--json-report` to also write
`report_data.json` — a single envelope for interactive viewers (ticket 107) or
any other consumer. Projection uses UMAP when the optional `[viz]` extra is
installed (`pip install "crawler-cli[viz]"` → `umap-learn`); otherwise PCA via
numpy (already required for analysis). Both paths are deterministic given
`--projection-seed` (default `42`). Excluded pages appear without coords.
Above ~50k embedded pages, pairs below `--json-min-similarity` (default:
`--threshold`) are omitted from the JSON to keep file size manageable.

| Top-level key | Contents |
|---|---|
| `version` / `generated_at` | Schema version + UTC timestamp |
| `embedding_model` | Model id used for the vectors |
| `thresholds` | `threshold`, `dup_threshold`, `thin_signature_words` |
| `projection` | `{method, dims, seed}` — `umap`, `pca`, or `trivial`/`none` |
| `off_topic` | Bottom-percentile centroid-similarity cut (`percentile`, `threshold`) |
| `summary` | Same summary block as `run_manifest.json` |
| `pages[]` | url, cluster_id, coords, risk, excluded, url_class, variant_kind, word/signature length diagnostics (`word_count`, `main_text_words`, `main_text_chars`, `signature_words`, `signature_chars`), section, signal_confidence, max_similarity, nearest_url, suggested_canonical, centroid_similarity, off_topic |
| `pairs[]` | url_a/b, similarity, relation, pair_class, thin, sim_percentile |
| `clusters[]` | id, urls, size, suggested_canonical/action, relation/thin/time_sequenced flags, crawler-native `label` (shared path prefix + signature terms — no LLM) |

**Interactive HTML report (`render-report` / `--html-report`).** After a JSON
export exists, render a single self-contained offline HTML file (no CDN, opens
from `file://`):

```bash
crawler-cli render-report --data ./out/report_data.json -o ./out/report.html
# or chain both steps:
crawler-cli intent-overlap --postgres-dsn ... --out ./out --html-report
```

The page includes a canvas cluster map (hover / zoom / pan / pin), match-type
filter toggles (parent-child, sibling, same-/cross-section, time-sequenced,
thin, parameterised, AMP, excluded, off-topic), risk + cluster pickers, URL
search, and sortable pages/pairs/clusters tables. AMP and excluded pages are
hidden by default. Tested target: ~3–5k pages and ~2k pairs stay comfortable on
a laptop; larger runs still open but the map may drop below 60fps. Report HTML
and JSON contain client URLs — keep them in the run `--out` dir (untracked);
do not commit them.

**AMP / page-variant awareness.** AMP variants are classified structurally from
crawler-captured evidence and recorded as `variant_kind='amp'` on the URL
identity. A page is AMP when it is the target of a `<link rel="amphtml">` edge
(authoritative), or when it has an AMP URL shape (`/amp` path tail or `amp=1`
query) confirmed by a canonical pointing at the base page or by equality of the
crawler intent-signature hash with the crawled base. Mere existence of the base
URL is not enough. They are excluded from pairing with an `amp-variant` reason
ranked ahead of `canonicalised-elsewhere`, so an AMP page is reported as AMP
whether or not it declares a canonical (previously an AMP page missing a
canonical leaked into the analysis as duplicate noise). `amp_issues.csv` is the
AMP canonical-hygiene report — AMP pages missing a canonical to their base page,
or canonicalling somewhere else, with the paired base URL and the evidence that
confirmed the classification. The run summary and `run_manifest.json` count
`amp_variants` and `amp_missing_canonical`. Pass `crawl --skip-amp-variants` to
skip enqueuing AMP URL shapes at discovery time and save crawl budget (default
OFF — crawl-and-classify keeps hygiene reporting working).

**Threshold calibration.** `--threshold` (default `0.85`) flags "high intent
overlap"; `--dup-threshold` (default `0.92`) flags "duplicate —
decanonicalisation likely". These are cosine-similarity cut-offs on
**normalised** embeddings and are model-dependent — the defaults are tuned for
`paraphrase-multilingual-MiniLM-L12-v2`. Every run prints where your thresholds
fall on the site's own nearest-neighbour similarity distribution (e.g.
`threshold 0.85 ~ p68`), and `similarity_distribution.csv` lists per-language
percentiles (p50–p99.9) and pair counts at candidate thresholds 0.80–0.95. Use
those to calibrate: if `0.85` sits below ~p50 you will flag too much; pick a
threshold nearer the p90–p95 knee for a new model or corpus.

Useful flags: `--hreflang-mode {suppress,primary-only,off}` (default `suppress`
skips same-group pairs), `--no-lang-split` (compare across languages),
`--linkage {single,complete}`, `--fail-on {duplicate,overlap}` (non-zero exit
for CI — `duplicate` triggers on pages at duplicate risk, `overlap` on any
overlap pair), `--ann` (hnswlib approximate pairing above `--ann-min-pages`,
≥0.99 recall vs exact; needs the `[ann]` extra), and `--time-sequenced-section
PATH_PREFIX` (repeatable — see below).

**Time-sequenced sections (news/blog).** News and blog archives naturally
accumulate semantically-close pages on recurring topics — a monthly "here's
what changed in health & safety law" column, say. That's usually *correct*
editorially, not a decanonicalisation bug: the query deserves freshness (QDF),
so a new post covering last month's topic again is the right outcome, not
something to merge or canonicalise away. The default `duplicate —
decanonicalisation likely` label overstates this. Opt in per section with
repeatable `--time-sequenced-section /news` (path-prefix match on segment
boundaries, e.g. `/news` matches `/news/archived/foo` but not `/newsletter`);
this is explicit opt-in only — the tool does not auto-detect sections from URL
keywords, since only the operator knows their site's structure. Pairs where
**both** URLs fall under the same configured prefix get pair class
`time-sequenced` (see `overlap_pairs.csv`'s `pair_class` column) and the
softer risk label `topical overlap (time-sequenced) — review editorially;
consider hub or internal linking` instead of the duplicate/overlap label;
whole clusters confined to one time-sequenced section get a "suggest
hub/roundup page" `suggested_canonical` in `clusters.csv` instead of a
canonical pick. These pairs/pages are excluded from `--fail-on duplicate`
gating by default but are never silently dropped — `run_manifest.json` and
the summary line report `time_sequenced_pairs`/`time_sequenced_pages` as
their own count. Cross-section pairs (e.g. a news post vs. an evergreen
service page) are unaffected and keep full duplicate/overlap treatment, since
those often are real cannibalisation.

**Thin content vs true duplicates.** Pages whose *signature* text (title + h1
+ meta description + extracted body — the same string that gets embedded)
has fewer than `--thin-signature-words` words (default `88`) carry little
distinguishing content, even when the raw crawled page is long — nav/footer/
player chrome inflates `word_count` without adding anything unique. When a
page's only `>= --dup-threshold` pairings are with other thin pages, its risk
is downgraded from `duplicate — decanonicalisation likely` (which prescribes
canonical/merge) to `thin content — add distinguishing content`; a pair where
only one side is thin keeps the normal duplicate risk on both pages but is
flagged `thin: asymmetric` in `overlap_pairs.csv` so the asymmetry isn't
hidden. `pages.csv` exposes the thin-content diagnostic surface next to
`word_count`: `main_text_words`, `main_text_chars`, `signature_words`,
`signature_chars`, and `signal_confidence` (same fields the ticket-106
`report_data.json` `pages[]` schema must carry). `clusters.csv` gains a
`thin` column, and `--fail-on duplicate` excludes thin-only pairs from the
duplicate count by default (the run summary reports thin page/pair counts
separately, so nothing is hidden). The `88` default came from calibrating
against a real run (thompsons-scotland.co.uk): its `/videos` hub + category
pages all share an *identical* signature (`signature_words=77`,
`signature_chars=545`) and extracted main text (`main_text_words=52`,
`main_text_chars=360`) — title, h1, a generic meta description, and a
site-wide footer disclaimer, no real body text — and pair at cosine 1.0
purely on that boilerplate, despite 820–1042 raw `word_count` each. A naive
40–60 word guess would miss that entirely. Recalibrate per site by comparing
`word_count` against `signature_*` / `main_text_*`: a persistent gap (high
raw count, low diagnostic lengths) is the tell.

Periodic re-runs: `crawl --refresh-days 30` skips URLs fetched successfully
within the window, and `--ua "domain=User Agent"` sets a per-domain User-Agent
(matches subdomains) for portfolio crawls.

### Run snapshots and retention

Each fetch is retained as an immutable page snapshot for its crawl run. The
normalised `pages`/`content` tables remain a convenient latest-state view, but
historical reporting and enrichment read snapshot values. When a database has
multiple runs, these commands require `--crawl-run-id`; they refuse to guess:

```bash
crawler-cli backfill-signatures --postgres-dsn ... --crawl-run-id crawl-20260716-a
crawler-cli generate-embeddings --postgres-dsn ... --crawl-run-id crawl-20260716-a
crawler-cli hreflang-groups --postgres-dsn ... --crawl-run-id crawl-20260716-a
crawler-cli intent-overlap --postgres-dsn ... --crawl-run-id crawl-20260716-a --out ./out
```

Snapshots retain HTML, metadata, extracted content/hashes, indexability,
canonical/hreflang/robots/schema/link/analytics facts, and run-specific
signatures, embeddings, and identity resolution. They consume more storage
than the current-state projection; use `compact-crawl --crawl-run-id RUN_ID`
to purge HTML for one retained run after its downstream analysis is complete.
Deleting a crawl truncates all runs and snapshots together.

### 3. Compare Crawls

Run a deep comparison between two saved crawl JSON files to identify missing URLs, title changes, schema regressions, and link drift:

```bash
crawler-cli compare baseline.json candidate.json --compare-links --persist
```

Either side may instead be pulled from a stored PostgreSQL crawl (one DB per site) rather than a JSON artifact. Keep DSNs in the environment — a DSN passed on the command line lands in shell history and the process list:

```bash
export CRAWLER_CLI_BASELINE_POSTGRES_DSN=postgresql://…/dev_site
export CRAWLER_CLI_CANDIDATE_POSTGRES_DSN=postgresql://…/prod_site

crawler-cli compare --baseline-run crawl-a --candidate-run crawl-b
```

Each side resolves its DSN in precedence order — `--<side>-store DSN` > `--<side>-store-env VAR` > the well-known variable:

| Side | Env var (also accepts the `PostgreSQLCrawler_` prefix) | Point at any var | Inline override |
| --- | --- | --- | --- |
| baseline | `CRAWLER_CLI_BASELINE_POSTGRES_DSN` | `--baseline-store-env VAR` | `--baseline-store DSN` |
| candidate | `CRAWLER_CLI_CANDIDATE_POSTGRES_DSN` | `--candidate-store-env VAR` | `--candidate-store DSN` |
| source (`compare-urls`) | `CRAWLER_CLI_SOURCE_POSTGRES_DSN` | `--source-store-env VAR` | `--source-store DSN` |
| target (`compare-urls`) | `CRAWLER_CLI_TARGET_POSTGRES_DSN` | `--target-store-env VAR` | `--target-store DSN` |

`--<side>-store-env` errors if the named variable is unset or empty, so a typo fails fast instead of silently falling back to a JSON artifact.

#### Near-site compare (dev vs prod)

Comparing two crawls of *the same site on different hosts* — `dev.domain.com` vs `domain.com`, or a local build vs production — otherwise drowns real content changes in host-derived noise (canonical points at the dev host, every internal link differs, a staging banner breaks every content hash). Supply ordered literal `--replace FROM=TO` substitutions (applied to page text before re-hashing, and to canonical/link/path URLs before diffing) so only material changes survive. `--simhash-threshold N` (default 4) classifies each page via Hamming distance on its simhash fingerprint as `identical` / `near` / `changed`:

```bash
crawler-cli crawl https://dev.domain.com --content-hashing --save-to dev.json
crawler-cli crawl https://domain.com     --content-hashing --save-to prod.json

crawler-cli compare dev.json prod.json --compare-links \
    --replace 'dev.domain.com=domain.com' \
    --replace 'https://dev.=https://' \
    --simhash-threshold 4 \
    --output near-site-diff.json
```

Every comparison row carries a `content_verdict` (`identical|near|changed|missing`) and `simhash_distance`; with the right `--replace` list the host-only pages report `identical`, banner-only pages report `near`, and canonical/link noise disappears.

#### Mapped compare / redirect validation (`compare-urls`)

Validate a site migration from a `source_url,target_url` mapping CSV: for each pair, `compare-urls` verdicts whether the source actually redirects to its mapped target and diffs the two pages' content. Page data for each side is resolved in order — saved JSON artifact → PostgreSQL store → live fetch (`--fetch-missing`, a single batched crawl per side through the real engine, so robots/throttle/backend all apply). `--fail-on` returns a non-zero exit code for CI gating.

```bash
# mapping.csv:  source_url,target_url,note
export CRAWLER_CLI_TARGET_POSTGRES_DSN=postgresql://…/prod_site

crawler-cli compare-urls --pairs mapping.csv \
    --target-run crawl-b \
    --fetch-missing \
    --output migration-report.csv \
    --fail-on redirect_mismatch
```

Each row reports both statuses, the redirect verdict (`redirect_ok`, `redirect_wrong_target`, `redirect_temporary`, `redirect_chain`, `no_redirect`, `error_status`, `not_crawled`) and captured hop chain, `sha256_equal` / `simhash_distance` / `content_verdict`, and per-field deltas (title/h1/meta/word_count). `--fail-on` accepts `redirect_mismatch`, `content_changed`, or `any`. Replacements are literal strings applied in order (no regex in v1).

### 4. Storage lifecycle

```bash
# Gzip legacy uncompressed HTML already in the database
crawler-cli compact-html --postgres-dsn ... --dry-run
crawler-cli compact-html --postgres-dsn ... --confirm crawler_db_example

# Wipe a crawl (truncate tables in place, or drop the whole database)
crawler-cli delete-crawl --postgres-dsn ... --dry-run
crawler-cli delete-crawl --postgres-dsn ... --confirm crawler_db_example
crawler-cli delete-crawl --postgres-dsn ... --mode drop-database --confirm crawler_db_example

# Drop one retained run's HTML while retaining its snapshot facts and hashes
crawler-cli compact-crawl --postgres-dsn ... --crawl-run-id crawl-20260716-a --confirm crawler_db_example
```

Run `generate-embeddings` **before** `compact-crawl` if you need vectors — compact removes HTML required for embedding generation.

### 5. Generate a Sitemap

Generate a clean `sitemap.xml` from a completed crawl (indexable, self-canonical, 200-OK URLs). Splits into a sitemap index above 50,000 URLs:

```bash
crawler-cli generate-sitemap --postgres-dsn ... --crawl-run-id crawl-20260716-a -o sitemap.xml --base-url https://example.com
```

Connection to PostgreSQL can be configured via environment variables (`CRAWLER_CLI_POSTGRES_*` or `PostgreSQLCrawler_POSTGRES_*`) or CLI flags (`--postgres-dsn`, `--postgres-host`, etc.). CLI flags override env vars.

## HTTP API

The HTTP API is a **separate project**, `crawler_api`, which depends on `crawler_cli` and
wraps its engine in a Dockerized, token-authenticated FastAPI service. It lives in its own
repository (sibling `crawler_api/` checkout next to this one) and is **not** part of this
package — there is no `pip install '.[api]'` extra here. See that repo's README and tickets
for API endpoints, auth, and deployment.

## Package Layout

```text
src/crawler_cli/
  __init__.py          # public library surface
  __main__.py          # CLI entry (crawler-cli)
  config.py / engine.py / backends.py / models.py
  extract.py / schema.py / custom_extract.py / hashing.py
  robots.py / sitemap.py / sitemap_generate.py
  persistence.py / serialization.py / compression.py
  monitoring.py / archive.py / probes.py / variants.py
  compare_renders.py / comparison.py / reports.py
  embeddings.py / intent_signature.py / intent_overlap.py
  hreflang_groups.py / amp.py / challenge.py
  obscura_install.py / auth.py / cookies.py / csv_urls.py
  circuit_breaker.py / proxy_pool.py / exit_codes.py
  detection/
    cms.py
    analytics.py
tests/                 # shipped in the sdist for install verification
```

## Default Behavior

- `robots.txt` is checked and honored by default (5xx/network unreachable → session disallow per RFC 9309; 4xx → allow-all)
- host `Crawl-delay` is honored when present unless you disable it
- plain `crawler-cli <url>` open crawls are bounded by default at `200` URLs
- unlimited open crawling requires an explicit `--max-pages 0`
- open crawl is expected to use PostgreSQL-backed frontier state so it can resume
- this package is expected to be used by other scripts for:
  - crawling a fixed list of URLs
  - resumable bounded open crawl from a seed set
  - saving crawl output and returning structured results

### Incomplete persistence and resume

Open-crawl JSON/JSONL summaries expose `persist_error_count` and
`frontier_mark_done_error_count`. Either condition records the crawl run as
`complete_with_errors` rather than `complete`; URLs in
`frontier_mark_done_failed_urls` were persisted but remain pending because
frontier bookkeeping failed. Re-run that explicit run with `--resume RUN_ID`
to reset pending URLs and finish the frontier. Mark-done failures return exit
code 1 even with `--allow-persist-failures`, so automation cannot mistake an
incomplete frontier for a completed crawl.

To bypass robots explicitly:

```python
config = CrawlConfig(respect_robots_txt=False)
```

## Basic Crawl Example

```python
import asyncio

from crawler_cli import CrawlConfig, CrawlEngine


async def main() -> None:
    config = CrawlConfig(
        backend="aiohttp",
        max_concurrency=5,
        rate_limit_per_second=2.0,
        user_agent="crawler_cli/0.1",
    )
    engine = CrawlEngine(config)

    result = await engine.crawl("https://example.com")

    print(result.status)
    print(result.final_url)
    print(result.extracted.title if result.extracted else None)
    print(result.extracted.canonical if result.extracted else None)


asyncio.run(main())
```

## Crawl A Defined List

```python
import asyncio

from crawler_cli import AsyncpgStore, CrawlConfig, CrawlEngine


async def main() -> None:
    store = AsyncpgStore("postgresql://crawler_user:secret@localhost:5432/crawler_db")
    await store.initialize()

    engine = CrawlEngine(
        CrawlConfig(
            backend="curl_cffi",
            max_concurrency=10,
            rate_limit_per_second=5.0,
        ),
        store=store,
    )

    job = await engine.crawl_list(
        [
            "https://example.com",
            "https://example.com/about",
            "https://example.com/contact",
        ],
        save_to="output/list-crawl.json",
    )

    for result in job.results:
        print(result.requested_url, result.status)

    await store.close()


asyncio.run(main())
```

## Use Playwright

Use this for pages that need JS rendering.

```python
from crawler_cli import CrawlConfig, CrawlEngine

config = CrawlConfig(
    backend="playwright",
    timeout_seconds=45,
    max_concurrency=2,
    max_requests_per_context=50,
    playwright_network_idle_timeout_seconds=5.0,
    memory_high_watermark_percent=85.0,
    rate_limit_per_second=1.0,
)
engine = CrawlEngine(config)
```

For long JS-enabled crawls, `max_requests_per_context` recycles Playwright contexts before they bloat, and the engine will temporarily reduce batch concurrency if system memory usage crosses `memory_high_watermark_percent`.

### Drive Real Chrome or Edge Profiles

For sites that only behave correctly in a real signed-in browser profile, launch
Playwright against Chrome/Edge directly instead of the bundled Chromium:

```bash
crawler-cli https://example.com \
  --playwright-channel msedge \
  --playwright-user-data-dir "$HOME/.config/microsoft-edge" \
  --playwright-profile-directory "Default"
```

You can also point at an explicit browser binary with
`--playwright-executable-path /path/to/chrome`. When a real user-data dir is
used, `crawler_cli` defaults that Playwright launch to headed mode so the
profile behaves like a normal browser session. If the profile is already open in
another Chrome/Edge process, Chromium may refuse to start because the profile is
locked.

### Attach To Existing Edge Or Chrome

If you already launched a real browser yourself with remote debugging enabled,
`crawler_cli` can attach to it over CDP instead of launching another browser.

```bash
microsoft-edge --remote-debugging-port=9222

crawler-cli https://example.com --playwright-cdp-port 9222
```

Equivalent explicit form:

```bash
crawler-cli https://example.com \
  --playwright-cdp-endpoint http://127.0.0.1:9222
```

Use `--playwright-cdp-host` if the debugging browser is bound somewhere other
than `127.0.0.1`. CDP attach flags are mutually exclusive with `--obscura` and
with the local Playwright launch/profile flags (`--playwright-channel`,
`--playwright-executable-path`, `--playwright-user-data-dir`,
`--playwright-profile-directory`).

## Obscura Browser Backend

`crawler_cli` can use [Obscura](https://github.com/user256/obscura) as its JS rendering backend. Obscura runs as a stealth CDP server that is harder for anti-bot systems to detect.

### Installing the Obscura binary

Obscura is a **native binary**, not a Python dependency, so it can't ship inside the
`crawler_cli` wheel. The easiest way to get it (Playwright-style):

```bash
crawler-cli install-obscura
```

This downloads the prebuilt Obscura release for your OS/architecture from GitHub,
verifies its pinned SHA-256 digest, safely unpacks `obscura` + `obscura-worker`
into `~/.local/share/crawler_cli/obscura/`, and swaps it into place only after the
staged binaries validate. `--obscura` then finds it automatically — no
`--obscura-binary` needed. Pin a supported version with `--obscura-version vX.Y.Z`
or re-fetch with `--force`; unpinned versions fail closed until their release
digests are added to `crawler_cli`.

**Binary resolution order** (first hit wins), so any of these work:

1. `--obscura-binary <path>` (explicit override)
2. `OBSCURA_BINARY` environment variable
3. the `install-obscura` install dir (above)
4. `obscura` on `PATH`
5. a sibling source checkout at `../obscura/target/release/obscura`

If none resolve, `--obscura` fails with a clear "binary not found" error.

**Building from source instead** (Rust toolchain required) — useful for development or
unsupported platforms:

```bash
cd ../obscura            # sibling checkout of github.com/h4ckf0r0day/obscura
cargo build --release    # produces target/release/{obscura,obscura-worker}
ln -sf "$PWD/target/release/obscura"        ~/.local/bin/obscura
ln -sf "$PWD/target/release/obscura-worker" ~/.local/bin/obscura-worker   # needed for multi-worker serve / scrape
```

The Obscura `serve` subcommand must accept `--port`, `--workers`, `--stealth`, and
`--proxy`, and `fetch` must support `--dump`/`--eval`/`--stealth`, which current releases do.

### Managed mode (default)

Pass `--obscura` and `crawler_cli` will start `obscura serve` automatically, connect over CDP, and terminate the process when the crawl finishes:

```bash
crawler-cli https://www.example.com --obscura
```

Stealth is **enabled by default** in managed mode unless you explicitly disable it.

### Unmanaged mode

If you already have `obscura serve` running, pass `--obscura-unmanaged`:

```bash
crawler-cli https://www.example.com --obscura --obscura-unmanaged
```

In unmanaged mode, `crawler_cli` can only report the stealth state if you explicitly supplied `--obscura-stealth` or `--no-obscura-stealth`. Otherwise the connected server is treated as `stealth: unknown` in logs and saved crawl JSON.

### One-shot fetch mode (`--obscura-fetch`)

By default `--obscura` drives a **persistent CDP browser** (`connect_over_cdp` +
`page.goto`). In some sandboxed/headless environments that long-lived CDP session
can hang on connect or navigation. `--obscura-fetch` is a more robust alternative:
each request shells out to the one-shot `obscura fetch` subprocess, which renders
the page in a stealth browser and returns the HTML. No `obscura serve` process or
port is involved.

```bash
# Each page is a separate `obscura fetch` — no persistent CDP, no port.
crawler-cli https://www.example.com --obscura --obscura-fetch
```

Trade-offs:

- **More robust**: no persistent CDP session to hang; a stuck fetch is bounded by
  `--timeout` and killed without wedging the crawl.
- **Safe concurrency**: each fetch is its own process, so `--max-workers` /
  `--per-host-concurrency` > 1 work without the shared-V8-isolate corruption that
  affects concurrent `page.content()` over a single `obscura serve`.
- **Slower per page**: pays a process-spawn per request.
- Sitemaps and other XML/feed/`.txt` URLs are fetched with `obscura fetch --dump
  original` (raw HTTP body); HTML pages use `--eval` to return the rendered DOM and
  final (post-redirect) URL together. HTTP status is reported as `200` on success
  and `0` on fetch failure (Obscura does not surface the raw status code here).

### Stealth policy

| Situation | Effective stealth |
|---|---|
| `--obscura` alone | `enabled` |
| `--obscura --obscura-stealth` | `enabled` (explicit) |
| `--obscura --no-obscura-stealth` | `disabled` (explicit) |
| `--obscura --obscura-unmanaged` | `unknown` unless you also choose an explicit stealth flag |
| `--obscura --analytics-detection` | **Error** — requires explicit `--obscura-stealth` or `--no-obscura-stealth` |

Passing both `--obscura-stealth` and `--no-obscura-stealth` is an error.

Stealth blocks trackers and fingerprinting scripts. That is desirable for resilient crawling, but it can **invalidate analytics audits** because tags may be blocked before they fire. For measurement-focused runs, use `--no-obscura-stealth` or plain `--js` Playwright/Chromium instead.

## Extracted Data Shape

Each crawl returns a `CrawlResult` dataclass. The main fields are:

- `requested_url`
- `final_url`
- `status`
- `headers`
- `content_type`
- `fetch_backend`
- `raw_html`
- `extracted`

`extracted` contains:

- `title`
- `meta_description`
- `meta_robots`
- `x_robots_tag`
- `canonical`
- `x_canonical`
- `hreflang_links`
- `html_lang`
- `headings`
- `text`
- `word_count`
- `metadata`

## Sitemap Example

```python
from crawler_cli import SitemapParser, discover_sitemap_paths

paths = discover_sitemap_paths("https://example.com")
print(paths)

parser = SitemapParser()
document = parser.parse(
    "https://example.com/sitemap.txt",
    b"https://example.com/\nhttps://example.com/about\n",
    "text/plain",
)

print(document.kind)
print([item.loc for item in document.urls])
```

## PostgreSQL Persistence Example

```python
import asyncio

from crawler_cli import AsyncpgStore, CrawlConfig, CrawlEngine


async def main() -> None:
    store = AsyncpgStore("postgresql://crawler_user:secret@localhost:5432/crawler_db")
    await store.initialize()

    engine = CrawlEngine(
        CrawlConfig(backend="aiohttp"),
        store=store,
    )

    await engine.crawl("https://example.com")
    await store.close()


asyncio.run(main())
```

The store initializes and writes the main normalized tables used by the extracted module:

- `urls`
- `pages`
- `content`
- `robots_directives`
- `canonical_urls`
- `hreflang_http_header`
- `hreflang_html_head`
- `hreflang_sitemap`
- `page_metadata`
- `indexability`
- `frontier`
- `crawl_metadata`

## Open Crawl With Upper Limit

```python
import asyncio

from crawler_cli import AsyncpgStore, CrawlConfig, CrawlEngine


async def main() -> None:
    store = AsyncpgStore("postgresql://crawler_user:secret@localhost:5432/crawler_db")
    await store.initialize()

    engine = CrawlEngine(
        CrawlConfig(
            backend="aiohttp",
            max_concurrency=5,
            default_open_crawl_limit=200,
            same_host_only=True,
        ),
        store=store,
    )

    job = await engine.crawl_open(
        ["https://example.com/"],
        max_urls=200,
        save_to="output/open-crawl.json",
    )

    print(job.crawled_count)
    print(job.blocked_count)

    await store.close()


asyncio.run(main())
```

## URL Variant Probes

Test canonicalisation of trailing-slash, suffix, and case variants:

```python
from crawler_cli import generate_variants, probe_variant

variants = generate_variants("https://example.com/about")
for v in variants:
    result = await probe_variant(engine, "https://example.com/about", v)
    print(v.kind, result.verdict)
```

## Render Parity (JS vs No-JS)

```python
from crawler_cli import compare_renders, CrawlConfig

result = await compare_renders(
    "https://example.com/",
    nojs_config=CrawlConfig(backend="aiohttp"),
    js_config=CrawlConfig(backend="playwright"),
)
print(result.verdict)  # ok, nav_js_injected, content_js_only, meta_drift
```

## Soft-404 Detection

```python
from crawler_cli import soft_404_fingerprint

fp = await soft_404_fingerprint(engine, "https://example.com")
print(fp.status, fp.simhash)
```

## Robots.txt Introspection

```python
from crawler_cli import RobotsPolicyCache, CrawlConfig

cache = RobotsPolicyCache(CrawlConfig())
decision = await cache.check("https://example.com/wp-admin/")
print(decision.allowed, decision.matched_rule, decision.matched_user_agent)
```

## Archive.org Audit

```python
from crawler_cli import audit_archive_urls, CrawlConfig

result = await audit_archive_urls("example.com", store, CrawlConfig())
print(len(result.missing_urls), len(result.legacy_issues))
```

## Run Tests

```bash
python -m pytest -q
```
