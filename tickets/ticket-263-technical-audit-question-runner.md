# Ticket 263: Answer the audit template's Questions tab from a saved technical audit

## Goal

Answer every question on the Questions tab of the
[Technical SEO Audit template with questions](https://docs.google.com/spreadsheets/d/1JyYbeoXhBq3Y_heUsUXRaZHOmNPSTeNeUhRodWcZ53o/edit?gid=1652728870)
deterministically from one `technical-audit` JSON bundle, and publish a copy
of the template with each answer, one data tab per Yes answer and one draft
ticket per actionable answer.

## Background

The 96 template questions mixed polarity (yes = good / yes = bad), included
non-boolean and client-specific wording, and marked eleven questions "No"
that crawler_cli can answer. They are now a registry,
`templates/technical-audit-questions.json`, rendered for review as
`docs/technical-audit-questions.md`. Each entry is phrased so Yes means a
problem and carries an `issue_if` rule, why it matters, a group (crawl,
crawl+profile, best-practice, heuristic, supplied-input, external, run-gate),
required inputs, owning contract checks or a new detector, and default ticket
grade. Site-specific inputs live in a site profile
(`templates/site-profile.example.json`).

Only 12 of the 44 contract checks produce evidence today, and several hold a
different population from the question that names them (for example
`indexability-segmentation` currently holds only header-vs-meta robots
conflicts). A question is therefore answered only by an explicit per-question
answerer that knows exactly which rows belong to it; everything else is
Pending with the reason.

## Tasks

- [x] Question registry, site-profile example, loader/validator and the
  generated review document.
- [x] `technical-audit-questions --audit … --out …` runner: statuses
  Issue / Healthy / Needs validation / Pending, Yes/No answer, Q26 run gate
  that downgrades every crawl answer when the run is incomplete.
- [x] Answerers for Q13, Q14, Q16, Q21, Q22, Q23, Q26, Q30, Q32, Q39, Q94,
  accepting schema-v1 check IDs in older saved audits.
- [x] Draft Tickets rows reusing the ticket-language solution and acceptance
  text of the check that supplied the rows.
- [x] Publish Questions, Tickets and data tabs to a template copy; locate the
  Tickets header beneath the template's title block instead of writing at A2.
- [x] Fix `_placeholders` crashing on denominators of 1,000 or more.
- [ ] Publish one real run to a copy of the template and review it with the
  tech-audit-tickets skill.

## Definition of Done

- [x] Every registry question gets exactly one answer; no question without an
  answerer is reported Healthy.
- [x] A scope-limited answer with no rows is "No (partial)" / Needs
  validation, never Healthy.
- [x] Heuristic and review-qualified answers never produce a ticket
  automatically.
- [x] Runs offline from a saved audit JSON (no database or network).
- [ ] A published workbook from a real run has been reviewed.

Follow-up detector batches: 264 (stored HTML), 265 (site profile),
266 (render, probes and external).
