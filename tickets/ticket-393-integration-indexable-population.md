# Ticket 393: Count the indexable-page population for Q15 and Q71

## Goal

Fix a defect found in QA of the merged Stream A, B and C technical-audit work on 2026-10-06, before it reaches master.

## Problem

Q15 (heading issues on indexable pages) and Q71 (missing canonical on indexable pages) filtered finding rows to indexable pages but kept the parsed-page count as the denominator, so a run with zero indexable pages answered Healthy. Q39 (targets linked from H2/H3) has the same shape: the heading-link population is never counted, so a site with no heading links answers Healthy; it is NOT fixed here.

## Evidence

Stream B QA review, defect 3. Rainbet bundle: metadata-basics denominator 10,852 parsed pages regardless of indexability.

## Tasks

- [x] Use the indexable count from the profile page facts as the Q15/Q71 denominator when that input is present, so a zero population cannot pass.
- [x] Record Q39 heading-link population as an open gap: the internal-link-targets collector only returns failing links.
- [x] Count the Q39 H2/H3 heading-link population (found and tested) per run and use the tested count as the Q39 denominator.

## Definition of Done

- [x] Q15/Q71 answer 'could not be tested' with zero indexable pages and use the indexable count otherwise.
- [x] Q39 gap filed, not silently left.
- [x] Q39 is Healthy over a counted, tested heading-link population with no failures; failures stay Issue with a ticket; zero tested heading links cannot pass; audits without the counts behave as before.

## Status

implemented (local); Q39 gap fixed conservatively (Priority: **P1**). Source: stream integration QA, 2026-10-06.

Q39 follow-up (post-merge QA, 2026-10-06), fixed on `fix/postmerge-qa-misc`: the Q39 answerer no
longer uses the parsed-page count as its denominator. Because the internal-link-targets collector
returns only failing links, the heading-link population is unknown, so Q39 now reports no
denominator (unit `heading links`) and marks its scope incomplete. A run with no failing heading
links, including an empty link population, answers `Needs validation` / `No (partial)` with a note,
never Healthy. Failing heading links still answer Yes. Regression:
`test_q39_heading_links_cover_error_redirect_and_noncanonical_targets`. Remaining (not done): a
producer that counts all H2/H3 links per run, which would let a clean Q39 reach Healthy.

Q39 producer (post-merge QA 2, 2026-10-07), done on `fix/postmerge-qa2-q39`:
`CrawlReports.technical_audit_context` now adds `heading_link_count` (distinct source/target/XPath links
inside an H2 or H3, from `links_json`) and `heading_link_tested_count` (those whose target has a saved
status in the same run) to `run_context`, using one XPath pattern shared with the answerer
(`HEADING_LINK_XPATH_PATTERN`). Both are `None` when the schema has no `links_json`. The Q39 answerer uses
the tested count as its denominator (unit `heading links`):
- counted population, no failing heading links: Healthy / No;
- failing heading links: Issue / Yes with a ticket, unchanged;
- untested heading links (target not fetched in the run) are noted as a count, not a blocker;
- zero tested heading links (none found, or none tested): the shared empty-population rule applies, so
  Q39 stays Pending with "No items in the tested population, so the rule could not be tested." (an empty
  population is not evidence of passing);
- audit JSON saved before the counts existed: unchanged, Needs validation / No (partial), no denominator,
  with a note to regenerate the audit.
Regressions in `tests/test_stream_integration_qa_fixes.py` (`test_q39_*`,
`test_technical_audit_context_*heading*`, `test_heading_link_pattern_matches_only_h2_and_h3_links`). The
saved Rainbet audit replay is unchanged apart from Q39's note text. The SQL was not run against a live
database in this pass (no database credentials were available to the agent); the context query is covered
by a fake-store unit test only.

Integration follow-up: a clean Q39 whose counted population has untested heading links (found > tested) is Needs validation, not Healthy.
