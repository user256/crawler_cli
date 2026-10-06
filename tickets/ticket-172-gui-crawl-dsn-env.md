# Ticket 172: GUI/crawl DSN credentials off argv

## Goal
Stop the live GUI bridge (and preferred local crawl patterns) from putting
Postgres credentials on the process argv.

## Background (2026-07-22 wiring audit)

Ticket **127** fixed **compare** store DSNs to resolve from the environment.
The main crawl path and GUI still put a full DSN on argv:

- `build_crawl_argv` always appends `--postgres-dsn`, dsn
  (`crawler_gui/server.py`).
- CLI still accepts `--postgres-dsn` / password pieces on the command line
  (`__main__.py`).

Credentials remain visible in `ps`, crash reports, and some logging setups for
the lifetime of every GUI-spawned crawl.

## Tasks
- Prefer spawning with `CRAWLER_CLI_POSTGRES_DSN` (or equivalent) in the child
  environment and omitting argv DSN when the bridge already has the DSN.
- Keep `--postgres-dsn` as an explicit override for one-off CLI use; document
  the safe pattern.
- Test that GUI argv lacks password material when env injection is used.
- Do not weaken loopback-only assumptions of the bridge.

## Definition of Done
- Default GUI crawl spawn does not put the DSN password on argv.
- Safe env pattern documented for local bridge operators.
- Automated test covers the no-secret-on-argv path.

## Status
proposed (Priority: **P2**, security/hygiene) — related to **127**, not
covered; found in 2026-07-22 audit.
