# Ticket 394: Give Q94 and Q41 rows their own ticket language

## Goal

Fix a defect found in QA of the merged Stream A, B and C technical-audit work on 2026-10-06, before it reaches master.

## Problem

Q94 header/HTML canonical mismatch rows are published with the `indexability-segmentation` / `canonical-declarations` wording ('missing, duplicate or relative canonical'), and Q41 locale-folder mismatch rows with the `hreflang-html-http` wording ('broken or non-reciprocal hreflang'). Both describe a different defect from the rows they carry.

## Evidence

Stream B QA review, defect 4; templates/technical-audit-ticket-language.json entries `canonical-declarations` and `hreflang-html-http`.

## Tasks

- [ ] Add ticket-language entries `html-header-canonical-mismatch` and `locale-path-language-mismatch` in the house style (use the tech-audit-tickets skill).
- [ ] Point Q94 and Q41 `language_check` at them and cover with a render test.

## Definition of Done

- [ ] Published Q94 and Q41 tickets describe the rows they carry.

## Status

proposed (Priority: **P3**). Source: stream integration QA, 2026-10-06.
