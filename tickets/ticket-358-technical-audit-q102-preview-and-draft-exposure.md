# Ticket 358: Implement technical-audit Q102 — Preview and draft exposure

## Goal

Make Q102 answerable from deterministic, run-scoped Python evidence.

## Question

Does any preview, draft, admin or CMS utility URL violate its approved access or indexing policy?

## Rule

Issue if: An unauthenticated request exposes protected content, or an intentionally public utility URL lacks its required noindex or crawl control; a public noindex directive is not readable because robots.txt blocks the URL.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Warning / High.
- Required inputs: `crawl`, `probes`, `robots`, `site-profile`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `robots-controls`, `indexability-segmentation`.
- New detector: `utility-path-access-policy`.
- Why it matters: Public preview and utility URLs can expose unfinished content, create duplicate pages and introduce low-value or sensitive crawl paths.
- Registry note: Planned: no dedicated answerer yet. Needs approved protected/public path classes and scoped unauthenticated probes. A login page returning 200 is not by itself evidence of exposed protected content; crawl-only absence is not proof of protection.

## Tasks

- [ ] Implement detector `utility-path-access-policy`, then register an explicit `Q102` answerer.
- [ ] Reuse contract evidence from `robots-controls`, `indexability-segmentation`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q102 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

answerer implemented; collector missing (Priority: **P1**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Collector missing: the answer stays Pending until a `utility-path-probe` observation collection is attached (format in docs/technical-audit-observations.md). No crawler_cli command produces it yet. Records carry the approved path class (protected or public-utility).
