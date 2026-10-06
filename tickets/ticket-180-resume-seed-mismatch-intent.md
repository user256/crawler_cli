# Ticket 180: Make changed seeds explicit on `--resume`

## Goal

Prevent `--resume --allow-run-config-mismatch` from accepting new seeds and
then silently discarding them because a resume only resets the existing
frontier.

## Background

The resume compatibility check correctly refuses a changed seed/config hash
unless the override flag is given. With the override, it logs a broad mismatch
warning; `crawl_open()` then takes the resume branch and only resets pending
frontier rows. The invocation's newly supplied seeds are never enqueued.

## Tasks

- Separate tuning-only compatibility changes from seed/scope changes in the
  stored run snapshot and CLI validation.
- Choose and document one safe contract: either reject changed seeds even with
  `--allow-run-config-mismatch`, or require a separately named, deliberate
  add-seeds-on-resume option that records provenance and applies normal scope,
  dedupe, budget, and run-lifecycle rules.
- Never weaken ticket 148 scope-manifest immutability or allow an override to
  widen an authorised scope.
- Make the summary/saved output state whether seeds were reused, rejected, or
  deliberately added.

## Definition of Done

- A changed seed set cannot be accepted and silently omitted.
- Tuning-only resume override behaviour remains available where safe.
- Tests cover default rejection, override handling, seed provenance, dedupe,
  and unchanged-scope enforcement.
- CLI help and README state the chosen contract.

## Status

proposed (2026-09-23, Priority: **P1**) — resume correctness; found in Shopify crawl review.
