# Ticket 264: Stored-HTML detectors for the question runner

## Goal

Answer the template questions that need only the raw HTML already stored for
a run (`pages.html_compressed`), with no re-crawl and no site profile.

## Scope

| Question | Detector |
|---|---|
| Q5 | `mixed-content` |
| Q12 | `head-elements-in-body` |
| Q15 | `heading-sequence` |
| Q17 | `social-tags` |
| Q41 | `locale-path-consistency` |
| Q45 | `locale-sibling-links` |
| Q47 | `breadcrumb-consistency` |
| Q51 | `semantic-landmarks` |
| Q53 | `faq-answer-presence` |
| Q54 | `figure-markup` |
| Q56, Q60 | `date-consistency` |
| Q58 | `toc-presence` |
| Q65 | `tracking-preloads` |
| Q67 | `font-loading` (needs first-party CSS fetches) |
| Q86 | `render-blocking-head` |
| Q91 | `empty-anchors` |
| Q92 | `insecure-form-actions` |

Also add answerers over contract checks as their collectors land (owners in
the contract): Q2, Q3, Q4, Q6, Q7, Q8, Q9, Q10, Q11, Q42, Q70, Q71, Q72,
Q73, Q74, Q76, Q79, Q80, Q83, Q84, Q85, Q87, Q88, Q89, Q93.

## Tasks

- Add a run-scoped detector pass that reads stored HTML once and emits rows
  per detector, with the parsed-page denominator, into the audit bundle.
- Register an answerer per question in `technical_audit_questions.ANSWERERS`;
  apply the registry thresholds.
- Fixture tests per detector: a defect page, a clean page, and a page the
  detector cannot judge (no stored HTML).

## Definition of Done

- [ ] Each listed question moves from Pending to Issue/Healthy/Needs
  validation on a fixture run.
- [ ] Detectors run on a saved run without network access.
- [ ] `docs/technical-audit-questions.md` regenerated.
