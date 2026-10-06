# Ticket 408: Port the question runner and stream collectors onto master's audit contract

## Goal

Port the question runner and stream collectors onto master's audit contract.

## Problem

`feature/technical-audit-183` (and its merged tip `feature/technical-audit-streams`, 5663419) carries the question registry (Q1-Q104), the question runner, the observation bundles and the Stream A/B/C collectors. It cannot be merged textually: master's `technical_audit.py` (3,049 lines, 20 report collectors, v3 control projection) and the lineage's (1,168 lines, 25 collectors, `question_inputs`) are add/add on the same path, as are `google_sheets.py`, `tests/test_technical_audit.py` and `tests/test_google_sheets.py`; `reports.py`, `__main__.py` and `persistence.py` conflict as content.

On the same Rainbet run (rainbet-20260925-v4) the two produce the same 44 check ids but different evidence: master answers `unavailable` for 20 checks the lineage computes from stored HTML (canonical-declarations, hreflang-html-http, hreflang-noindex, indexability-segmentation, internal-link-targets, orphan-candidates, response-status-and-redirect-history, soft404-error-routes …), master rows carry no `kind` field and no `coverage_state`, and 12 checks have findings on both sides with different row shapes (image-markup, metadata-basics, metadata-duplicates-aliases, internal-authority, near-duplicate-content, parameter-and-faceted-controls …). The runner's answerers filter rows by `kind` and read `question_inputs`, so pointing it at master's bundle would silently answer Healthy.

## Evidence

Scratch comparison 2026-10-06: `rainbet-audit-manual-review.json` (master-side port, 52 s) versus `b2-audit.json` (lineage, 8 min); 28 of 44 checks share evidence keys only because both are empty.

## Tasks

- [ ] Per check, choose master's collector or the lineage's (or merge them) and record the evidence-row contract; the lineage's `_check` keys (`coverage_state`, `eligible_count`, `kind`) must survive.
- [ ] Add `question_inputs` and `source_coverage` to master's `build_technical_audit`; port the lineage's `reports.py` collectors (stored-HTML single pass, profile pages, crawl depth, performance, empty anchors) as additive methods.
- [ ] Move the new modules as files: technical_audit_questions/evidence/observed_answers/tickets/inputs, audit_observations, audit_html_signals, the seven pure audit modules, backlinks, templates and docs, skills/tech-audit-tickets.
- [ ] Re-run the 183 lineage's test suite against the ported bundle; re-run the Rainbet smoke and compare answers to `rainbet-answers-integ.json`.
- [ ] Reconcile ticket numbering: the lineage reserved 240-246 and 263-399 for different tickets than master's 240-243 and 264-266.

## Definition of Done

- [ ] `technical-audit-questions` runs on a master-built bundle with the same answers it gives today on the lineage's bundle, and the full suite is green.

## Status

proposed (Priority: **P1**). Source: master reconciliation, 2026-10-06.
