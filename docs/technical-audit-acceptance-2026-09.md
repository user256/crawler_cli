# Technical audit acceptance evidence — 2026-09

This captures the repository-level verification for ticket 198. Unit and fake-
service tests establish local behavior; they are not substitutes for a live
PostgreSQL crawl store or Google Sheets publication.

## Reproducible checks

From the `crawler_cli` repository root:

| Command | Outcome |
|---|---|
| `uv tool run --from ruff==0.16.6 ruff check src/crawler_cli` | Pass |
| `uv tool run --from ruff==0.16.6 ruff format --check src/ tests/` | Pass; 159 files already formatted |
| `uv tool run --from mypy==2.3.1 mypy src/crawler_cli` | Pass; 63 source files |
| `uv run --frozen --extra test pytest -q tests/test_google_sheets.py tests/test_technical_audit.py tests/test_report_cli.py tests/test_persistence_integration.py` | 58 passed, 36 skipped |
| `uv run --frozen --extra test pytest -q` | 1,488 passed, 58 skipped, 6 deprecation warnings; exit 0 |
| `git diff --check` | Pass |

The focused suite covers audit schema/projection and CLI output, Sheets v2
header/manifest preflight and scalar serialization, plus the PostgreSQL test
module. The full suite includes regressions for directive conflicts, stale
live failures, unknown coverage, link/orphan classification and incomplete
similarity/authority evidence. PostgreSQL integration cases are environment-
gated and skipped when `CRAWLER_CLI_TEST_DSN` is unset.

## Not verified in this environment

- `CRAWLER_CLI_TEST_DSN` was unset for the local command run, so the focused
  local suite skipped PostgreSQL fixtures. GitHub Actions' PostgreSQL
  integration job does configure the test DSN, runs the integration-marked
  suite including the new multi-site/run/partial-page audit regression, and
  passed on PRs #103 and #104. The separate legacy/resume/concurrent checks in
  that module also ran there; these are CI fixture results, not evidence from
  a representative customer crawl store.
- `GOOGLE_DOCS_OAUTH_TOKEN_FILE` and `GOOGLE_APPLICATION_CREDENTIALS` were
  unset, and no disposable template ID was supplied: actual template copying,
  API writes/readback, layout review, stale-tab cleanup, and induced partial-
  failure recovery are unverified. Mocked publisher and v2-contract tests are
  not live publication proof.
- No representative production-like crawl artifact was supplied for a full
  collection-to-replay-to-template-copy trace. Synthetic/fixture tests do not
  establish that end-to-end trace.

Accordingly, local deterministic tests pass, while the live PostgreSQL,
Google Sheets, and representative-audit acceptance items remain open. Do not
describe ticket 198 or the complete audit workflow as fully accepted until
those integrations are exercised and their outcomes appended here.
