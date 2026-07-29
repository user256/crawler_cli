# Portal integration contract — crawler-cli 0.2.2

**Status:** release-preparation contract for 0.2.2 (crawler ticket 130). It is
not an immutable release until the release checklist records the `v0.2.2` tag,
the exact release commit, and the uploaded wheel/sdist SHA-256 values. This
document is the single reference for what the portal Migration Manager (epic
3334) may rely on. Anything not listed here is NOT contract and may change
without notice.

## Base commit

- Release candidate is the dedicated 0.2.2 release-prep PR, based on
  `origin/master` commit **`f074c23`** (the reviewed `portal-url-policy/1`
  hook). The final release commit must be captured in the GitHub Release;
  source branches, mutable refs, and the pre-existing `v0.2.1` tag are not
  valid install pins.
- Release candidate: `[project].version = 0.2.2`; intended install pin
  `crawler-cli==0.2.2`. It becomes a supported immutable pin only after the
  recorded wheel and sdist checksums are attached to the `v0.2.2` release.
- Python `>=3.11`, POSIX. Extras: `playwright` (`playwright>=1.44`), `intent`
  (`trafilatura>=1.8`), `embeddings-local` (`sentence-transformers>=2.2`,
  `numpy>=1.24`); also `ann`, `viz`, `test` (see `pyproject.toml`).

## Versioned output schemas

Machine-readable outputs are stamped with an explicit schema identifier
(ticket 3344). Consumers MUST check it and refuse unknown majors.

| Schema id | Surface | Golden proof |
|---|---|---|
| `crawler-cli/crawl-artifact/1` | saved crawl JSON (`serialize_crawl_job`) | `tests/contract/golden/crawl_artifact.json` |
| `crawler-cli/compare/1` | `compare --output` JSON + stdout summary | `golden/compare_rows.json`, `golden/compare_summary.json` |
| `crawler-cli/compare-urls/1` | `compare-urls --output` JSON/CSV + stdout summary | `golden/compare_urls_rows.json`, `golden/compare_urls_rows.csv`, `golden/compare_urls_summary.json` |

CSV has no in-band version field; its column set
(`__main__.COMPARE_URLS_CSV_COLUMNS`) is frozen under `compare-urls/1` —
columns may be appended, never renamed/removed/reordered. Loaders accept
legacy artifacts without `schema_version`
(`tests/contract/test_crawl_artifact_contract.py`).

## Capability inventory

Each required capability, its implementing code, and the test that proves it.
All paths relative to the repo root.

| Capability | Implementation | Proving tests |
|---|---|---|
| Basic/Bearer auth scope | `src/crawler_cli/auth.py` (`AuthConfig`, `applies_to`, `auth_headers`); per-request wiring in `src/crawler_cli/backends.py` (`_request_headers`, `_basic_auth`) | `tests/test_auth.py`; `tests/contract/test_security_proofs.py::test_domain_scoped_auth_not_sent_to_other_hosts` |
| Credential handling on redirects | aiohttp/curl_cffi native redirect handling (`backends.py` `fetch`) | `tests/test_auth.py::test_{aiohttp,curl_cffi}_basic_auth_not_forwarded_to_cross_origin_redirect`; `tests/contract/test_security_proofs.py` (bearer cross-origin strip; same-origin retention). **Playwright excluded — ticket 129** |
| Secrets out of argv | `--auth-password-env/-file`, `--auth-token-env/-file` (`__main__._resolve_secret_sources`, `_build_auth`); store DSNs from env (`_resolve_store_dsn`, ticket 127); `CRAWLER_CLI_POSTGRES_*` env for the persistence DSN (`_build_dsn`) | `tests/test_auth.py::test_auth_password_env_keeps_secret_out_of_argv`; `tests/contract/test_security_proofs.py` (token env/file); `tests/test_store_dsn_env.py` |
| Secrets out of logs/artifacts | engine/backends never log headers or DSNs; artifacts carry response headers only (`serialization.py`) | `tests/contract/test_security_proofs.py::test_authenticated_crawl_logs_and_artifact_never_contain_secret` |
| Robots handling | `src/crawler_cli/robots.py` (RFC-9309 matcher), `engine.py` (`respect_robots_txt`, `allowed_by_robots`, `skip_reason="robots_txt_disallow"`) | `tests/test_robots_introspection.py`, `tests/test_path_restrictions.py`, `tests/test_engine.py` |
| Redirect-hop capture | `backends.py` (`response.history` for aiohttp/curl_cffi, `_playwright_redirect_chain`); `FetchResponse.redirect_chain` → `CrawlResult.redirect_chain` (`models.py`); persisted to artifact JSON (`serialization.py`) | `tests/test_backends.py`; `tests/contract/test_crawl_artifact_contract.py::test_artifact_round_trips_through_loader`; golden `compare_urls_rows.json` (hop chains per pair) |
| Source→target URL mapping (`compare-urls`) | `src/crawler_cli/compare_urls.py` (CSV parse, `classify_redirect` verdict matrix, `build_pair_rows`, `rows_failing`); CLI wiring `__main__._run_compare_urls` (artifact → store → live resolution; source side matches `requested_url` only) | `tests/test_compare_urls.py`, `tests/test_compare_urls_cli.py`; `tests/contract/test_compare_urls_contract.py` (all 7 verdicts golden-frozen) |
| Host remapping (`--replace`) | `src/crawler_cli/remap.py` (ordered literal FROM=TO; URL+text+re-hash); remap-aware diffing in `comparison.py` | `tests/test_remap.py`, `tests/test_compare_remap.py`; `tests/contract/test_compare_contract.py` |
| Hash inputs + signed/unsigned simhash + `hamming64` | `src/crawler_cli/hashing.py` (`normalize_html_for_hashing`, `sha256_hash`, `simhash64`, `simhash_to_signed/unsigned`, `hamming64`) | `tests/test_hashing.py`, `tests/test_hamming.py`; `tests/contract/test_hashing_contract.py` (algorithm outputs frozen as constants) |
| Content verdicts | `comparison.py` (`content_comparison`: `identical` sha-equal / `near` ≤ threshold, default 4 / `changed` / `missing` one-sided) | `tests/test_comparison_deep.py`; contract goldens (near=1, changed=27 fixtures; signed-vs-unsigned distance 0) |
| Intent signatures / embeddings | `src/crawler_cli/intent_signature.py`, `embeddings.py` (extras `intent` + `embeddings-local`; lazy import with extra-naming errors), `intent_overlap.py` | `tests/test_intent_signature.py`, `tests/test_embeddings.py`, `tests/test_embeddings_local.py`, `tests/test_intent_overlap.py` |
| Persisted-run lookup / store-backed compare sides | `persistence.py` (`AsyncpgStore.resolve_reporting_run_id`, `fetch_pages_for_comparison`); `__main__._load_compare_side`, `_resolve_compare_urls_side` | `tests/test_persistence_integration.py` (requires `CRAWLER_CLI_TEST_DSN`); `tests/test_compare_urls.py` unit paths |
| Output schemas | see table above | `tests/contract/` golden suite |
| Exit-code taxonomy | `src/crawler_cli/exit_codes.py` | `tests/contract/test_exit_code_contract.py`, `tests/test_persist_exit_policy.py` |
| Portal HTTP connection policy | `portal_policy.py`; `crawl --portal-url-policy MODULE:FACTORY`; one-shot aiohttp resolver/connector in `backends.py` | `tests/test_portal_policy_hook.py` (initial URL, redirect, sitemap, DNS pinning, literal-IP mismatch, CLI factory loading) |

