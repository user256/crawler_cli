# Ticket 112: Crawl-run isolation hygiene leftovers

**Status:** done (2026-07-15, branch `agent/ticket-112-run-isolation-hygiene-leftovers`)
**Priority:** P3 hygiene
**Related:** Tickets 090, 091, 099

## Goal

Close the optional hygiene items that ticket 099 intentionally left out of its
narrowed DoD after the core run-selection follow-ups merged.

## Background

PR #20 (ticket 099) removed the no-op `--new-run` flag, introduced
`CrawlRunSelectionError` so unrelated `RuntimeError`s propagate, dropped the
dead legacy-run backfill SQL, and covered resume mismatch / not-found paths.
Those are the review-blocking items. Two minor notes from the original 099
ticket were not folded in:

## Tasks

- Remove or wire `CrawlConfig.max_pages`. It is set from `--max-pages` in the
  CLI but never read by the engine (only `default_open_crawl_limit` is
  consumed). Either delete the dead field or make the engine the single source
  of truth so the two cannot diverge.
- Fix the password-context guard message so it names the source that was
  actually supplied (`--auth-password` / `--auth-password-env` /
  `--auth-password-file`) instead of always saying `--auth-password requires…`.
- Optional: collapse the now-single-member mutually exclusive argparse group
  around `--resume` into a plain argument.

## Definition of Done

No unused crawl-limit config field remains as a latent trap; auth guard copy
matches the flag that failed; tests cover the wording / config-field behaviour;
ruff + mypy + unit suite green.

## Resolution

- Deleted dead `CrawlConfig.max_pages`; CLI `--max-pages` maps only to
  `default_open_crawl_limit` (engine single source of truth).
- Auth password-context guard names the supplied source flag
  (`--auth-password` / `--auth-password-env` / `--auth-password-file`).
- Collapsed the single-member `--resume` mutually exclusive argparse group into
  a plain argument (resume vs `--crawl-run-id` still validated in `_run_crawl`).
- Tests updated/added for config-field removal and per-source auth wording.
- Validation: ruff + mypy clean; 534 unit tests passed.
