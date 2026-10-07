# Ticket 422: Make database-backed tests safe to run and run them in CI

## Problem

52 tests skip unless `CRAWLER_CLI_TEST_DSN` is set (38 in
`test_persistence_integration.py`, 12 in `test_persistence_coverage_gate.py`,
one each in `test_intent_overlap_eval.py` and
`test_tls_final_response_identity.py`). CI and the default local run never
exercise them, which is how ticket 418's `UndefinedColumnError` and the
missing `run_url_sources` bulk writes reached master.

Running them locally is also hazardous.
`tests/test_persistence_coverage_gate.py::test_drop_crawl_database_isolated_from_test_dsn`
connects to the DSN's server as admin and runs
`DROP DATABASE IF EXISTS "crawler_cli_drop_probe"` / `CREATE DATABASE` outside
the test database. On a shared server (the local `crawler` instance holds 27
operator databases; see the 2026-06-05 DB-drop incident) that is one typo away
from data loss, and during the 2026-10-07 QA it ran once by accident.

## Tasks and acceptance criteria

- [ ] Gate every statement that creates or drops a database (the drop-probe
      test and any fixture teardown) behind an explicit opt-in such as
      `CRAWLER_CLI_TEST_ALLOW_DATABASE_DDL=1`; without it the test skips with a
      message naming the flag. Database names stay literal; no pattern matches.
- [ ] Add a conftest guard that refuses a `CRAWLER_CLI_TEST_DSN` whose database
      name does not start with `crawler_cli_test_`, so a production DSN cannot
      be used by mistake.
- [ ] Add a PostgreSQL service to the CI workflow with a `crawler_cli_test_ci`
      database and the opt-in flag set, so the 52 tests run on every PR.
- [ ] Document the local recipe (scratch database per run, exact-name drop)
      in `docs/` or the test README.

## Status

proposed (Priority: **P2**). Filed 2026-10-07. Related: 414, 418.
