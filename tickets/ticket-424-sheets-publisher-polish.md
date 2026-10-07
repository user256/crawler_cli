# Ticket 424: Sheets publisher follow-ups carried over from ticket 223

## Problem

Ticket 406 closed the correctness gaps in the template publisher. Three
usability items from ticket 223 were left out of scope and are recorded here
so they are not lost:

1. Evidence tabs are appended after `Config` instead of being inserted between
   `Tickets` and `Config`, so the workbook reads Tickets, Config, Q15, Q22…
2. Ticket 189's publish receipt and read-back check (re-reading the written
   range and comparing it with what was sent) is not reused by either
   publish path, so a partial write is reported as success.
3. The contract's `priority_values` / `classification_values` are asserted
   against generated tickets but never compared with the template's real
   data-validation sources (see 420 for the one-off live comparison).

## Tasks and acceptance criteria

- [ ] `addSheet` requests for evidence tabs pass an `index` placing them after
      `Tickets` and before `Config`; test with the fake service.
- [ ] After writing, read back `Tickets!B6:I<n>` and each evidence tab's used
      range and fail with a `PublishReceiptError` on any mismatch; return a
      receipt (sheet ID, ranges, row counts) that the CLI prints.
- [ ] Optional `--check-template` reads the template's data-validation rules
      and fails if their sources disagree with the contract.

## Status

proposed (Priority: **P3**). Filed 2026-10-07. Related: 189, 223, 406, 420.
