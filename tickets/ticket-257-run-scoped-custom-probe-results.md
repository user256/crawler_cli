# Ticket 257: Persist run-scoped custom probe results for generic GUI reporting

## Goal

Store the actual outcome of every bounded host/protocol, URL-variant and
synthetic/fictitious-URL probe against the crawl run that requested it, so a
database-backed GUI can render the same evidence for any crawl without reading
an export, replaying a request, or inferring a probe from URL provenance.

## Background

`rainbet-20260925-v4` has ordinary crawl snapshots and source inventory, but
no `custom_check` source rows or persisted probe outcomes. `url_sources` can
say where a URL came from; it cannot prove that a custom check was attempted
or record its status, redirect chain, control URL, timing, or verdict.

The current variant/soft-404 helper APIs return in-memory observations for a
technical audit. A normal crawl does not persist a generic run-scoped custom
probe result for the GUI to read. Backfilling an old run from backlink/archive
exports would falsely label source URLs as crawler checks and is explicitly
out of scope.

This extends tickets 193 and 236; it does not replace their evidence and
verdict rules.

## Tasks

- Add a run-scoped custom-probe result model and migration, keyed by a stable
  check ID and crawl run ID. Keep one attempted URL, optional control URL,
  final URL, status, redirect chain, redacted response evidence, elapsed time,
  observed timestamp, coverage state and verdict/qualification per result.
- Persist outcomes from the explicit bounded server-configuration probes:
  HTTP/HTTPS, www/non-www, slash/suffix/case variants, and the synthetic
  nonexistent-path/soft-404 check. Persist denied, blocked, timeout and
  unavailable states too; absence of a successful response is still evidence.
- Associate probe execution with an existing run without reopening or
  mutating the ordinary crawl frontier. Probe storage must work for any run,
  including a completed one, and must not create fake page snapshots.
- Provide one read API/store query that returns only results persisted for the
  selected run. It must never fall back to `url_sources`, backlink imports,
  Archive.org sources, exports or URL-shape inference.
- Make technical-audit JSON/Sheets and the database table agree on check IDs,
  coverage counts and qualification. The GUI is a generic read-only consumer
  of this database contract, not a second collector.

## Definition of Done

- [ ] A completed run with no custom-probe rows renders an explicit
  “not recorded” state; URLs in its source inventory do not appear as checks.
- [ ] An explicit probe session stores one queryable row per attempted check,
  including HTTP/www, a case variant and a fictional URL, with the actual
  outcome and run ID.
- [ ] Redirect, 404, timeout/denial and successful-response fixtures retain
  distinct evidence and coverage states; no source import is reclassified as
  a probe.
- [ ] The selected-run database query produces the same stable result set for
  a CLI/report consumer and a generic GUI consumer, with no network access.
- [ ] Migration, persistence integration and GUI-contract tests prove that
  two runs cannot see each other’s probe results.

## Status

proposed (2026-09-28, Priority: **P1**) — Rainbet exposed the missing
run-scoped persistence contract. No Rainbet data was backfilled or re-fetched.
