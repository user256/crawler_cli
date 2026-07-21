# Ticket 122: Site-to-site compare — host remapping, simhash tolerance, and CSV URL-pair / redirect mapping

## Goal
Make the compare tooling usable for the two real-world jobs it is almost —
but not quite — able to do today:

1. **Near-site compare** (e.g. `dev.domain.com` vs `domain.com`, or a local
   build vs production): compare two crawls of "the same site on different
   hosts" by supplying replacement strings, so host-derived differences stop
   drowning out real content changes.
2. **Mapped compare / redirect validation**: compare URL A on one site to
   URL B on another (migration mappings) from a user-supplied CSV, sourcing
   page data from existing crawls where available and fetching fresh where
   not, and validating that each source URL actually redirects to its mapped
   target.

Both jobs lean on the content-hashing layer (`hashing.py`) that the crawler
already computes and persists for every page.

## Background — current state (evidence, 2026-07-16)

- `compare` CLI (`__main__.py` `_run_compare`) diffs two **saved crawl JSON
  artifacts** via `comparison.compare_deep()`. Rows are keyed by URL **path**
  (`comparison._path_of`), so two hosts already line up on shared paths —
  the near-site case is structurally half-done.
- **Content equality is sha256-exact only** (`comparison.py:151`).
  `content_hash_simhash` is computed at fetch time (`engine.py:325`),
  persisted to Postgres (`content.content_hash_simhash BIGINT`) and to JSON
  artifacts, but **no code anywhere computes a hamming distance** — the
  near-duplicate half of the hashing solution is write-only today.
- `normalize_html_for_hashing()` strips tags/scripts and hashes visible text
  only, so differing hosts inside `href` attributes do *not* break the sha256.
  What does break it: staging banners, host names mentioned in visible text,
  cookie/consent variants, environment footers — exactly what a dev site has.
- **Canonical and discovered-link diffs compare absolute URLs**,
  (~~hreflang~~ — **scope correction, ticket 123**: no hreflang comparison exists
  anywhere in the compare path; this background line overstated the state.)
  so in a dev-vs-prod compare *every* page reports a canonical change
  (dev canonical → dev host) and every link diff is noise.
- **Redirect data is thin**: `CrawlResult` has only `requested_url` /
  `final_url` / final `status`. Backends follow redirects internally
  (`backends.py:270,379`) and the aiohttp `response.history` is discarded, so
  hop count, intermediate URLs, and per-hop status (301 vs 302) are not
  available. `compare_deep`'s `url_moves` only derives moves *within* the
  baseline crawl.
- **List crawling exists**: `crawl --csv-file … --csv-column url` →
  `engine.crawl_list()`; robots, throttling, backends all apply. So "crawl
  exactly these URLs" needs no new engine work.
- **Store-side compare persistence exists** (`persist_comparison_session`,
  comparison views, `reports.comparison_summary`), but compare inputs can only
  be JSON artifacts — there is no way to pull an existing Postgres crawl (one
  DB per site, per local convention) into a compare without re-exporting.

## Design decisions

1. **Remap at compare time, not crawl time.** Crawl each side as-is; apply an
   ordered list of literal replacements (`--replace FROM=TO`, repeatable) when
   diffing. This keeps artifacts truthful, works retroactively on existing
   crawls, and lets one crawl serve multiple compares. Replacements apply to:
   - normalized text *before re-hashing* (recompute sha256 + simhash from
     `raw_html` when present, else `extracted.text`; stored hashes were
     computed without replacements so they cannot be reused when `--replace`
     is given);
   - canonical / link URLs before equality diffs (~~hreflang~~ — struck per
     ticket 123: there is no hreflang diff to remap);
   - path keying, so path-level renames (e.g. `/en/…=/…`) can align too.
2. **Use simhash for tolerance, not just storage.** Add `hamming64()` to
   `hashing.py` and report per-row `simhash_distance`, classifying rows as
   `identical` (sha256 equal) / `near` (distance ≤ `--simhash-threshold`,
   default 4) / `changed`. A dev-vs-prod compare then surfaces *material*
   changes instead of a binary mismatch wall.
