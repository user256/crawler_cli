# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
    remains as an override.
  - New `compare-urls` subcommand: validate a `source_url,target_url` mapping
    CSV — redirect verdict + captured hop chain per pair, content diff, field
    deltas — resolving each side artifact → store → live (`--fetch-missing`),
    with `--output` (CSV/JSON), `--persist`, and `--fail-on` CI gating.
  - `hashing.hamming64()` (consistent with the signed/unsigned BIGINT mapping)
    and redirect-chain capture on `FetchResponse`/`CrawlResult`
    (aiohttp/curl_cffi `history`, Playwright request chain), persisted to
    artifact JSON.

- Compare review hardening (ticket 123): hash-less flag-free compares retain
  their prior behaviour, store-backed remaps can rehash stored HTML, CSV reports
  expose redirect hops, identity mappings are accepted, and CI check failures
  use a distinct exit code.
- Live GUI Chrome profile support (ticket 128): local profile discovery,
  lock/default-directory preflight, persistent Playwright launch wiring, and
  Obscura/profile mutual exclusion.

### Changed

- Packaging metadata, install matrix, license, and release documentation
  (ticket 098).

## [0.1.0] - 2026-07-15

### Added

- Initial public packaging baseline for the reusable `crawler-cli` module:
  async crawl engine, extraction, sitemap parsing, robots-aware fetch control,
  Playwright/Obscura backends, PostgreSQL persistence, and intent-overlap
  analysis extras.
