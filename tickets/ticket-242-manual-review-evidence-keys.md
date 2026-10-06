# Ticket 242: Key manual-review extra evidence by stable IDs, and test the status rules

## Goal

Manual-review questions that need extra evidence must look it up by a stable
key, not by an English sentence, and the register's status rules must be
tested in both directions.

## Background

In `src/crawler_cli/manual_review_questions.py`, `manual_review_answer_register`
checks `supplied.get(extra_key) is True`, where `extra_key` is the prose
description of the evidence. Rewording a description silently breaks the
lookup, and a boolean is a claim, not evidence. Nothing populates
`run_context["manual_review_evidence"]` today. The existing test only asserts
the unavailable set is a superset and never shows a question reaching `pass`.

## Tasks

- Give each question's additional evidence a stable machine key
  (e.g. `per_host_resource_robots`) plus the human description; emit both in
  the register row.
- Accept supplied evidence only as a mapping entry for that key that names an
  evidence reference (e.g. a non-empty `detail_sheet` or `source` string);
  a bare `True` is not enough.
- Tests: Q2/3/6/7/8/9/11 reach `pass` when their controls pass; each status
  precedence (unavailable > finding > partial > pass) is covered; a question
  with extra evidence passes only with a valid evidence entry and stays
  unavailable with `True` or a mistyped key.

## Definition of Done

- Tests above pass; register row shape documented in the module docstring.
- Scope: `src/crawler_cli/manual_review_questions.py`,
  `tests/test_manual_review_questions.py`, and the Manual Review column
  mapping in `src/crawler_cli/google_sheets.py` only if the row shape changes
  (coordinate: ticket 240 owns that file; limit the edit to the Manual Review
  row comprehension).
