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
