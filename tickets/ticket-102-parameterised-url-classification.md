# Ticket 102: Classify non-canonicalised parameterised URLs distinctly

## Goal
Query-string URLs that serve (near-)identical content to their base path and
declare **no canonical** currently flood the overlap analysis as ordinary
duplicate pages. Label them as what they are — non-canonicalised parameterised
variants — so the report reads "missing canonical on parameterised URL"
rather than burying them among genuine intent-overlap findings.

## Background (evidence: thompsons-scotland.co.uk run, 2026-07-15)
- 408 of 3337 pages.csv rows have a query string; **551 of 736 overlap pairs
  involve at least one parameterised URL** — they dominate the report.
- Worst case: `/the-team?type=…`, `?team_type=…`, `&limit=100` permutations —
  a Joomla filtered-list view exploding into dozens of sim-1.0 "duplicates"
  of each other, none declaring a canonical (site finding: they should all
  canonical to `/the-team`).
- `/other-services/claims-following-gdpr-breach?type=gdprform` vs its clean
  base URL, sim 1.0, no canonical.
- `/index.php` ↔ `/` paired at sim 1.0 — default-document URL not folded.
- Current machinery: `normalise_url` (hreflang_groups.py:45) strips only
  *tracking* params, so every param permutation is a distinct page;
  `resolve_variants` folds only same-norm-URL groups; `compute_exclusion`
  (intent_overlap.py:524) has no param awareness. Nothing can be folded
  blindly — params sometimes DO distinguish content — so this must be
  content-confirmed, not URL-only.

## Tasks
- Page classification: a page whose URL has a (post-tracking-strip) query
  string and no canonical (or a self-canonical that still carries the params)
  is `parameterised`. Record it (new column in pages.csv, e.g.
  `url_class=parameterised`, empty otherwise).
- Content-confirmed folding: when a parameterised page's base-path URL was
  also crawled and their **signature hashes match** (`intent_signatures.
  signature_hash` — already the unified content identity), treat the
  parameterised URL as a variant of the base URL: exclude it from pairing
  with reason `parameterised-duplicate` and suggest
  `add canonical → <base url>` in the pages report. Hash equality keeps this
  100% crawler-evidenced; do NOT fold on URL shape alone.
- Parameterised pages whose content does NOT match their base (genuine
  filtered/paginated views with distinct content) stay in the analysis but
  keep the `parameterised` class so pairs among them are identifiable
  (ticket 101's pair fields make this visible pair-side).
- Default-document folding: extend `normalise_url` to fold `/index.php`,
  `/index.html`, `/index.htm` (path tail) onto the directory URL — mirrors
  the trailing-slash rule. Check impact on hreflang grouping tests.
- Summary/manifest counts: parameterised pages, folded parameterised
  duplicates, missing-canonical count (the actionable site finding).
- Tests: classifier unit tests, signature-hash folding (match and non-match),
  index-document normalisation, report shape.

## Definition of Done
- Re-run on the thompsons-scotland store: the `/the-team` param explosion
  reports as parameterised duplicates of `/the-team` with a
  missing-canonical action, NOT as dozens of overlap pairs; overlap_pairs.csv
  pair count drops accordingly and remaining pairs are content findings.
- `/index.php` folds into `/`. ruff/mypy/tests green.

## Constraint
100% crawler-powered — folding decisions rest on crawler-captured canonical
and signature-hash evidence only. `?amp=1`/`&amp=1` URLs are AMP variants and
belong to ticket 103's classification (run both classifications; AMP wins).

## Status
done (2026-07-15, PR #15) — merged in the dependency-ordered review batch. Non-canonicalised parameterised URLs are classified, signature-hash-confirmed duplicates fold to their crawled base, default index documents normalise to their directory, and AMP query variants now explicitly retain the more specific AMP classification.
