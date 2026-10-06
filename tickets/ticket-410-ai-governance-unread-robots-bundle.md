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

- [ ] Separate record identity (host) from fetch outcome; permit an explicit unknown status with a reason.
- [ ] Retain failed hosts and all successful collections; Q96 must remain Pending or Needs validation for incomplete evidence.
- [ ] Add command-level coverage for timeout, denied destination, challenge, truncated response and mixed successful/failed hosts.

## Status

proposed (Priority: **P1**). Filed by post-merge QA, 2026-10-06.
Related existing tickets: 370, 388, 409. This records a fix request; no product fix has been applied.
