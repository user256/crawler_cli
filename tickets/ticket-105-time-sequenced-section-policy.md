# Ticket 105: Softer overlap policy for time-sequenced sections (news/blog)

## Goal
News/blog archives naturally accumulate semantically-close pages on recurring
topics; the query-deserves-freshness dynamic means canonical-merging them is
usually wrong even when similarity is high. Give intra-section pairs in
designated time-sequenced sections a distinct label and default gating so
they are reviewed editorially instead of being flagged as decanonicalisation
emergencies.

## Background (evidence: thompsons-scotland.co.uk run, 2026-07-15)
- 14 of 736 pairs are news↔news, e.g.
  `/news/archived/frankly-legal-health-and-safety` ↔
  `/news/archived/frankly-legal-how-health-safety-helps-you` — a recurring
  column on one topic. Semantically near-duplicates; editorially distinct,
  time-anchored posts. Neither merging nor canonicalising is obviously right,
  and the current `duplicate — decanonicalisation likely` label overstates it.
- Depends on ticket 101 (pair relation + section columns) for the section
  classification plumbing.

## Tasks
- Config surface: repeatable `--time-sequenced-section PATH_PREFIX` (e.g.
  `--time-sequenced-section /news`). Explicit opt-in only — do NOT
  auto-detect from URL keywords; the operator knows their site's sections.
  (A later enhancement could suggest candidates from crawl-captured
  article dates, but detection is out of scope here.)
- Labelling: pairs where BOTH URLs fall under the same time-sequenced prefix
  get pair class `time-sequenced` and page/cluster risk
  `topical overlap (time-sequenced) — review editorially; consider hub or
  internal linking` instead of the duplicate label. Cross-section pairs
  (news vs evergreen service page) are unaffected — those often ARE real
  cannibalisation and must keep full duplicate/overlap treatment.
- Gating: time-sequenced intra-section pairs excluded from
  `--fail-on duplicate` counts by default; summary/manifest reports them as
  their own count so nothing disappears silently.
- Reports: clusters.csv gets the softer suggested action for such clusters
  (suggest hub/roundup page rather than a canonical survivor).
- Tests: prefix matching (nested paths, trailing slash), both-sides rule,
  gating, label precedence vs ticket 104's thin label (thin wins — a thin
  news page is still thin).

## Definition of Done
- Re-run on the thompsons-scotland store with
  `--time-sequenced-section /news`: the 14 news pairs report under the
  topical-overlap label and drop out of duplicate gating; all non-news
  findings unchanged; ruff/mypy/tests green; README documents the flag and
  the QDF rationale.

## Constraint
100% crawler-powered. Depends on ticket 101.

## Status
done (2026-07-15, PR #14) — merged after ticket 101 in the dependency-ordered review batch. The repeatable section policy, pair class, softer page/cluster guidance, and duplicate-gate exclusion are live. Combined regression tests ensure thin content wins and an ordinary cross-section overlap cannot be masked by a closer time-sequenced match.
