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

- [ ] With a token holding full `drive` scope, publish the saved Rainbet
      question answers via `technical-audit-questions --google-sheets-template`
      into a scratch folder; confirm rows land at `B6:I`, B3's `COUNTA(B6:B)`
      counts them, the header at B5 is intact and Config is untouched.
- [ ] Repeat with a `drive.file`-only token so `files().copy` is refused;
      confirm the `copyTo` fallback produces a workbook with tabs `Tickets`,
      `Config` (plus evidence tabs), dropdowns resolve, and the workbook is in
      the requested folder.
- [ ] Publish once with a deliberately mismatched contract column list and
      once against a copy whose header was edited; confirm
      `TemplateContractError` / `TemplateHeaderError` and that the copy has no
      writes (compare revision history).
- [ ] Read the template's data-validation rules and compare their sources with
      the contract's `priority_values` / `classification_values`; add that
      comparison as a `--check-template` dry run or a documented script.
- [ ] Delete the scratch workbooks afterwards; record sheet IDs, token scopes
      and outcomes in `tickets/qa-new-audit-2026-10-06/live-sheets-run.md`.

## Status

proposed (Priority: **P1**). Filed 2026-10-07; fixes under test are in PR #119.
Related: 189, 223, 406, 424.
