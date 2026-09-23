# Ticket 182: Discover a supported system Chromium for Playwright

## Goal

When Playwright's bundled Chromium cannot run on the host, locate a supported
system Chromium executable automatically and report exactly which browser was
chosen.

## Background

Ubuntu 26.04 installations may provide Chromium through `/snap/bin/chromium`
while the bundled Playwright browser is unavailable or unsupported. The CLI
already supports explicit `--playwright-executable-path`, but ordinary `--js`
fails before operators learn the usable system path.

## Tasks

- On a bundled-browser launch failure only, search a small documented,
  platform-aware allowlist (including `/snap/bin/chromium` on Linux); validate
  that the candidate is an executable Chromium-family binary before launch.
- Preserve explicit `--playwright-executable-path` and `--playwright-channel`
  precedence; never replace an explicit choice or silently fall back after an
  explicit path fails.
- Bound fallback to one candidate/launch attempt per configuration, with clear
  logs and structured runtime evidence identifying bundled versus system mode.
- Keep managed Obscura/CDP modes out of this fallback path.

## Definition of Done

- A mocked bundled-browser failure falls back to an executable system Chromium
  candidate and reports it.
- Explicit path/channel precedence and no-candidate failure are covered.
- The fallback does not apply to CDP/Obscura and cannot loop through binaries.
- CLI help/docs explain the automatic behaviour and override.

## Status

proposed (2026-09-23, Priority: **P3**) — runtime portability; found on Ubuntu 26.04.
