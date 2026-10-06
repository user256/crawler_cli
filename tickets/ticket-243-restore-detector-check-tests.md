# Ticket 243: Repair tests broken by the v3 `checks` projection

## Goal

The full test suite passes after `audit["checks"]` became the v3 control list
and detector rows moved to `audit["detector_checks"]`.

## Background

Commit 6496fba left five tests failing that passed on its parent:

- `tests/test_live_rechecks.py::test_historical_failures_are_candidates_until_rechecked`
- `tests/test_live_rechecks.py::test_recovered_targets_are_removed_from_client_failures_with_provenance_retained`
- `tests/test_report_cli.py::test_technical_audit_writes_deterministic_bundle` (expects schema `/2`)
- `tests/test_report_cli.py::test_technical_audit_skips_reports_requiring_absent_legacy_columns` (`KeyError: 'redirect-chains'`)
- `tests/test_structured_data_audit.py::test_unknown_feature_and_recommendation_candidates_never_enter_client_action_log`

## Tasks

- Point detector-ID lookups at `audit["detector_checks"]` and update the
  schema version expectation to `crawler-cli/technical-audit/3`.
- Where a test's intent is about the client-facing contract, also assert on
  the corresponding v3 control in `audit["checks"]`.
- Do not change production code.

## Definition of Done

- The five tests pass; no other test regresses.
- Scope: the three test files above only.
