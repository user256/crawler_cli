# Ticket 100: Extend Obscura installer test coverage and verify pinned digests

## Goal
Lock in the security guarantees implemented in ticket 094 with explicit tests
for every rejected archive-member class, and confirm the pinned SHA-256 digests
match the real published release assets.

## Background
Ticket 094 (PR #11) hardened `install-obscura` with pinned-digest verification,
strict per-member validation, staged extraction, and atomic install with
rollback. Review approved it as MERGE (security logic sound, 42 tests passing).
Two non-blocking gaps remain: the test suite proves some rejection classes but
not all the code defends against, and the pinned digests could only be checked
against locally-built archives (tests monkeypatch the digest), not the real
GitHub assets.

## Tasks
- Add explicit rejection tests for the member classes the extractor already
  guards but does not yet cover: tar symlink (`SYMTYPE`), tar absolute-path
  member, tar device/FIFO member, and a zip entry with a symlink mode bit.
  (Existing tests cover the zip traversal and tar hardlink cases.)
- One-time: cross-check each of the 5 pinned `v0.1.8` platform-asset SHA-256
  digests against the published `h4ckf0r0day/obscura` release assets and record
  the verification, so the pins are trusted, not assumed.
- Optional: add a regression asserting the double `_validate_version` call
  (install site + `_release_url`) is intentional or dedupe it.

## Definition of Done
- Every archive-member rejection branch has a direct test.
- Pinned digests are confirmed against the real published assets.

## Status
in_progress (Priority: **P3 security**) — claimed by `agent/ticket-100-obscura-installer-test-hardening`; test hardening for ticket 094; found in
2026-07-15 PR review.
