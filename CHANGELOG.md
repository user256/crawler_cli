# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Speculative URL discovery across static JavaScript, CSS, and render time
  (tickets 155, 156, and 157). `--discover-js-urls` inventories bounded
  URL-like literals from executable inline scripts and same-scope linked
  JavaScript without following them, and `--follow-js-urls` admits only strict
  page-like candidates to an open crawl frontier. `--discover-css-urls` scans
  inline, linked, and bounded `@import` CSS with stylesheet-relative
  resolution, and `--discover-style-attributes` adds style attributes.
  `--render-discover` reuses Playwright or selectively renders link-poor and
  script-heavy HTTP pages, recording hydrated-only anchors and typed browser
  request outcomes under hard cost limits; only `--follow-rendered-links`
  admits hydrated anchors. API, action, and asset candidates always remain
  inventory-only, network observations are never replayed, and a persisted
  per-host cap of 50 outstanding speculative URLs bounds frontier growth.
  Evidence surfaces through the new `report js-url-candidates`,
  `report css-url-candidates`, `report render-url-candidates`, and
  `report render-attempts` outputs and their run-scoped PostgreSQL tables.

### Changed

- **Breaking for artifact consumers:** saved crawl artifacts are stamped
  `crawler-cli/crawl-artifact/4`, carrying the speculative-discovery evidence
  arrays. The terminal budget counters introduced in `/2` are retained.
  Loading stays backward tolerant for earlier stamped artifacts.

### Fixed

- Run-scoped candidate tables no longer violate their `crawl_runs` foreign key
  when a caller persists without `CrawlEngine`, or after
  `truncate_crawl_tables`. The compatibility run row is now created at the top
  of the persist transaction rather than only alongside the page snapshot.

## [0.3.0] - 2026-08-10

### Added

- Run-scoped network budgets for the Portal-guarded aiohttp path (ticket 3685):
  `--max-requests` and `--max-bytes`. Both are rejected by configuration
  validation on any other backend or without a Portal connection policy,
  because no other path can truthfully guard every request. A request slot is
  consumed immediately before each policy-pinned connection, and every body
  read takes a bounded byte lease rather than reserving the full per-response
  ceiling up front.
- Wire, decoded and accounted byte counters on results and run summaries.
  `max_bytes` is charged as `sum(max(response wire bytes, response decoded
  bytes))`, so a compressed response is accounted for what it expands to and a
  decompression bomb cannot outrun the ceiling.
- Typed terminal budget stops. A run that exhausts a budget ends as a clean
  partial crawl with `budget_stop_reason` of `max_requests` or `max_bytes` and
  `crawl_run_status: partial_budget_exhausted`, never as an uncaught error.
- `crawler_cli.runtime_budget.enforcement_capabilities()`, a no-network probe
  declaring which limits this build enforces.
- Brotli decoding on the guarded path. `br` is advertised and decoded under the
  same bounded leases as gzip and deflate. `Brotli>=1.1` is therefore a new
  **declared runtime dependency**, and the guarded request advertises exactly
  `gzip, deflate, br` instead of inheriting whichever codecs happen to be
  importable in the deployment environment.

### Changed

- **Breaking for artifact consumers:** saved crawl artifacts are stamped
  `crawler-cli/crawl-artifact/2`. Consumers pinning the schema string with
  strict equality must accept `/2` before installing this release. Loaders here
  still read legacy artifacts that carry no `schema_version`, but reject a
  stamped unknown one.
- A body stopped by a run budget or a broken transfer encoding is opaque on the
  guarded path: no extraction, link discovery, or content hash from a prefix.
  Unguarded backends are unchanged, including a page clipped at
  `max_response_bytes`.
- robots.txt resolution on the guarded path goes through the same connection
  pinning and budget admission as page, redirect and sitemap fetches, and keeps
  the credential-free header set the legacy robots fetch already used.
- Redirect-target matching normalises percent-encoding spelling per RFC 3986
  section 6.2.2 (ticket 3755), so `%c8%99` matches `%C8%99` and raw non-ASCII
  matches its encoded form.

### Fixed

- `crawl --save-to` accepts bare CSV seed files.
- A missing robots.txt no longer refetches on every URL check: CDN cache
  headers on a 4xx are not treated as robots policy, and `no-cache` or
  `max-age=0` falls back to the session default TTL.

## [0.2.2] - 2026-07-29

### Added

- Portal-managed HTTP connection policy hook (ticket 130): `crawl
  --portal-url-policy MODULE:FACTORY` loads an operator-installed async policy
  that authorizes and pins the initial URL, every HTTP redirect, and sitemap
  fetch to one literal IP address.  The policy capability report deliberately
  leaves browser navigation, browser subresources, and live comparison false;
  callers must keep those paths disabled until they have their own guard.

