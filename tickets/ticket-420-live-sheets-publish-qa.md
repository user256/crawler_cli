# Ticket 420: Live Google Sheets publish QA for the template-contract publisher

## Problem

Ticket 406 rebuilt the publisher around `templates/google-sheets-template-contract.json`
with fail-before-write header checks and a `sheets.copyTo` fallback. All of
that is covered by fakes only. The one live call made was a read of the
template header. Untested against the real API: the `copyTo` fallback under a
`drive.file` token, whether the Config-sourced Priority / Classification
dropdowns still resolve after the `Copy of X` → `X` rename, the folder move
under `drive.file`, and that the contract's value sets match the template's
actual dropdown sources.

## Tasks and acceptance criteria

- [x] With a token holding full `drive` scope, publish the saved Rainbet
      question answers via `technical-audit-questions --google-sheets-template`
      into a scratch folder; confirm rows land at `B6:I`, B3's `COUNTA(B6:B)`
      counts them, the header at B5 is intact and Config is untouched.
- [x] Repeat with a `drive.file`-only token so `files().copy` is refused;
      confirm the `copyTo` fallback produces a workbook with tabs `Tickets`,
      `Config` (plus evidence tabs), dropdowns resolve, and the workbook is in
      the requested folder.
- [x] Publish once with a deliberately mismatched contract column list and
      once against a copy whose header was edited; confirm
      `TemplateContractError` / `TemplateHeaderError` and that the copy has no
      writes (compare revision history).
- [x] Read the template's data-validation rules and compare their sources with
      the contract's `priority_values` / `classification_values`; add that
      comparison as a `--check-template` dry run or a documented script.
- [x] Delete the scratch workbooks afterwards; record sheet IDs, token scopes
      and outcomes in `tickets/qa-new-audit-2026-10-06/live-sheets-run.md`.

## Status

done (Priority: **P1**). Filed 2026-10-07; fixes under test are in PR #119.
Related: 189, 223, 406, 424, 428. Live run 2026-10-07 on `fix/ticket-420`: four of five
criteria done. The full-`drive` publish (first box) was done the same afternoon on
`fix/ticket-428`, after the user created a full-drive token. It passed after one more fix:
the publisher's `values.clear` had been deleting the template's dropdowns on the
`files.copy` path (commit `e33ff78`).

## Live run, 2026-10-07

Full record, with sheet IDs, token scopes and commands:
[qa-new-audit-2026-10-06/live-sheets-run.md](./qa-new-audit-2026-10-06/live-sheets-run.md).
All scratch workbooks and the scratch folder were trashed. The template was only read and was
unchanged afterwards.

- **`drive.file` (+ `spreadsheets`) token:** `files.copy` was refused (404) and the `copyTo`
  fallback ran. The Rainbet publish put 9 rows at `Tickets!B6:I14` and B3 shows "Count of
  tickets: 9". The B5 header and the frozen rows are intact, and Config is identical to the template. The tabs read
  Tickets, Questions, 13 evidence tabs, Config. The workbook was in the requested folder, and the receipt
  printed 15 ranges verified by read-back. **Defect, fixed:** `copyTo` dropped all 42
  Config-sourced dropdown cells (`F6:G26`). The fallback now restores the source validation after
  the renames. After the fix, 42 of 42 cells were restored and `--check-template` on the published copy passes.
- **A `drive.file`-only token (no `spreadsheets` scope)** cannot read the template at all, so
  the publish cannot work. **Defect, fixed:** it crashed with an `HttpError` traceback (exit 1) on both
  publish and `--check-template`. It now prints a clear error and exits 2, and nothing is created.
- **Mismatched contract columns:** `TemplateContractError`, exit 2, and no file created.
  **Edited header (`Severity` in G5):** `TemplateHeaderError` naming B5. The copy has a single
  revision, `modifiedTime` = `createdTime`, no added tabs and an empty `B6:I`.
- **`--check-template` on the real template:** passes, exit 0. The `Config!B2:B` and `Config!A2:A`
  values match the contract's Ticket Classification and Priority sets.
- **Observation:** the template validates only rows 6–26, so ticket rows 27+ get no dropdown.

Fix commit: `b6d8812` (tests for both defects; full suite 2047 passed).

## Full-drive publish, 2026-10-07 (afternoon, `fix/ticket-428`)

Token `google-drive-oauth-token.full-drive.json` (`drive`, `spreadsheets`). The Rainbet publish
went through `files.copy` into a scratch folder, and the workbook
`14-x_qr8gw6zDlwwQHkKiXxZsEQkBFPWuilYpGijowFU` (trashed) was checked:

- 9 rows at `Tickets!B6:I14`, and B3 shows "Count of tickets: 9".
- The B5 header and the 5 frozen rows are intact, and Config is identical to the template.
- Tab order: Tickets, Questions, 9 data tabs, Config.
- The dropdowns are on every ticket row, and `--check-template` on the copy passes.
- The receipt printed 11 ranges verified by read-back.

**Defect, fixed in `e33ff78`:** the first full-drive run had no dropdowns at all.
`values.clear` on `Tickets!B6:I10000` deleted the template's own `F6:G26` rules, which a plain
`files.copy` keeps. The publisher now clears values with `updateCells`
(`fields: userEnteredValue`), which keeps them. Details are in the
[run record](./qa-new-audit-2026-10-06/live-sheets-run.md).
