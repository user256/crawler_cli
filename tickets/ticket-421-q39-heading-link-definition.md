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

- [ ] Decide, with the question owner, whether `a > h2|h3` (and
      `a > * > h2|h3`) belongs to the Q39 population. Record the decision in
      the question registry entry and `docs/`.
- [ ] If yes: extend `HEADING_LINK_XPATH_PATTERN` / the `links_json` xpath
      capture so both the producer count and the `_heading_link` failure filter
      match the wrapping form, with tests for both shapes and for the
      PostgreSQL `~*` form of the regex.
- [ ] Regenerate the Rainbet technical audit from the `crawler` database and
      replay `technical-audit-questions`; Q39 must show a non-null denominator
      (unit "heading links") and the expected status.
- [ ] If no: add a note to Q39's answer when a run has 0 inside-heading links
      but N wrapping links, so analysts know why it could not be tested.

## Status

proposed (Priority: **P2**). Filed 2026-10-07 after closing the Q39 part of
393 in PR #119. Related: 393, 395.
