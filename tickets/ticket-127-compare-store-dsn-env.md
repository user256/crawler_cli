# Ticket 127: Compare store DSNs resolve from the environment

## Goal
Stop the per-side compare store DSNs introduced by ticket 122 from having to be
passed as literal credentials on the command line.

## Background (2026-07-17)

Ticket 122 added four flags that each take a full PostgreSQL DSN:
`--baseline-store` / `--candidate-store` (`compare`) and `--source-store` /
`--target-store` (`compare-urls`). A DSN carries credentials, so passing one
inline writes it into shell history and exposes it in the process list
(`ps aux`) for the lifetime of the crawl — which for a live `--fetch-missing`
migration check is not short.

The rest of the codebase already avoids this in two established ways:

- `_build_dsn` reads `CRAWLER_CLI_POSTGRES_DSN` /
  `PostgreSQLCrawler_POSTGRES_DSN` for the main `--postgres-dsn`.
- `_resolve_secret_sources` offers the `--auth-password` /
  `--auth-password-env` / `--auth-password-file` trio for the auth password.

The 122 store flags followed neither, and the README worked examples propagated
the inline habit (`--baseline-store "$DEV_DSN"`).

## Design decisions

1. **Both mechanisms, in a strict precedence chain** — a well-known variable
   per side so CI needs no flags at all, plus an explicit `--<side>-store-env`
   for arbitrary variable names:

   `--<side>-store DSN` > `--<side>-store-env VAR` > `CRAWLER_CLI_<SIDE>_POSTGRES_DSN`

2. **Inline stays as an override**, not deprecated: it is genuinely convenient
   for a local one-off against a throwaway DB, and removing it would break the
   flags 122 just shipped. Precedence (not an error) resolves any combination,
   so a fixed env var in a CI profile can be overridden ad hoc.
3. **Well-known names mirror `_build_dsn`'s prefixes** — both `CRAWLER_CLI_` and
   the legacy `PostgreSQLCrawler_` prefix are accepted, so this reads the same
   way as every other Postgres setting in the tool.
4. **A named-but-unset variable is an error, not a fallback.** `--<side>-store-env
   TYPO` must fail fast; silently degrading to "no store configured" would make
   a compare quietly read a JSON artifact (or nothing) instead of the DB the
   operator asked for.

## Tasks
- `store_dsn_env_vars(side)` + `_resolve_store_dsn(args, side)` implementing the
  precedence chain, tolerant of a minimal `Namespace` (programmatic callers).
- `--baseline-store-env` / `--candidate-store-env` / `--source-store-env` /
  `--target-store-env`; existing `--<side>-store` help points at the env var.
- Add the four `<SIDE>_POSTGRES_DSN` names (both prefixes) to conftest's
  `_POSTGRES_ENV_VARS` isolation list — an exported var would otherwise flip an
  artifact-only compare into a store-backed one mid-test.
- README: lead the store examples with the env-var form; document the
  precedence table and the fail-fast rule.

## Definition of Done
- `compare` / `compare-urls` run store-backed with no DSN on the command line.
- Precedence holds: inline > `--<side>-store-env` > fixed env var; sides are
  independent; unset/empty named variable exits non-zero with a clear message.
- Existing inline `--<side>-store` usage keeps working unchanged.
- ruff / mypy / tests green; README + CHANGELOG updated.

## Status
in-review (2026-07-17) — implemented on `agent/127-compare-store-dsn-env`.
13 unit tests in `tests/test_store_dsn_env.py` cover the precedence chain, both
env prefixes, per-side independence, fail-fast on unset/empty, and the
minimal-Namespace path. Full suite green (711 passed).

Not a ticket-123 item: that ticket owns the correctness findings from the PR #47
review; this is a separate credential-hygiene concern on the same surface, so it
takes the next unreserved number per the queue's ordering rules.
