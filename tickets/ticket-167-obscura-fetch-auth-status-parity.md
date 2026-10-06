# Ticket 167: ObscuraFetch auth/cookie/status parity (or hard fail)

## Goal
Stop `--obscura-fetch` from silently dropping auth/cookies/headers and always
reporting HTTP 200 on success, either by wiring what the binary supports or by
failing closed when unsupported options are set.

## Background (2026-07-22 wiring audit)

`ObscuraFetchBackend._build_argv` only passes stealth / proxy / UA / timeout
(`backends.py`). No Cookie, Authorization, or other `request_headers`. The
success path hardcodes `status=200`.

Challenge escalation treats `ObscuraFetchBackend` as a browser backend
(`engine._is_browser_backend`), so there is no further escalate — and status-based
circuit-breaker / challenge logic sees a fake 200.

Operators combining `--obscura-fetch` with `--auth-*` / `--cookie*` get an
unauthenticated fetch that looks successful.

## Tasks
- Document the supported surface for `--obscura-fetch`.
- Wire cookies + auth/headers where the binary allows, **or** hard-error at
  config/CLI time when those options are set with `--obscura-fetch`.
- Prefer surfacing the real main-document status from the binary/payload. If it
  is genuinely unavailable, represent that as an explicit unknown/error
  outcome; merely changing `200` to `0` is insufficient because the engine
  currently treats non-429/non-5xx values as circuit-breaker success and can
  still count an HTML response as crawled content.
- Tests for rejection or forwarding of auth/cookies, plus engine-level status
  semantics (unknown status cannot record breaker success or a successful
  crawled page; a real 4xx/5xx is retained when available).

## Definition of Done
- Unsupported auth/cookie combinations cannot silently succeed.
- Status reported to the engine is honest.
- Unknown status is not counted as a successful fetch or circuit-breaker
  success, and does not silently become a normal page snapshot.
- Docs and help text match behaviour.
- Tickets **043** / **129** (CDP Playwright path) remain out of scope except
  where shared config validation helps.

## Status
proposed (Priority: **P1**) — backend parity / correctness; found in 2026-07-22 audit.
