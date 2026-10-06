# Ticket 405: Keep the 44-row control ledger and manual-review tab out of the client copy, and Config last

## Goal

Keep the 44-row control ledger and manual-review tab out of the client copy, and Config last.

## Problem

The register publisher appends 'Audit Controls' (every control with qualification codes such as `collector_not_available_for_this_run`) and 'Manual Review' to the copied client workbook, after the Config tab that ticket 223 requires to stay last. The branch's own SKILL text says no collection mechanics in client-facing fields.

## Evidence

QA review of feature/full-manual-review-audit, finding 3 (policy part).

## Tasks

- [ ] Put the ledger tabs behind a flag or into a separate internal workbook; keep Config as the last tab.

## Definition of Done

- [ ] Client copy carries Tickets plus evidence tabs only unless asked otherwise.

## Status

proposed (Priority: **P2**). Source: master reconciliation QA, 2026-10-06.
