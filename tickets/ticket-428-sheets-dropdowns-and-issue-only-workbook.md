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
- [x] Live: full-`drive` publish (closes 420 check 1) and a `drive.file`
      publish confirm the dropdown extension and the issue-only tab set.

## Status

done (Priority: **P2**). Filed and done 2026-10-07 on `fix/ticket-428` (based on
`fix/postmerge-qa-integration` at `adccf49`). Related: 406, 420, 424.

## Completion, 2026-10-07

- **Dropdowns** (`src/crawler_cli/google_sheets.py`). With at least one ticket, the
  publisher reads `dataValidation` on the copy's first data row (`Tickets!B6:I6`) before any
  write. After writing n rows it sends one `batchUpdate` with one `setDataValidation` per
  validated column over rows 6..5+n. The template is never written. Rows past the last
  ticket keep whatever the template had. The `PublishReceipt` gains `dropdowns` (also in
  `as_dict`), and the CLI prints `dropdowns applied to every ticket row: …`.
  `--check-template` is unchanged. It already notes rows without validation.
- **Live defect found and fixed:** `values.clear` on the ticket columns deleted the template's
  own dropdowns on the `files.copy` path (UI-made rules; rules set through the API survive). The
  ticket columns are now cleared with `updateCells` limited to `userEnteredValue`. The fake
  service in the tests reproduces the destructive clear, so a regression fails
  `test_dropdown_extension_leaves_template_rows_below_the_last_ticket_alone`.
- **Questions workbook** (`questions_sheet_tables`). Only answers with `answer["ticket"]` get
  a Questions row and a data tab. Tickets are unchanged. The code that writes the `--out` JSON was not
  touched (a test asserts the answers are unmodified). The live full-drive and drive.file
  runs wrote byte-identical answers files with all 104 answers.
- **Technical-audit workbook** (`audit_sheet_tables`). It did publish non-issues: Overview had
  one row per contract check with its status (pass, unavailable, partial, not_applicable), and
  passing checks with a tested population (`verified_evidence`, for example
  `rendered-robots-links` and `supplied-search-evidence`) got an evidence tab of clean rows.
  Overview now keeps its run-metadata rows and lists only checks with affected rows or a
  ticket. The new `ticketed_check_ids(audit, language)` in `technical_audit_tickets.py` shares
  the ticket gate with `build_ticket_register`, so an unavailable check that raises a
  collection ticket still appears. Evidence tabs are written only for checks with affected
  rows. Audit Log and Tickets are unchanged. The audit JSON keeps every check.
- **Tests:** 6 new (4 dropdown, 1 questions, 1 technical-audit); old tab-set assertions
  updated, including `test_passing_search_and_inventory_checks_publish_no_tested_evidence_tab`.
  The full suite has 2107 passed and 56 skipped (the baseline was 2101 / 56). `ruff check`
  and `ruff format --check` are clean.
- **Live (2026-10-07):** full `drive` and `drive.file` Rainbet publishes and 30-ticket publishes
  on both copy paths. Dropdowns cover rows 6–35, and only the 9 ticketed answers and their 9 data
  tabs were present. See
  [live-sheets-run.md](./qa-new-audit-2026-10-06/live-sheets-run.md). All scratch files were
  trashed.
