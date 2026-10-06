# Ticket 411: Keep capped AI-governance probes below Healthy

## Goal

Restore the evidence and coverage contract for Q96 after PR #118.

## Problem

Limiting the number of probed origins can produce Healthy for the entire run even though some seed hosts were never checked.

## Cause and evidence

`_run_technical_audit_observations` slices seed_origins by ai_governance_max_origins and sets coverage complete whenever fetched records have a status. It never compares the selected count with the eligible origin count.

CLI fixture: two seed hosts, cap 1, fetched host allows all seven declared agents. Actual: one record, complete coverage, Q96 Healthy / No, denominator 7. The omitted host could have the opposite policy.

Reproduced on merged master `72629af137e0803aface1f4ce94a9a18ba7f0eb1`.
Run `PYTHONPATH=src python tickets/qa-new-audit-2026-10-06/reproduce.py` from the repository root. See result key `411` in [captured results](./qa-new-audit-2026-10-06/results.json).

## Tasks and acceptance criteria

- [ ] Preserve eligible, selected and omitted origin counts and identities in the collection scope.
- [ ] Mark a capped collection partial, even when every selected request succeeds.
- [ ] Test cap below population, equal to population and unread responses; capped clean evidence must never become Healthy.

## Status

proposed (Priority: **P1**). Filed by post-merge QA, 2026-10-06.
Related existing tickets: 370, 409. This records a fix request; no product fix has been applied.