3. **CSV mapping is a first-class pair list, not a second crawl.** New
   `compare-urls` subcommand takes `--pairs mapping.csv` (columns
   `source_url,target_url`, names overridable). Each side resolves in order:
   saved JSON artifact → Postgres store (new loader) → live fetch
   (`--fetch-missing`, batched through `engine.crawl_list`). Absent
   `--fetch-missing`, unresolvable URLs report `status: not_crawled` rather
   than failing the run.
4. **Redirect validation needs real chains.** Capture redirect hops
   (`[{url, status}, …]`) on `FetchResponse`/`CrawlResult` — aiohttp via
   `response.history`; Playwright via the request redirect chain. Per pair,
   fetch `source_url` live and verdict it: `redirect_ok` (final URL ==
   normalized target), `redirect_wrong_target`, `redirect_temporary` (302/307
   in chain), `redirect_chain` (>1 hop), `no_redirect`, `error_status`.

## Tasks

### A. Shared plumbing
- `hashing.hamming64(a, b) -> int`; must be consistent with
  `simhash_to_unsigned` for values loaded from Postgres. Unit tests including
  the high-bit/sign-mapping edge (see [[crawl-content-hashing-bug]] history).
- A small `Remap` helper (ordered literal `FROM=TO` replacements; fail fast on
  a malformed spec) with `apply_to_text()` / `apply_to_url()`, plus a
  re-hash-from-artifact helper (raw_html → normalize → replace → sha256 +
  simhash64).
- Store loader `fetch_pages_for_comparison(urls | run_id)` reconstructing
  comparison-grade rows (final_url, status, title, h1, meta description,
  word_count, canonical, hashes) from the pages/content tables, so existing
  Postgres crawls are usable as either side of a compare.

### B. Near-site compare (`compare` extensions)
- `--replace FROM=TO` (repeatable, ordered) and `--simhash-threshold N`.
- `compare_deep()` accepts the remap + threshold: remap-aware path keying and
  canonical/link diffs (~~hreflang~~ — struck per ticket 123); per-row `simhash_distance` and
  `content_verdict` (`identical|near|changed|missing`).
- Allow either side of `compare` to come from the store
  (`--baseline-store`/`--candidate-store` + run selector) using the A-loader,
  not just JSON paths.
- Summary output and `comparison_rows()` gain the new fields;
  `persist_comparison_session` schema extended accordingly.
- Docs: worked example — crawl `dev.domain` and `domain`, compare with
  `--replace 'dev.domain.com=domain.com' --replace 'https://dev.=https://'`.

### C. CSV pair compare + redirect validation (`compare-urls`)
- Parse `--pairs mapping.csv` (`--source-column`/`--target-column`
  overrides); reject rows with empty/duplicate sources, report count skipped.
- Resolution precedence per side: artifact → store → `--fetch-missing` live
  crawl (single batched `crawl_list` per side, not per-row fetches).
- Redirect-chain capture on `FetchResponse`/`CrawlResult` (aiohttp
  `response.history`; Playwright redirect chain) — persisted to artifact JSON;
  Postgres persistence of hops may be deferred to a follow-up, but the
  compare-urls report must include them.
- Per-pair output row: source/target URLs, both statuses, redirect verdict +
  chain, `sha256_equal`, `simhash_distance`, `content_verdict`, field deltas
  (title/h1/meta/word_count), `note` passthrough column if present.
- `--output` CSV/JSON, `--persist` via comparison sessions, and `--fail-on`
  (`redirect_mismatch`, `content_changed`, `any`) returning a non-zero exit
  code for CI use.
- Docs: worked migration example (old-site crawl in store + fresh target
  fetch + redirect validation in one run).

### D. Tests
- Unit: hamming64, Remap application (text/url/ordering), rehash helper,
  redirect verdict matrix (ok / wrong target / 302 / chain / none / 4xx),
  CSV parsing edge cases.
- Integration-style: compare two fixture crawls differing only by host +
  banner → zero `changed` rows with the right `--replace`, N `near` rows at
  distance ≤ threshold; compare-urls fixture mapping with a mock redirect
  chain.
- Report-shape tests for the new row fields (JSON + persisted session).

## Definition of Done
- `compare --replace … --simhash-threshold …` on a dev-vs-prod style fixture
  pair produces a diff with no host-derived false positives; canonical/link
  noise gone; `content_verdict` present on every row.
