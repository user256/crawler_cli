# Ticket 416: Preserve denominator units in question-derived tickets

## Goal

Restore the evidence and coverage contract for Q63, Q96 and other non-page populations after PR #118.

## Problem

Client draft descriptions label every denominator as pages, even when the answerer tested hosts, agent-host policies, links or templates.

## Cause and evidence

`question_ticket_rows` hard-codes `across {denominator} pages tested`. The newer answerers use different population units; the existing comment about contract denominators no longer applies to all question evidence.

A Q63 fixture with one host emits `Yes: 1 hosts, across 1 pages tested`. Q96 denominators count tested host-agent policy comparisons. This is separate from ticket 399's Q88 population calculation.

Reproduced on merged master `72629af137e0803aface1f4ce94a9a18ba7f0eb1`.
Run `PYTHONPATH=src python tickets/qa-new-audit-2026-10-06/reproduce.py` from the repository root. See result key `416` in [captured results](./qa-new-audit-2026-10-06/results.json).

## Tasks and acceptance criteria

- [ ] Carry an explicit denominator unit from each answerer or registry contract; do not assume it equals the finding unit.
- [ ] Render the correct unit, with sensible singular/plural wording, in draft tickets and evidence summaries.
- [ ] Cover pages, hosts, host-agent policies, links and templates, including an answer whose finding and denominator units differ.

## Status

proposed (Priority: **P2**). Filed by post-merge QA, 2026-10-06.
Related existing tickets: 263, 250, 399. This records a fix request; no product fix has been applied.
