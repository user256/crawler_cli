# Ticket 101: Classify overlap-pair URL relationships (parent-child, sibling, section)

## Goal
Every overlap pair and cluster member currently gets the same undifferentiated
treatment. Classify the URL-path relationship between the two sides of each
pair so downstream labelling, remediation guidance, and fail-on gating can
treat structurally different situations differently.

## Background (evidence: thompsons-scotland.co.uk run, 2026-07-15)
`runs/thompsons-scotland-20260715/overlap_pairs.csv`: 736 pairs.

- **30 pairs are direct parent-child** (one URL's path is a prefix of the
  other's), e.g. `/accidents-to-cyclists` ↔
  `/accidents-to-cyclists/cycle-accident-compensation-claims`, and the
  `/videos` hub vs each `/videos/<category>` page. A hub/landing page
  overlapping its own detail pages is a *content-differentiation* problem
  (or an intentional consolidation candidate) — not the same de-canonicalisation
  risk as two unrelated pages competing, and "pick one canonical" is often the
  wrong remediation for a parent-child pair.
- Many more pairs are same-section siblings (e.g. within `/videos/...`,
  `/news/archived/...`) where cluster-level review beats pair-level review.
- `overlap_pairs.csv` fields today: `url_a,url_b,similarity,low_confidence,sim_percentile`
  — no relationship information at all; `pages.csv`/`clusters.csv` likewise.

## Tasks
- Add a pure classification helper (suggest: `hreflang_groups.py` next to
  `normalise_url`, or a small `url_relations.py`): given two same-host URLs
  return `parent-child` (path-prefix, either direction), `sibling` (same
  parent directory), `same-section` (same first path segment), else
  `cross-section`. Normalise before comparing (reuse `normalise_url`).
- Extend `overlap_pairs.csv` with `relation`, `section_a`, `section_b`
  (first path segment; `/` for the homepage).
- In `pages.csv`/`clusters.csv`, when a page's duplicate risk is driven
  *solely* by parent-child pairs, use a distinct risk label (suggest:
  `parent-child overlap — differentiate or consolidate deliberately`) instead
  of `duplicate — decanonicalisation likely`, and have
  `suggested_canonical` prefer the parent as the natural survivor when a
  merge IS wanted.
- `--fail-on duplicate` keeps counting parent-child pairs by default but the
  summary line must break the counts out (e.g. `736 pairs (30 parent-child)`),
  so CI users can see composition. A follow-up policy flag can gate them out
  later if wanted — do not silently change gating semantics in this ticket.
- run_manifest summary gains per-relation pair counts.
- Unit tests over the classifier (trailing slash, homepage, query strings,
  nested depth >1) and a report-shape test.

## Definition of Done
- `overlap_pairs.csv` rows carry `relation`/`section_a`/`section_b`; pages and
  clusters reports distinguish parent-child-driven duplicate risk; manifest
  and summary line expose per-relation counts; ruff/mypy/tests green.
- Re-run against the thompsons-scotland Postgres store: the 30 parent-child
  pairs classify correctly (spot-check `/videos` hub and
  `/accidents-to-cyclists` cases).

## Constraint
100% crawler-powered — classification uses only the URL structure the crawler
already captured. No external input.

## Status
done (2026-07-15, PR #16) — merged in the dependency-ordered review batch. Pair/cluster relationship fields, parent-child risk labelling and canonical preference, relation summary counts, and unchanged duplicate gating were retained in the combined implementation. Validated in the 493-test merged suite plus lint, formatting, mypy, and browser smoke checks.
review. Foundation for ticket 105 (time-sequenced section policy).
