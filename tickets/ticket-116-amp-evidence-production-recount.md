# Ticket 116: Confirm evidence-backed AMP counts on thompsons-scotland

**Status:** done (2026-07-16 production-store reclassification)
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

## Acceptance notes (2026-07-16)

- Ran the current ticket-108 classifier through `intent-overlap` against the
  dedicated production store `thompsons_scotland_co_uk_crawler`, writing a
  fresh local report set to
  `runs/thompsons-scotland-20260716-amp-recount/`. The run completed at
  `2026-07-16T07:18:01Z`; it used the existing Thompson's crawl corpus (3,962
  URL identities, 3,895 fetched-200 pages, 3,333 intent-signature hashes), not
  fixtures or unit-test data.
- The fresh report classified **479** AMP variants, versus the pre-hardening
  figure of 648 (**-169**). The missing-canonical subset is **0**, versus 171
  previously (**-171**). `amp_issues.csv` has two `canonical-not-base` rows;
  both remain positively confirmed by their matching signature hashes and are
  not missing canonicals.
- Confirmation evidence is **0 `amphtml-target`**, **477
  `canonical-to-base`**, and **2 `signature-hash`**. A direct read of the live
  store found zero persisted `amphtml_urls` edges. This is an important
  provenance limitation of the historical corpus: its page fetches predate
  ticket 103's `rel=amphtml` extraction, even though the store has subsequently
  received the ticket-103 schema. The zero is recorded as observed evidence,
  not treated as an inferred AMP count.
- The recount invoked `classify_amp_variants` over all 3,895 fetched-200 pages
  using only the three ticket-108 confirmation paths. Its 479 rows exactly
  match the fresh intent-overlap `amp-variant` exclusion total; URL shape plus
  a crawled base was never sufficient. The two signature-hash rows and all 477
  canonical-to-base rows have a crawler-stored matching base, while no row was
  admitted by base existence alone.
