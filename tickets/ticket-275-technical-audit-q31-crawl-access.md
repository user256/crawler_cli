# Ticket 275: Implement technical-audit Q31 — Crawl access

## Goal

Make Q31 answerable from supplied, versioned evidence. The runner must not make live third-party requests.

## Question

Does the site serve Google's crawler materially different content from what it serves visitors?

## Rule

Issue if: Content, links or directives fetched as verified Google differ materially from a visitor fetch of the same URL.

## Evidence and reuse

- Group: `external` — answerable: No; ticket: never; always Pending with the tool needed.
- Registry classification and priority: Error / High.
- Required inputs: `external-api`.
- Threshold: `min_affected = 1`.
- Existing contract checks: none.
- New detector: none.
- Why it matters: Showing search engines different content from users breaks Google's spam policies and can lead to a manual action that removes pages from search.
- Registry note: crawler_cli can compare a Googlebot user agent with a browser user agent from the same IP, which catches user-agent cloaking only; IP-based cloaking needs a fetch from Google's own IPs (URL Inspection).

## Tasks

- [ ] Move Q31 from the `external` group to `supplied-input` in the registry first. While it is `external`, `_answer_one` returns Pending before looking up `ANSWERERS` (`technical_audit_questions.py`, the `group == "external"` branch), so a new answerer would be silently ignored.
- [ ] Implement a versioned supplied-evidence reader and an explicit `Q31` answerer; it must not make live third-party requests.
- [ ] Define and persist the minimum evidence schema before classifying.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing input must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q31 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Keep the answer Pending until supplied evidence is present. The implementation may classify the supplied bundle but must not imply it queried Google or observed all SERPs.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; supplied input (verified-google-fetch) (Priority: **P1**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Moved to `supplied-input`; Pending until a supplied bundle is attached; the runner never fetches as Google.
