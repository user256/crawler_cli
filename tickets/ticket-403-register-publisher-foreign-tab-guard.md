# Ticket 403: Never clear a client tab that merely shares a name with an audit tab

## Goal

Never clear a client tab that merely shares a name with an audit tab.

## Problem

`_write_audit_register_tabs` cleared `'<Tab>'` wholesale before writing; only `addSheet` checked whether the tab existed. A client template that already had an 'Audit Controls' or 'Manual Review' tab lost its content.

## Evidence

QA review of feature/full-manual-review-audit, finding 3 (safety part).

## Tasks

- [x] Before clearing a pre-existing tab, read its header row; refuse unless it is the audit's own header (a rerun).
- [x] Tests: foreign tab refused and untouched; own tab still rewritten and trimmed on rerun.

## Definition of Done

- [x] No client-authored tab is ever cleared.

## Status

implemented (local) (Priority: **P1**). Source: master reconciliation QA, 2026-10-06.
