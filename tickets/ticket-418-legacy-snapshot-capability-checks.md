# Ticket 418: Restore per-report snapshot capability checks after PR #118

## Problem and evidence

With `CRAWLER_CLI_TEST_DSN` set,
`tests/test_persistence_integration.py::test_technical_audit_marks_legacy_snapshot_reports_unavailable`
fails on the integrated tree with `UndefinedColumnError: column s.content_extracted does not exist`.

Commit `abb0210` made `technical-audit` skip any report whose SQL needs a
`page_run_snapshots` column the table lacks (a `capabilities_by_report` map
over `schema_capabilities`), so a database crawled by an older version
reports those checks as unavailable instead of crashing. The PR #118 merge
`72629af` replaced that with a five-entry `capability_by_report` map, so
reports such as `orphans`, `metadata-duplicates`, `hreflang-validation`,
`profile-indexability-pages` and `performance-pages` queried missing
columns again. `technical_audit_context` also ran two unguarded queries:
the Q81 TTFB drift query (`ttfb_seconds`) and the `locale_signature_count`
query from `55cdf4d` (`content_extracted`, `hreflang_json`). The Q39
`heading_link_count` query from `5038657` was already guarded on
`links_json`. The DB test itself still named check IDs from the old audit.

## Acceptance criteria

- [x] `schema_capabilities` reports every column a migration added to
      `page_run_snapshots` (`SNAPSHOT_OPTIONAL_COLUMNS` in `reports.py`).
- [x] One map, `TECHNICAL_AUDIT_REPORT_CAPABILITIES`, lists the columns each
      audit report needs; `_run_technical_audit` skips a report missing any.
- [x] The TTFB drift and locale-signature queries run only when their
      columns exist; the heading-link query keeps its `links_json` guard.
- [x] A non-DB test fails any query that names a column the fake table
      lacks, runs the audit with no newer column, and checks each report
      reads only its declared columns, so the map cannot drift silently.
- [x] The DB test drops every optional column and asserts current check IDs.

## Status

done (Priority: **P1**). Post-merge QA, 2026-10-07.

Fixed on `fix/postmerge-qa-integration` in `e889298`: restored the per-report
capability map in `reports.py` and applied it in `_run_technical_audit`;
guarded the TTFB drift and `locale_signature_count` queries; added
`tests/test_technical_audit_legacy_schema.py`; the DB test now drops all 21
optional snapshot columns. Full suite passes with and without a scratch
`CRAWLER_CLI_TEST_DSN`.
