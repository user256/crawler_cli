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
`done` (2026-07-15) — Priority: **P3 security**. Claimed and delivered on
`agent/ticket-100-obscura-installer-test-hardening`.

## Delivery notes
- Added direct rejection tests in `tests/test_obscura.py` for:
  - tar symlink (`SYMTYPE`)
  - tar absolute-path member
  - tar character-device member
  - tar FIFO member
  - zip entry with Unix symlink mode bit (`S_IFLNK` in `external_attr`)
- One-time digest cross-check (2026-07-15): downloaded all five published
  `v0.1.8` assets from `https://github.com/h4ckf0r0day/obscura/releases/download/v0.1.8/`
  and compared SHA-256 to `_ASSET_SHA256`. **5/5 matched**; fail-closed verify
  left unchanged.

  | Asset | Pinned digest (verified) |
  | --- | --- |
  | `obscura-aarch64-linux.tar.gz` | `58602b8293a93caa6fdac98a2868292c9a91ecab86d835f9bd20361ac7e48ea0` |
  | `obscura-aarch64-macos.tar.gz` | `dfa84fa20e0e33c7b1af9ded190cdbf928c5a52a3edb308600595e11455ee7bb` |
  | `obscura-x86_64-linux.tar.gz` | `e54d07054047d4180247f03bea08d1bd724ef1859829331a433da972f973988b` |
  | `obscura-x86_64-macos.tar.gz` | `34cbeb9706f0af95de7fd6693346a3f1d601b35ddc3c623f060a363e9adac206` |
  | `obscura-x86_64-windows.zip` | `5bcbf6789897f7e6d67a160f45510cf06e6d44a966357aa5f8b238961bac0b53` |

- Optional double `_validate_version` cleanup left untouched (non-blocking).
