# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
