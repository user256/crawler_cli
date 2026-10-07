# Running the database-backed tests

About 52 tests need a real PostgreSQL database. They skip unless
`CRAWLER_CLI_TEST_DSN` is set. CI runs them on every push and pull request in
the `integration` job, against a throwaway `postgres:16` service container.

## Safety rules

These tests empty every crawl table (`TRUNCATE ... CASCADE`) after each test.
One test also creates and drops a database on the same server. A shared server
can hold operator databases, so two guards apply (ticket 422):

1. **Database name prefix.** `tests/conftest.py` stops the whole run with a
   usage error unless the DSN's database name starts with `crawler_cli_test_`.
   It checks the parsed name with `str.startswith`. It never uses SQL `LIKE`,
   because `_` is a wildcard there; that wildcard is how seven operator
   databases were dropped on 2026-06-05.
2. **DDL opt-in.** `test_drop_crawl_database_isolated_from_test_dsn` creates
   and drops the database `crawler_cli_test_drop_probe`, named exactly. It
   skips unless `CRAWLER_CLI_TEST_ALLOW_DATABASE_DDL=1` is set. Only set the
   flag on a server where creating and dropping that one database is
   acceptable, such as a disposable container or CI.

## Local recipe

Use a new scratch database for each run, give it an exact name, and drop
exactly that name afterwards. Never drop databases by pattern.

```sh
DB=crawler_cli_test_$(date +%Y%m%d%H%M%S)   # exact, unique, prefixed
ADMIN="postgresql://USER:PASSWORD@localhost:5432/postgres"

psql "$ADMIN" -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$DB\""

CRAWLER_CLI_TEST_DSN="postgresql://USER:PASSWORD@localhost:5432/$DB" \
  pytest -m integration -rs
# Add CRAWLER_CLI_TEST_ALLOW_DATABASE_DDL=1 to include the drop-probe test.

psql "$ADMIN" -v ON_ERROR_STOP=1 -c "DROP DATABASE \"$DB\""
```

You can also use a disposable container, which matches CI:

```sh
docker run --rm -d --name crawler-cli-test-pg -p 5433:5432 \
  -e POSTGRES_USER=crawler -e POSTGRES_PASSWORD=crawler \
  -e POSTGRES_DB=crawler_cli_test_local postgres:16

CRAWLER_CLI_TEST_DSN=postgresql://crawler:crawler@localhost:5433/crawler_cli_test_local \
CRAWLER_CLI_TEST_ALLOW_DATABASE_DDL=1 \
  pytest -m integration -rs

docker stop crawler-cli-test-pg
```

If a test run is interrupted after the drop-probe test created its database,
remove it by its exact name:
`DROP DATABASE IF EXISTS "crawler_cli_test_drop_probe"`.