## Exit codes (frozen)

| Code | Meaning |
|---|---|
| 0 | success (for `compare-urls` without `--fail-on`, findings still exit 0) |
| 1 | crawl/persistence failure or frontier incompleteness |
| 2 | validation/usage error (bad flags, missing/empty pairs CSV, bad `--replace`, unset `--*-store-env` var) |
| 3 | `--fail-on` findings gate tripped (`compare-urls`, `intent-overlap`); the run itself succeeded |
| 130 | interrupted (SIGINT/SIGTERM); wins over 1 |

## Security guarantees

Proven upstream (aiohttp + curl_cffi backends):

1. **argv hygiene** — every credential (basic password, bearer token, store
   DSNs, persistence DSN) has an env/file invocation path; nothing forces a
   secret into `ps`-visible argv.
2. **Log/artifact hygiene** — a DEBUG-level authenticated crawl emits no
   credential material to logs, stdout/stderr, or saved artifacts (artifacts
   carry response headers only).
3. **Redirect scoping** — Basic and Bearer credentials are stripped on
   cross-origin redirects, retained on same-origin hops, and
   `AuthConfig.domain` keeps them off other hosts entirely.

**Gaps the portal must wrap (guarantees that do NOT live upstream):**

- **SSRF/target authorisation**: crawler-cli fetches whatever URL it is given
  (private ranges, metadata endpoints included) and `--fetch-missing` performs
  live fetches. `--portal-url-policy` can guard only the initial HTTP URL,
  HTTP redirects, and sitemaps; it is opt-in and does not guard browser or
  live-comparison paths. The portal's `url_policy` layer must authorise every
  enabled target path (epic 3334 §risk B3).
- **Inline secrets remain possible**: `--auth-password`, `--auth-token`,
  `--<side>-store DSN` overrides still accept literal secrets. The portal
  worker must always use the env/file forms.
- **Resource limits / timeouts**: process-level wall-clock timeout and
  cancellation are the caller's job (the worker must enforce its own timeout
  and treat 130 as a clean drain).
- **URL-embedded credentials** (`https://user:pass@host/`) are not scrubbed
  from logs/artifacts; the portal must not construct such URLs.

## Portal HTTP policy hook (0.2.2)

`crawl --portal-url-policy MODULE:FACTORY` imports a local, zero-argument
factory. It must return an object with async
`authorize(url, purpose) -> PinnedConnection`. Each authorization returns the
requested hostname and port plus one literal IP address. The aiohttp path
creates a one-shot resolver/connector for that address, so a later DNS lookup
or pooled connection cannot replace the approved destination.

The `policy_capabilities()` report is intentionally narrow:

| Path | 0.2.2 guarded? |
|---|---|
| Initial HTTP URL | Yes |
| HTTP redirect | Yes |
| Sitemap fetch | Yes |
| Browser navigation | No |
| Browser subresource | No |
| Live comparison | No |

Portal must fail closed for every required path whose value is false. The hook
does not accept an FD3 protocol, proxy a browser, or turn browser/live paths
into guarded paths.

## Notes for consumers

- `compare-urls` source-side rows resolve by `requested_url` only; a page that
  merely redirected *to* a source URL never stands in for a crawl of it.
- Store-loaded rows may carry no `raw_html`; verdicts then rely on stored
  hashes, and `--replace` cannot re-hash such rows (open ticket 123 item).
- `simhash` values may appear in either unsigned or signed (PostgreSQL
  BIGINT) form; `hamming64` normalises both — consumers should store what
  they receive and compare via `hamming64`, never raw XOR.
- Golden regeneration (`CONTRACT_GOLDEN_UPDATE=1`) is a contract change and
  must be treated as such in review.
