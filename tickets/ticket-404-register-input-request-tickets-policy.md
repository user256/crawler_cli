# Ticket 404: Decide whether input-request tickets belong in the client register

## Goal

Decide whether input-request tickets belong in the client register.

## Problem

`unavailable_ticket` entries in the ticket language publish 'Supply verified search-bot access logs', 'Grant Search Console access or supply exports' (and, before 402, 'Authorise an external-link recheck') on every bare audit. They are static requests, not run-scoped findings, and there is no flag to suppress them. The README documents the behaviour as intended.

## Evidence

QA review of feature/full-manual-review-audit, finding 2.

## Tasks

- [ ] Confirm the policy with the audit owner; if kept, add a `--no-input-request-tickets` switch and label them as requests in the sheet; if dropped, remove the `unavailable_ticket` path.

## Definition of Done

- [ ] Client registers contain input requests only by explicit choice.

## Status

proposed (Priority: **P2**). Source: master reconciliation QA, 2026-10-06.
