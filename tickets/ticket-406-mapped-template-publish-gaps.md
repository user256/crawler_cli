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

proposed (Priority: **P2**). Source: master reconciliation QA, 2026-10-06.

## Post-merge QA, 2026-10-06

Still applicable to the replacement publisher at `72629af`, though the original
control-register implementation has been removed. In
`GoogleSheetsTemplatePublisher._ticket_header_anchor`, an unrecognised header
falls back to `(1, 2)`. A fixture with a copied Tickets tab containing a title,
existing note and unrecognised header calls `values.clear` on
`'Tickets'!A2:H10000`, then writes generated rows at A2. No full header sequence
is checked. The source template is preserved, but client content in the copy
can be overwritten and generated fields can land under wrong columns.

- [ ] Fail before any clear/update if the expected destination header is missing
  or its full column mapping does not match; do not default to A2.
- [ ] Test the current question publisher with absent, partial and reordered
  headers, plus correctly located headers beneath a title block.

This supplements the existing ticket rather than filing a duplicate.
