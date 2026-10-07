# Ticket 421: Decide whether links that wrap a heading count for Q39

## Problem

Q39 counts internal links whose xpath lies *inside* an H2/H3
(`HEADING_LINK_XPATH_PATTERN`). A read-only run of the new
`heading_link_count` query on the real `rainbet-20260925-v4` crawl returned
**0 found / 0 tested** (324 ms), confirmed by parsing all 10,852 stored pages
with the crawler's own xpath code: 24,170 H2/H3 elements, 0 links inside one,
and **137 links that wrap a heading** (`<a><h3>…</h3></a>`). Under the current
definition Rainbet's Q39 therefore reads "could not be tested" rather than
Healthy, and the regenerated audit will say the same. Whether wrapping links
are heading links is a definition question, not a query bug.

## Tasks and acceptance criteria

- [x] Decide, with the question owner, whether `a > h2|h3` (and
      `a > * > h2|h3`) belongs to the Q39 population. Record the decision in
      the question registry entry and `docs/`.
- [x] If yes: extend `HEADING_LINK_XPATH_PATTERN` / the `links_json` xpath
      capture so both the producer count and the `_heading_link` failure filter
      match the wrapping form, with tests for both shapes and for the
      PostgreSQL `~*` form of the regex.
- [x] Regenerate the Rainbet technical audit from the `crawler` database and
      replay `technical-audit-questions`; Q39 must show a non-null denominator
      (unit "heading links") and the expected status.
- [x] ~~If no: add a note~~ (not applicable: the decision was yes). A note still names the wrapping links counted to Q39's answer when a run has 0 inside-heading links
      but N wrapping links, so analysts know why it could not be tested.

## Status

done (Priority: **P2**). Branch `fix/ticket-421`, based on c6073c3 (PR #119 tip).

**Decision (question owner, 2026-10-07): yes.** Links that wrap a heading (`a > h2|h3` and
`a > * > h2|h3`) count in the Q39 heading-link population alongside links inside an H2/H3. Recorded in
Q39's registry entry (question, issue_if, note, `requires` now includes `stored-html`) and the
regenerated `docs/technical-audit-questions.md`.

Approach. `links_json` cannot detect the wrapping form, so no XPath pattern can be extended to it:
a wrapping link's own XPath ends in `/a`, and `extract_links` keeps one link per target per page. On
Rainbet every one of the 137 wrapping anchors is a card whose image link to the same target comes
first, so the heading anchor is not in `links_json` at all (0 of 137 matched by source and XPath).
The wrapping form is therefore read from the stored HTML in the existing single stored-HTML pass
(ticket 379; one parse per page now shared with the empty-anchor row), so old crawls need no re-crawl
and old and new crawls are counted the same way:
- `extract.wraps_heading` (`a > h2|h3`, `a > * > h2|h3`) and `reports._heading_wrapping_links` (crawler
  `generate_xpath`, targets normalised like `extract_links`, same-host only).
- `CrawlReports.heading_link_population` (moved out of `technical_audit_context`, so reconcile and
  observation commands do not pay for an HTML pass) counts `links_json` inside-heading links (unchanged
  `HEADING_LINK_XPATH_PATTERN`, `~*`) UNION the wrapping anchors, distinct by source/target/XPath, and
  adds `heading_link_wrapping_count` (None when the run stored no HTML).
- `technical-audit` flags `internal-link-quality` rows with `wraps_heading: true` when the same page
  links to the same target from a heading-wrapping anchor (matched on source and target, because the
  saved row carries the image link's XPath); `_heading_link` accepts the flag.
- Q39 is never Healthy when the wrapping form was not checked (no stored HTML, or an audit built before
  this ticket); it says so in a note, and otherwise notes how many heading links wrap their heading.

Rainbet (`rainbet-20260925-v4`, read-only DSN, 11m27s, 1.3 GB peak; outputs in the gitignored
`runs/t421-rainbet/` of the worktree): `heading_link_count` 137, tested 137, wrapping 137. Q39 before:
saved merged bundle Needs validation / No (partial), no denominator; PR #119 code on the regenerated
bundle Pending, "could not be tested" (0 found / 0 tested). After: Needs validation / No (partial),
0 of 137 heading links, unit "heading links". The 137 flagged rows are all `non_indexable_target`,
which Q39 excludes, so there is no failure; the status stays below Healthy only because of the
run-wide coverage gate that also downgrades Q22 and Q13. No other answer changed (104 answers,
Issue 1 / Needs validation 22 / Healthy 1 / Pending 80, as before).

Tests: unit tests for both shapes, the helper, the marker, the population query and the answerer in
`tests/test_stream_integration_qa_fixes.py`; PostgreSQL tests in `tests/test_persistence_integration.py`
for `~*` parity with Python `re` and an end-to-end audit with a link inside an H2 and a card link
wrapping an H3 (run against a throwaway `crawler_cli_test_t421` database, dropped afterwards).

Filed 2026-10-07 after closing the Q39 part of 393 in PR #119. Related: 393, 395.
