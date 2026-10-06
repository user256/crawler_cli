# Ticket 360: Implement technical-audit Q104 — Search-result host hygiene

## Goal

Define the manual, supplied-evidence review workflow for Q104. The automatic runner keeps this question Pending and never raises a ticket for it.

## Question

Does Google Search show any unapproved alternate-host URL in the reviewed performance data or search results?

## Rule

Issue if: A dated GSC domain-property export records impressions for an unapproved hostname during the agreed review period, or a documented SERP check finds an unapproved alternate-host URL.

## Evidence and reuse

- Group: `external` — answerable: No; ticket: never; always Pending with the tool needed.
- Registry classification and priority: Warning / Medium.
- Required inputs: `gsc`, `external-api`.
- Threshold: `min_affected = 1`.
- Existing contract checks: none.
- New detector: none.
- Why it matters: Alternate-host results can divide visibility, expose non-production content and send users to the wrong version of the site even when the production host is healthy.
- Registry note: Manual review required: segment GSC page URLs by hostname and record the date range, permitted hosts, queries, location and review date for SERP checks. No impressions or site: matches does not prove universal absence from Google's index. Always Pending in the automatic runner; no automatic ticket.

## Tasks

- [ ] Define a versioned evidence record for the manual review: GSC domain-property export date range, permitted hosts, hostnames with impressions, and for SERP checks the query, location and review date.
- [ ] Document the review procedure next to the question in the review document.
- [ ] Keep the `external` group so the runner returns Pending with the tool needed and `ticket = false`.
- [ ] Add a regression test proving Q104 stays Pending with no automatic ticket, even when a review record is present.

## Definition of Done

- [ ] The runner returns Pending for Q104 with the required tool named, and never a ticket.
- [ ] The manual record states its date range and scope; no result is presented as proof of universal absence from Google's index.

## Status

implemented locally (manual workflow); always Pending (Priority: **P2**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Review procedure documented in the registry note; versioned record kind `search-host-review` defined; `test_q104_stays_pending_even_with_a_review_record` proves Pending with no ticket.
