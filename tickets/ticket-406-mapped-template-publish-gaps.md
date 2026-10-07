# Ticket 406: Finish ticket 223: template mapping, copy fallback and destination header check

## Goal

Finish ticket 223: template mapping, copy fallback and destination header check.

## Problem

The template id is hard-coded in the ticket-language JSON; `drive.files().copy` has no `sheets.copyTo` fallback for drive.file-scoped OAuth tokens; the header check reads the source sheet rather than the copy; `header_row: 6` is unverified against the real template, and no test covers a header mismatch.

## Evidence

QA review of feature/full-manual-review-audit, finding 4.

## Tasks

- [ ] Read the mapping from the template contract; add the copyTo fallback; verify headers on the destination; test a mismatch.

## Definition of Done

- [ ] A mapped publish fails loudly on a changed template and works with drive.file tokens.

## Status

partly done (Priority: **P2**). Source: master reconciliation QA, 2026-10-06.
Destination header check and fail-before-write done 2026-10-07; template-contract mapping and the
copyTo fallback remain open (see below).

## Post-merge QA, 2026-10-06

Still applicable to the replacement publisher at `72629af`, though the original
control-register implementation has been removed. In
`GoogleSheetsTemplatePublisher._ticket_header_anchor`, an unrecognised header
falls back to `(1, 2)`. A fixture with a copied Tickets tab containing a title,
existing note and unrecognised header calls `values.clear` on
`'Tickets'!A2:H10000`, then writes generated rows at A2. No full header sequence
is checked. The source template is preserved, but client content in the copy
can be overwritten and generated fields can land under wrong columns.

- [x] Fail before any clear/update if the expected destination header is missing
  or its full column mapping does not match; do not default to A2.
- [x] Test the current question publisher with absent, partial and reordered
  headers, plus correctly located headers beneath a title block.

This supplements the existing ticket rather than filing a duplicate.

### Fix, 2026-10-07 (`fix/postmerge-qa-misc`)

Post-merge criteria done. With `locate_ticket_header` (the question publisher),
`GoogleSheetsTemplatePublisher.publish` now reads the copied workbook's Tickets tab
right after copying and before any `addSheet`, `values.clear` or `values.update`.
The full generated header must appear in order in consecutive cells (whitespace and
case are normalised); an absent, partial, reordered or interleaved header, or a copy
without a Tickets tab, raises `TemplateHeaderError` (a `ValueError`, so the CLI exits
with a validation error) naming the copy and the closest header found. There is no A2
fallback on this path. The copied workbook is left as copied, not deleted. Tests in
`tests/test_google_sheets.py` use fakes and assert no writes on failure.

Still open from the original ticket: reading the mapping from a template contract
instead of the hard-coded template ID, the `sheets.copyTo` fallback for drive.file
tokens, and verifying `header_row: 6` against the real template. The non-question
`technical-audit --google-sheets-template` path (no `locate_ticket_header`) still
writes Tickets rows at A2 without a header check.

### Completion, 2026-10-07 (`fix/postmerge-qa2-sheets`)

- **Every publish path checks the header.** `technical-audit --google-sheets-template` used
  to clear `'Tickets'!A2:H10000` and write at A2. In the real template that range holds the
  ticket-count formula (B3) and the header (B5). The `locate_ticket_header` switch is gone. Both
  commands now locate the full header in the copy and fail with `TemplateHeaderError` before
  any `addSheet`, `values.clear` or `values.update`. There is no A2 fallback.
- **Template contract.** `templates/google-sheets-template-contract.json` (version
  `crawler-cli/google-sheets-template-contract/1`) holds the template URL, the Tickets tab
  name, the ticket columns, the header search window (40 rows × 26 columns), the Priority and
  Ticket Classification value sets, and the protected tabs (`Config`).
  `load_template_contract` / `validate_template_contract` reject malformed contracts. The publisher
  takes the contract, and `--google-sheets-contract` selects another one for both commands.
  Without `--google-sheets-template`, the contract's template is copied. Before anything is
  copied, the publisher raises `TemplateContractError` if the generated Tickets columns differ
  from the contract, if a ticket's Priority or Classification is outside the dropdown values,
  or if a generated tab would overwrite the tickets tab or a protected tab. A test keeps the
  contract in step with `TICKET_COLUMNS` and the ticket-language `target_template`.
- **`sheets.copyTo` fallback.** If `drive.files().copy` fails with HTTP 403 or 404, the
  publisher rebuilds the workbook. It calls `spreadsheets.create`, copies each template tab
  in index order with `sheets.copyTo`, deletes the placeholder tab and renames each
  `Copy of X` back to `X` in one batch. It then moves the workbook into `--google-sheets-folder`
  if one was given. The header is still checked on that destination before any write. Other
  errors are re-raised.
- **`header_row: 6` was wrong.** On 2026-10-07 a single read-only Sheets API read of template
  `1T9BRLgaFDZ99Lx3q53Av75eZZM32BIJc0nahVPQpGmU` used the existing
  `drive.file + spreadsheets` OAuth token. It showed the header at **B5** (row 5, not 6), 5
  frozen rows, prefilled row numbers in column A, `COUNTA(B6:B)` in B3, and tabs
  `Tickets, Config`, with Config holding the dropdown values. This is recorded under
  `verified_layout` in the contract. The publisher does not use those values to place rows:
  it locates the header dynamically, so a fixed header row no longer matters. Tests cover a
  header at rows 1, 5, 6 and 12 and the real layout (writes go to `B6:I`).

Tests are in `tests/test_google_sheets.py`, all with fakes. They cover: plain-path mismatch with
no writes; the real layout; contract defaults, errors and a custom tab; and the 403/404 fallback
with the 500 error not masked. On the previous code the plain path wrote at A2 under a
mismatched header, and a refused Drive copy raised.

Not done (from ticket 223, outside this ticket's criteria):
- No live publish was run, so these are unverified against the real API: copyTo with a
  `drive.file` token, Config-sourced validation resolving after the rename, and the folder
  move under `drive.file`.
- The template's actual data-validation sources are not read back and compared with the
  contract value sets.
- Evidence tabs are still appended at the end, not placed between Tickets and Config.
- The receipt/read-back verification from ticket 189 is not reused.
