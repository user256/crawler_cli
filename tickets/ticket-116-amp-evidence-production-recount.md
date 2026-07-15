# Ticket 116: Confirm evidence-backed AMP counts on thompsons-scotland

**Status:** proposed (2026-07-15 MERGE follow-up from ticket 108 / PR #23)
**Priority:** P3 evidence / ops
**Related:** Tickets 103, 108
**Depends on:** Fresh crawl or live store with post-103/108 amphtml edges + signatures

## Goal

Record how many thompsons-scotland AMP classifications are positively confirmed
under ticket 108's evidence rules (amphtml edge, canonical-to-base, or
signature-hash), including the missing-canonical subset.

## Background

PR #23 (ticket 108) removed `base-exists`-only AMP confirmation and recomputes
`variant_kind` each run. Unit and Postgres integration coverage pass. The
checked-in `runs/thompsons-scotland-20260715/` export predates ticket 103
(`amp_issues.csv` absent; no `amp-variant` exclusion reasons), so the literal
DoD production-rerun count was deferred at merge.

## Tasks

- Run a fresh intent-overlap (or reclassify) against a post-103/108 store with
  signatures and amphtml edges for thompsons-scotland.
- Record confirmed_by mix (amphtml / canonical / signature-hash) and the
  missing-canonical subset versus the prior 648 AMP / 171 missing-canonical
  figures.
- Attach counts to this ticket's acceptance notes (no inferred counts from
  unit tests alone).

## Definition of Done

Production evidence-backed AMP coverage and missing-canonical counts are
written into this ticket; no page is counted AMP from URL shape + base
existence alone on that run.
