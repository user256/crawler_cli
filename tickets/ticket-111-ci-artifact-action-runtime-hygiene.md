# Ticket 111: Restore CI coverage artifacts and supported action runtimes

**Status:** done (2026-07-15, PR #19)
**Priority:** P3 CI hygiene
**Related:** Tickets 056, 066, and 096

## Goal

Make the successful CI coverage output actually retrievable and remove action
runtime deprecation warnings without weakening any required check.

## Review finding

The merged `master` run passed both Python test jobs, PostgreSQL integration,
lint/typecheck/formatting, and real Chromium. Both matrix jobs nevertheless
reported that `.coverage` did not exist when `actions/upload-artifact` ran, so
the configured coverage artifacts were empty. GitHub also warned that the
current checkout/setup/cache/upload actions target deprecated Node.js 20 and
were being forced onto Node.js 24 by the runner.

## Tasks

- Emit an explicit, stable coverage artifact (for example XML plus the raw data
  file when useful) and fail the upload step when the expected artifact is absent.
- Keep the existing 60% coverage gate and both supported Python versions.
- Update GitHub-maintained actions to supported runtime generations after
  checking their current migration notes and input compatibility.
- Preserve the Playwright browser cache key and PostgreSQL service behaviour.
- Add a workflow-level assertion or artifact check that prevents another silent
  no-files upload.

## Definition of Done

Both Python matrix jobs publish a non-empty coverage artifact, every required CI
job remains green, and the workflow emits no deprecated-action-runtime or
missing-artifact annotation.

## Done

Shipped in PR #19: stable `coverage/` XML + data artifacts per Python matrix
job, assert-non-empty before upload (`if-no-files-found: error`), and
checkout/setup-python/cache/upload-artifact moved off deprecated Node 20
generations. Coverage gate and Playwright cache key unchanged; CI green on
the PR.
