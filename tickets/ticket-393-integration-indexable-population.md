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

## Definition of Done

- [x] Q15/Q71 answer 'could not be tested' with zero indexable pages and use the indexable count otherwise.
- [x] Q39 gap filed, not silently left.

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