- `compare-urls --pairs mapping.csv --fetch-missing --fail-on redirect_mismatch`
  works end-to-end against a real pair of sites (record the run used as
  evidence); non-zero exit on a deliberate bad mapping.
- Existing `compare` behaviour unchanged when no new flags are passed
  (including persisted-session schema compatibility for old sessions).
- ruff / mypy / tests green; README + CHANGELOG updated.

## Constraints
- No new heavyweight deps — hamming distance is `int.bit_count()` on XOR.
- Replacements are **literal strings, applied in order** — no regex in v1
  (document this; regex can be a follow-up flag).
- Live fetching in `compare-urls` goes through the existing engine (robots,
  throttle, backend selection) — no side-channel HTTP client.
- Don't mutate engine config in-place when toggling redirect following
  (`probes.py:26-28` shows the existing anti-pattern to avoid).

## Status
done (2026-07-17) — PR #47 reviewed and merged to master (MERGE+REMEDIATE).

### Review outcome (2026-07-17)
- Two review bugs fixed on the branch pre-merge (commit 67d8ebf), with 4
  regression tests:
  - `normalize_url_for_match` treated a bare host and its `/` root as
    different paths, so a correct root mapping (`https://host` target vs
    `https://host/` final URL) verdicted `redirect_wrong_target`, and a
    chainless client-normalized root fetch read as a redirect.
  - `_resolve_compare_urls_side` indexed results by `final_url` too, so in a
    chained mapping (A→B, B→C) pair B→C could resolve to the A result that
    merely redirected to B. Source side now matches `requested_url` only;
    target side keeps the `final_url` fallback.
- Store-loader blocker cleared: the DSN-gated
  `test_fetch_pages_for_comparison_reconstructs_rows` ran in CI's Postgres job
  and was re-run locally against a real PostgreSQL scratch database (passed).
- Remaining findings (flag-less `compare` hash-recompute behaviour change,
  `--replace` no-op on store-loaded sides, persisted-session test gap, CSV
  hops output, `--fail-on` exit code, identity mappings, artifact-path error
  handling, hreflang-diff scope correction) → ticket 123.
- Final state: suite 680 passed / 41 skipped; ruff + mypy clean; CI fully
  green on merge.

### Delivery notes
- **A:** `hashing.hamming64()` (+ `sha256_of_normalized`/`simhash64_of_normalized`
  re-hash primitives), `remap.Remap` (ordered literal `FROM=TO`, `apply_to_text`
  / `apply_to_url`, `rehash`), and `AsyncpgStore.fetch_pages_for_comparison()`.
- **B:** `compare_deep()` takes `remap` + `simhash_threshold`; remap-aware path
  keying and canonical/link diffs; per-row `content_verdict` + `simhash_distance`
  on `comparison_rows()`; `compare --replace/--simhash-threshold/
  --baseline-store/--candidate-store`; comparison-session schema extended
  (`content_verdict`, `simhash_distance`, `ADD COLUMN IF NOT EXISTS` for old DBs).
- **C:** redirect-chain capture on `FetchResponse`/`CrawlResult`
  (aiohttp/curl_cffi `history`, Playwright request chain) → serialized to
  artifacts; `compare_urls.py` (CSV parse, redirect verdict matrix, row build,
  `--fail-on`); `compare-urls` subcommand (artifact→store→live resolution via one
  batched `crawl_list` per side).
- **D:** unit tests (`test_hamming`, `test_remap`, `test_compare_remap`,
  `test_compare_urls`, `test_compare_urls_cli`) + a DSN-gated store-loader
  integration test. ruff + mypy clean; full suite green.

### Evidence
- Near-site: `test_compare_remap` proves zero host-derived false positives with
  `--replace` (canonical/link noise gone), a `near` row at distance ≤ threshold,
  and `content_verdict` on every row.
- Live `compare-urls --fetch-missing --fail-on redirect_mismatch` (2026-07-16)
  against `http://github.com` (→ `https://github.com/`, 301 chain captured →
  `redirect_ok`) and `http://example.com/` (no redirect → `no_redirect`): exit
  code 2 on the deliberate mismatch, real hop chain recorded.
- **Blocker (external):** the store loader path is exercised only by the
  DSN-gated integration test; no PostgreSQL was reachable in the authoring
  environment, so a store-backed compare run must be recorded in CI/review.
