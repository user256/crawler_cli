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

- [x] Carry an explicit denominator unit from each answerer or registry contract; do not assume it equals the finding unit.
- [x] Render the correct unit, with sensible singular/plural wording, in draft tickets and evidence summaries.
- [x] Cover pages, hosts, host-agent policies, links and templates, including an answer whose finding and denominator units differ.

## Status

done (Priority: **P2**). Filed by post-merge QA, 2026-10-06.
Related existing tickets: 263, 250, 399.

Fixed on `fix/postmerge-qa-misc`. `Evidence` and `Answerer` carry a `denominator_unit`; each answer
records it as `denominator_unit`. Contract-check answers take it from a per-check map (pages by
default; documents, content signatures, interaction captures, records otherwise); observed answers
take `templates` when grouped by template, otherwise a per-observation-kind unit (Q63 hosts), and
custom answerers name theirs (Q96 host-agent policies, Q92 forms, Q66 images, Q25 URLs, Q27/Q77
hosts, Q15/Q71 indexable pages, Q91 links, Q88 timed pages, Q44 priority pages). Draft tickets
render both counts with singular/plural wording (`Yes: 1 host, across 1 host tested (100%)`) and
show the share only when the finding and denominator units match. The Questions tab notes start
with `Tested: N <unit>.`; the numeric Tested column is unchanged. A missing unit renders as
`items`, never `pages`. Q63 repro now reads `Yes: 1 host, across 1 host tested (100%) in run qa.`
Regression tests: `tests/test_technical_audit_observed_answers.py` (ticket 416 section) and
`tests/test_technical_audit_questions.py`. Ticket 399's Q88 population calculation is unchanged.
