# Ticket 370: Implement technical-audit Q96 — AI crawler governance

## Goal

Make Q96 answerable from deterministic, run-scoped Python evidence.

## Question

Do the robots.txt rules for AI crawlers differ from the site's declared AI policy?

## Rule

Issue if: For any of GPTBot, OAI-SearchBot, ClaudeBot, Claude-SearchBot, PerplexityBot, Google-Extended or CCBot, the effective robots.txt verdict differs from the profile's ai_crawler_policy.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Warning / Medium.
- Required inputs: `robots`, `site-profile`.
- Site-profile keys: `ai_crawler_policy`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `robots-controls`.
- New detector: `ai-crawler-policy`.
- Why it matters: AI search assistants send traffic only to sites they can crawl. Blocking a search agent by accident removes the site from those answers; allowing a training agent the site meant to block cannot be undone later.
- Registry note: Without a declared policy the per-agent inventory is reported as Needs validation. /llms.txt presence is reported but is not a defect: no major search engine has confirmed using it.

## Tasks

- [ ] Implement detector `ai-crawler-policy`, then register an explicit `Q96` answerer.
- [ ] Reuse contract evidence from `robots-controls`.
- [ ] Read `ai_crawler_policy` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q96 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; fed by saved robots.txt (`--robots-txt HOST=FILE`) (Priority: **P2**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Uses the project's RFC 9309 robots parser for the root path; 4xx = allow all, 5xx/unread = untested. Without `ai_crawler_policy` the per-agent inventory is reported as Needs validation. /llms.txt status is noted, never a defect. No live fetch (destination guard).
