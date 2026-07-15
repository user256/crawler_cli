# Ticket 108: Harden AMP classification evidence and recomputation

**Status:** done (2026-07-15)
**Priority:** P1 correctness
**Depends on:** Ticket 103

## Goal

Prevent an ordinary URL whose final path segment is `/amp` from being excluded
from intent analysis merely because the corresponding base URL was crawled.
Keep AMP classification grounded in positive crawler-captured evidence.

## Review finding

Ticket 103 correctly added `rel="amphtml"` extraction, `variant_kind`, explicit
analysis precedence, and canonical-hygiene reporting. Its classifier also treats
`AMP-shaped URL + base page exists` as sufficient confirmation. Base existence
is not content evidence and is broader than Ticket 103's constraint; a legitimate
non-AMP `/amp` route could therefore be silently excluded. The content comparison
currently uses raw response hashes, while the ticket names intent-signature hashes.

## Tasks

- Keep a `rel="amphtml"` target authoritative.
- For URL-shape candidates without that edge, require a canonical-to-base match
  or equality of the crawler's intent-signature hash with the crawled base.
- Remove `base-exists` as sufficient evidence and use `signature_hash`, not raw
  response-body identity, for semantic-content confirmation.
- Recompute `variant_kind` deterministically so stale AMP labels are cleared when
  a page no longer satisfies the classifier.
- Preserve AMP-over-parameterised precedence and `amp_issues.csv` behaviour.
- Add negative coverage for a literal `/amp` page with a crawled base but no
  canonical, signature match, or amphtml edge.
- Re-run against a fresh thompsons-scotland crawl and record how the 648 AMP pages,
  including the 171 missing-canonical findings, are positively confirmed.

## Definition of Done

No page is classified AMP from URL shape plus base existence alone; all AMP
classifications report an authoritative edge, canonical match, or signature-hash
match. Stale labels are cleared, the production rerun retains evidence-backed AMP
coverage, and ruff, formatting, mypy, unit, and PostgreSQL integration tests pass.

## Acceptance notes (2026-07-15)

- `classify_amp_variants` confirmation paths are now `amphtml-target`,
  `canonical-to-base`, and `signature-hash` only; `base-exists` / raw
  `content_hash` confirmation removed.
- Persistence recomputes `variant_kind='amp'` each run (clear-then-write) so
  stale labels drop when evidence disappears.
- Negative unit + integration coverage: `/amp` + crawled base with no
  amphtml/canonical/signature evidence is not classified.
- Thompsons-scotland production confirmation: the checked-in
  `runs/thompsons-scotland-20260715/` export predates ticket 103
  (`amp_issues.csv` absent; no `amp-variant` exclusion reasons). A fresh
  intent-overlap pass against the live store (with signatures + amphtml
  edges) is required to count evidence-backed AMP coverage and the
  missing-canonical subset; not blocked here.
