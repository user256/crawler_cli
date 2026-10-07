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

- [x] `addSheet` requests for evidence tabs pass an `index` placing them after
      `Tickets` and before `Config`; test with the fake service.
- [x] After writing, read back `Tickets!B6:I<n>` and each evidence tab's used
      range and fail with a `PublishReceiptError` on any mismatch; return a
      receipt (sheet ID, ranges, row counts) that the CLI prints.
- [x] Optional `--check-template` reads the template's data-validation rules
      and fails if their sources disagree with the contract.

## Status

done (Priority: **P3**). Filed 2026-10-07, done 2026-10-07 on `fix/ticket-424`
(based on the PR #119 tip). Related: 189, 223, 406, 420.

## Completion, 2026-10-07

All in `src/crawler_cli/google_sheets.py`, tested with fakes in
`tests/test_google_sheets.py`. No live Google API call was made.

- **Tab order.** The copy's tab indexes are read with the sheet IDs. New
  evidence tabs are added with `index` = Tickets index + 1, + 2, …, so the
  workbook reads Tickets, Questions, Q15 Data…, Config. Without a Tickets tab
  they go before the first protected tab; with neither, they are appended.
  Tabs that already exist in the copy are not moved.
- **Read-back receipt.** `publish()` now returns a `PublishReceipt`
  (`spreadsheet_id`, `url`, `ranges` of tab / A1 range / rows sent). After
  every write it reads back `Tickets!<col><first>:<col><n>` (the first data
  row when there are no tickets, which must then be empty) and each evidence
  tab's whole used range with `UNFORMATTED_VALUE`. Cells are compared as
  canonical text: `None`/empty equal, trailing empty cells and rows trimmed,
  numbers compared numerically whether they come back as numbers or strings,
  booleans as `TRUE`/`FALSE`, CRLF as LF. Any difference (lost row, changed
  cell, stale extra cell, truncated columns) raises `PublishReceiptError`
  (a `RuntimeError`, so the CLI exits 2) naming up to five cells, with the
  workbook left in place. Both `technical-audit` and `technical-audit-questions`
  print the receipt after the workbook URL. Unlike ticket 189's original, no
  receipt file is written and there is no resume; that was not in scope.
- **`--check-template`** on `technical-audit-questions` (stand-alone, read-only;
  `--audit` and `--out` are only required without it):

      crawler-cli technical-audit-questions --check-template \
        [--google-sheets-template <url-or-id>] [--google-sheets-contract <json>] \
        [--google-sheets-credentials <service-account.json>]

  `check_template_validation` locates the Tickets header as the publisher
  does, reads `dataValidation` for the first 100 data rows of the ticket
  columns (`spreadsheets.get`, `includeGridData`, field mask limited to
  `dataValidation`), resolves `ONE_OF_LIST` values or `ONE_OF_RANGE`
  formulas such as `=Config!$A$2:$A$5` with a `values.get`, and compares each
  contract `value_sets` column (Priority, Ticket Classification) with the
  template as sets. It prints OK/FAIL per column with the template values,
  contract values and the `only in template` / `only in contract` diff, and
  exits 2 on a mismatch, a missing rule on the first data row, an unsupported
  rule type, or a rule that changes further down the column. Rows in the
  sample with no validation are reported as a note, not a failure. Auth is
  the same as the publish path.

Not done: the flag has not been run against the real template; ticket 420
will do that live.
