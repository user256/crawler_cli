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

- [x] Preserve eligible, selected and omitted origin counts and identities in the collection scope.
- [x] Mark a capped collection partial, even when every selected request succeeds.
- [x] Test cap below population, equal to population and unread responses; capped clean evidence must never become Healthy.

## Status

done (Priority: **P1**). Filed by post-merge QA, 2026-10-06; fixed on `fix/postmerge-qa-robots`, 2026-10-07.
Related existing tickets: 370, 409.

Fix: `--ai-governance` deduplicates the seed origins, applies the cap, and writes a structured `population` on the `robots-txt` collection (`eligible_count`, `selected_count`, `omitted_count`, `cap`, and the `eligible`, `selected`, `omitted` and `unread` hosts); the scope string names the omitted and unread hosts too. Coverage is partial whenever any eligible origin is omitted or any selected one is unread. Validation refuses a collection whose `population` counts do not add up or that claims `complete` while omitting eligible items. As defence in depth, the Q96 answerer also treats a population with omitted hosts as incomplete coverage, so a hand-edited bundle cannot reach Healthy either.

Tests: `tests/test_ai_governance_observations.py` covers cap below population (partial, Needs validation), cap equal to population (complete, can be Healthy), duplicate seed hosts, a capped run with an unread selected host (Pending), and the answerer guard. `reproduce.py` key 411 now reports partial coverage and Q96 Needs validation / No (partial).
