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
