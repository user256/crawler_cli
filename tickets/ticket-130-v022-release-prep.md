# Ticket 130: Prepare an immutable crawler-cli 0.2.2 release

## Goal

Prepare, but do not publish, the first safe patch release containing the
reviewed `portal-url-policy/1` hook merged in PR #51.

## Background

`v0.2.1` already exists as an annotated remote tag, but it points to the
closed, unmerged PR #50 and is not an ancestor of `master`. It has no GitHub
Release or attached artifacts. It must never be moved, reused, or published.

The reviewed replacement hook is on `master` in PR #51. It remains HTTP-only:
initial URL, HTTP redirects, and sitemap fetches can be policy-authorized and
pinned; browser navigation, browser subresources, and live comparisons are
explicitly unsupported. This release must describe that boundary accurately
without changing Portal or enabling any worker.

## Tasks

- Bump package metadata to `0.2.2` and finalize the matching changelog entry.
- Update the crawler-side Portal contract with the truthful HTTP-only policy
  capability matrix and immutable release evidence requirements.
- Document the release operator's exact artifact checks: clean build, Twine
  metadata validation, wheel-content inspection, SHA-256 recording, CI run,
  annotated tag, and attached wheel/sdist.
- Build and validate the candidate locally. Open a draft PR only.

## Non-goals

- Do not create, move, or push a tag.
- Do not create a GitHub Release, upload to PyPI/an internal index, or attach
  public release assets.
- Do not change Portal, its crawler pin, its worker enablement, or Migration
  Manager capability requirements.
- Do not claim browser or live-comparison connection guarding.

## Definition of Done

- A draft PR contains only this release-preparation documentation/metadata and
  ticket-register work.
- `python -m build` and `twine check dist/*` pass in a clean build directory.
- The wheel excludes tests, tickets, and run artifacts; the source archive
  follows the documented packaging policy.
- Focused policy/contract tests pass, and no tag/release/upload has occurred.

## Status

in review (2026-07-29) (Priority: **P0 release safety**) — drafted after the
unusable `v0.2.1` tag was discovered. The release action remains deliberately
blocked until this PR is merged and a separate operator performs the documented
immutable-artifact steps.
