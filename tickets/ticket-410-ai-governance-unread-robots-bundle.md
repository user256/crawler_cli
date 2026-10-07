# Ticket 410: Keep failed robots fetches as unknown observations

## Goal

Restore the evidence and coverage contract for Q96 after PR #118.

## Problem

An unread robots.txt makes the entire observations command fail instead of retaining unknown coverage. This also discards other successfully collected kinds when flags are combined.

## Cause and evidence

`robots_txt_record(host, None, ...)` emits `status: null`; `validate_observation_bundle` requires a non-null status as an identity field. The command deliberately constructs this row and then `new_bundle` rejects it.

CLI fixture: one seed host, guarded fetch returns None. Actual: exit 2, `collection 1 (robots-txt) record 1: missing status`, no output bundle.

Reproduced on merged master `72629af137e0803aface1f4ce94a9a18ba7f0eb1`.
Run `PYTHONPATH=src python tickets/qa-new-audit-2026-10-06/reproduce.py` from the repository root. See result key `410` in [captured results](./qa-new-audit-2026-10-06/results.json).

## Tasks and acceptance criteria

- [x] Separate record identity (host) from fetch outcome; permit an explicit unknown status with a reason.
- [x] Retain failed hosts and all successful collections; Q96 must remain Pending or Needs validation for incomplete evidence.
- [x] Add command-level coverage for timeout, denied destination, challenge, truncated response and mixed successful/failed hosts.

## Status

done (Priority: **P1**). Filed by post-merge QA, 2026-10-06; fixed on `fix/postmerge-qa-robots`, 2026-10-07.
Related existing tickets: 370, 388, 409.

Fix: `robots-txt` identity is now `host` only. A record states its outcome: an integer `status` (`fetch_outcome: "fetched"`), or `fetch_outcome: "unknown"` with a non-empty `unknown_reason` and null status/body. Validation still refuses a record with no status and no explicit unknown outcome, an unknown record that carries a status or body, and a non-integer status. `CrawlEngine._bounded_fetch_response` takes an optional `on_skip` callback that reports why it returned None (`timeout:<exc>`, `destination_denied:<reason>`, `scope_manifest_denied:<reason>`, `challenge:<kind>`, `truncated:<reason>`, `circuit_breaker_open`, `fetch_error:<exc>`, `no_response`); `--ai-governance` records that reason, keeps the host, marks the collection partial, and the other collections (for example `--tls-probe`) are still written. Q96 counts unknown hosts as untested: all-unknown is Pending, mixed read/unread is Needs validation, never Healthy.

Tests: `tests/test_ai_governance_observations.py` (command-level timeout, denied destination, challenge, truncated, circuit-open and no-reason cases, mixed hosts, validation, engine skip reasons). `reproduce.py` key 410 now writes the bundle with exit 0.