### Changed

- The Portal integration contract is prepared for the `0.2.2` artifact.  Its
  schemas and existing CLI/output guarantees remain at major version 1; this
  patch adds the opt-in connection-policy seam without changing an unguarded
  crawl's behaviour.

## [0.2.0] - 2026-07-20

### Added

- Site-to-site compare tooling (ticket 122):
  - `compare --replace FROM=TO` (ordered literal host/path remapping) and
    `--simhash-threshold N` for near-site (dev-vs-prod) diffs. Every comparison
    row now carries a `content_verdict` (`identical|near|changed|missing`) and
    `simhash_distance`; canonical/link/path diffs and content re-hashing are
    remap-aware so host-derived differences stop drowning real changes.
  - Either `compare` side can be loaded from a stored PostgreSQL crawl via
    `--baseline-store`/`--candidate-store` (+ run selector), backed by a new
    `AsyncpgStore.fetch_pages_for_comparison()` loader. Per-side DSNs resolve
    from the environment (`CRAWLER_CLI_<SIDE>_POSTGRES_DSN`, or
    `--<side>-store-env VAR` to name any variable) so credentials stay out of
    shell history and the process list; the inline `--<side>-store DSN` flag
    remains as an override (ticket 127).
  - New `compare-urls` subcommand: validate a `source_url,target_url` mapping
    CSV — redirect verdict + captured hop chain per pair, content diff, field
    deltas — resolving each side artifact → store → live (`--fetch-missing`),
    with `--output` (CSV/JSON), `--persist`, and `--fail-on` CI gating.
  - `hashing.hamming64()` (consistent with the signed/unsigned BIGINT mapping)
    and redirect-chain capture on `FetchResponse`/`CrawlResult`
    (aiohttp/curl_cffi `history`, Playwright request chain), persisted to
    artifact JSON.
- Portal integration contract (portal ticket 3344):
  - Versioned output schemas: saved crawl artifacts carry
    `"schema_version": "crawler-cli/crawl-artifact/1"`; `compare` `--output`
    JSON and its stdout summary carry `crawler-cli/compare/1`; `compare-urls`
    `--output` JSON/CSV and its stdout summary carry
    `crawler-cli/compare-urls/1`. The `--output` JSON files are now a
    `{"schema_version": …, "rows": […]}` envelope (previously an unreleased
    bare list). Artifact loaders keep accepting legacy files without the
    field.
  - Golden contract suite (`tests/contract/`, shipped in the sdist) freezing
    JSON/CSV output fields, redirect chains, signed/unsigned simhash BIGINT
    handling and exact hash-algorithm outputs, missing-page verdicts, exit
    policies, and security proofs (argv/log/artifact credential hygiene;
    cross-origin redirect credential stripping with same-origin retention for
    the aiohttp and curl_cffi backends). Contract reference:
    `docs/portal-integration-contract.md`.
  - `--auth-token-env VAR` / `--auth-token-file PATH`: bearer tokens accept
    the same argv-free secret sources as basic-auth passwords.

- Compare review hardening (ticket 123): hash-less flag-free compares retain
  their prior behaviour, store-backed remaps can rehash stored HTML, CSV reports
  expose redirect hops, identity mappings are accepted, and CI check failures
  use a distinct exit code.
- Live GUI Chrome profile support (ticket 128): local profile discovery,
  lock/default-directory preflight, persistent Playwright launch wiring, and
  Obscura/profile mutual exclusion.

### Changed

- `compare-urls --fail-on` findings now exit **3** (`EXIT_FINDINGS`, matching
  `intent-overlap --fail-on`) instead of conflating with the validation/usage
  code 2, so automation can tell a failed gate from a bad invocation. The
  `compare-urls` CSV gains a dedicated `redirect_hops` column and
  `source_final_url` is now always a clean URL (the hop count was previously
  appended to it as text). Both surfaces were unreleased (ticket 122 line).
- Packaging metadata, install matrix, license, and release documentation
  (ticket 098). The sdist now also ships `docs/`.

### Security

- The Playwright backend applies auth as context-wide headers/credentials
  without origin scoping and is excluded from the redirect credential-scoping
  guarantees (upstream ticket 129); dispatch authenticated crawls on the
  aiohttp or curl_cffi backends until it lands.

## [0.1.0] - 2026-07-15

### Added

- Initial public packaging baseline for the reusable `crawler-cli` module:
  async crawl engine, extraction, sitemap parsing, robots-aware fetch control,
  Playwright/Obscura backends, PostgreSQL persistence, and intent-overlap
  analysis extras.
