# Ticket 428: Dropdowns on every ticket row, and a workbook that reports actual issues only

## Problem

Two changes the user asked for after the ticket 420 live run:

1. **Dropdowns stop at row 26.** The real template
   (`1T9BRLgaFDZ99Lx3q53Av75eZZM32BIJc0nahVPQpGmU`) has Priority and Ticket
   Classification data validation (sourced from `Config!A2:A` and `Config!B2:B`)
   only on `Tickets` rows 6–26. A workbook with more than 21 tickets has no
   dropdown on rows 27+. The template must not be edited.
2. **The workbook reports non-issues.** In the user's words: "only have the
   created document report on actual issues. we shouldn't report non-issues."
   `questions_sheet_tables` writes a Questions tab with all 104 answers
   (Healthy, Pending, Needs validation, No…) and a data tab for every Yes answer,
   including Yes answers that produce no ticket. `audit_sheet_tables`
   (`technical-audit --google-sheets-template`) lists every check and its status
   on Overview (pass, unavailable, partial…) and writes the tested population
   (`verified_evidence`) of passing checks as evidence tabs.

## Tasks and acceptance criteria

- [x] After writing n tickets, the publisher reads each ticket column's rule
      from the copy's first data row (not hard-coded) and applies it to rows
      6 through 5+n with one `batchUpdate`, one `setDataValidation` per column.
      Rows below the last ticket and the template are not changed. Works on
      both copy paths (`files.copy` and the `copyTo` fallback). The receipt
      lists the ranges. Tests with the fake service.
- [x] `technical-audit-questions`: the workbook holds only answers that produce
      a ticket (`answer["ticket"]`, the gate `question_ticket_rows` uses). The
      Tickets tab is unchanged; the Questions tab keeps its header and columns
      but holds only those rows; data tabs are written only for those answers.
      The `--out` answers JSON is complete and unchanged.
- [x] `technical-audit`: Overview lists the run metadata and only checks with
      affected rows or a ticket; evidence tabs only for checks with affected rows.
      The audit JSON is unchanged.
- [x] README and CLI help updated; tests that asserted the old tab set updated.
- [ ] Live: full-`drive` publish (closes 420 check 1) and a `drive.file`
      publish confirm the dropdown extension and the issue-only tab set.

## Status

open (Priority: **P2**). Filed 2026-10-07 on `fix/ticket-428` (based on
`fix/postmerge-qa-integration` at `adccf49`). Related: 406, 420, 424.
