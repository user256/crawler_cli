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
- [ ] Delete the old-audit modules, tests, docs and templates listed above (left to the operator).
- [ ] Rebuild the Rainbet bundle with the merged code and compare answers with the lineage's run.
- [ ] Write producers for the observation kinds that lost their probe (follow-up tickets).

## Status

in progress (Priority: **P0**). Source: master reconciliation, 2026-10-06.
