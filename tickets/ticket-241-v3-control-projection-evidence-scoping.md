# Ticket 241: Stop v3 control projection from fanning one detector into several tickets

## Goal

A detector result may only support a v3 control with the evidence that belongs
to that control, and a control may only pass when its contract evidence exists.

## Background

Review of commit 6496fba found that `project_v3_controls` in
`src/crawler_cli/technical_audit_contract.py` copies a detector's full status,
counts and evidence into every control mapped to it in `CONTROL_DETECTORS`.

- One `metadata-and-locale` finding (3 URLs, missing title) produced `finding`
  on metadata-basics, metadata-duplicates-aliases, content-quality and
  locale-html-lang. Three are ticket-eligible, so the client would receive
  three tickets with identical URLs under different problem labels.
  `rendered-mobile-and-resource-evidence` feeds 5 controls and
  `url-variants-and-soft-404` feeds 3.
- Controls pass without their contract evidence: `locale-redirects` requires
  authorised geo/locale probe evidence but passes on the URL-variants detector;
  `mobile-rendering-parity` passes without a mobile render;
  `crawl-depth-distribution` passes from the authority inventory.
- Required detectors that are absent are silently dropped, so a control can
  pass on a subset (`rendered-robots-links` passed with only one of its two
  detectors).
- `tested_count` and `denominator` are summed across detectors that examine
  the same population, inflating the client's Tested and Population columns.
- The ticket-language file already defines the blocking qualification
  `combined_v2_detectors`, but the projection never emits it.

## Tasks

- For each shared detector, scope evidence to the control by issue type /
  candidate type where the detector's evidence rows carry one; recompute
  `affected_count` from the scoped rows. A control with no scoped rows from a
  `finding` detector must not become `finding`.
- Where evidence cannot be scoped, emit a blocking qualification (reuse
  `combined_v2_detectors` or add a documented code in
  `templates/technical-audit-ticket-language.json`) so no client ticket is
  produced.
- A control whose contract evidence is not collected by any mapped detector
  (at least locale-redirects, mobile-rendering-parity, crawl-depth-distribution;
  review every mapping) must be `unavailable` or `partial`, never `pass`.
- Treat a missing required detector as `unavailable` evidence for that
  control.
- Use the maximum (or the shared population), not the sum, for `tested_count`
  and `denominator` when detectors test the same population; document the rule.

## Definition of Done

- A test: one metadata finding yields at most one ticket-eligible control.
- A test: every control's pass requires every mapped detector to be present
  and passing, and the listed evidence-gap controls never pass.
- A test: merged denominators are not double-counted.
- Scope: `src/crawler_cli/technical_audit_contract.py`,
  `templates/technical-audit-ticket-language.json`, a new
  `tests/test_technical_audit_contract.py`. Do not edit `technical_audit.py`.
