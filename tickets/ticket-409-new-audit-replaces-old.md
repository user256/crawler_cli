# Ticket 409: Replace the old technical audit with the three-stream audit

## Goal

Land the question-runner audit built in Streams A, B and C (tickets 263-399) on
master in place of the previous `technical-audit` pipeline, keeping every
non-audit feature master gained since the lineage branched.

## What changed

- `technical_audit.py`, `technical_audit_tickets.py`, `google_sheets.py`,
  `skills/technical-seo-audit/SKILL.md` and `templates/technical-audit-ticket-language.json`
  are the lineage's versions. The question registry, runner, observation bundles,
  Stream A/B/C collectors and their tests arrive as new files.
- The crawler core keeps master's data model: crawl-artifact schema v9, link
  `rel` lists (the lineage's `follow` flag is derived from `rel`), the
  redirect-chain, directive-evidence and canonical-evidence columns.
- `reports.py` is the lineage's, plus master's `orphan_pages` (known-URL aware,
  used by `reconcile-sources`), `source_reconciliation_inventory`,
  `current_site_join_inventory`, `accept_language_probes` and the link-graph helpers.
- The three features built inside the old audit after the lineage branched are
  re-attached as observation producers for the new runner
  (`technical-audit-observations --ai-governance`, `--probe-accept-language`,
  `--tls-probe`; adapters in `audit_observation_adapters.py`), feeding Q96, Q25
  and Q63. The preload list and OCSP stapling are still not observed, so Q63
  stays below Healthy from stored headers alone.

## Removed capabilities (old audit only; retrievable from master before this merge)

`technical_audit_contract.py`, `manual_review_questions.py`,
`structured_data_audit.py`, `performance_audit.py`, `rendered_audit.py`,
`url_variant_audit.py`, `external_link_checks.py`, `live_rechecks.py`, the v1/v2
Sheets templates and the ticket-register publisher, with their tests and docs.
The live rechecks, URL-variant, rendered-mobile and external-link probes have no
producer for the new runner's `host-probe`, `utility-path-probe`,
`external-link-recheck`, `render-trace` and `mobile-render` kinds yet.

## Tasks

- [x] Merge, resolve, re-attach, suite green (old-audit test files excluded).
- [x] Deleted the old-audit modules, tests, docs and templates listed above (commit 2ca2e9b); full suite 1866 passed, 60 skipped with nothing ignored.
- [x] Rebuilt the Rainbet bundle with the merged code (11 min, 1.3 GB peak; the lineage's run peaked at 3.9 GB). 104 answers: Issue 1, Needs validation 22, Healthy 1, Pending 80 against the lineage's 1/20/1/82. Only Q13 (orphans now graph-based: 8,761 of 10,852 vs 7,716), Q91 (500 confirmed empty anchors over 627,923 internal anchors, previously Pending) and Q63 (answered from `--tls-probe`: rainbet.com sends no Strict-Transport-Security header) changed.
- [ ] Write producers for the observation kinds that lost their probe (follow-up tickets).

## Status

Merged in PR #118 at `72629af` (Priority: **P0**); producer follow-ups remain open. Post-merge QA reproduced the saved Rainbet answer summary exactly and filed tickets 410–417; see [QA report](./qa-new-audit-2026-10-06/README.md).
