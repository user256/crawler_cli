# Ticket 261: Adaptive rate calibration and crawl-budget pressure detection

**Status:** Concluded with remediation 266 — merged to `master` after review on 2026-09-29.
**State:** Needs closing
**Priority:** P2
**Module:** engine

## Delivered

- Opt-in pre-crawl TTFB/rate-header calibration and conservative starting-rate recommendations.
- Per-origin adaptive concurrency, `Retry-After`/exponential backoff, recovery, and bounded pressure-history reporting.
- Unit coverage for calibration, throttling, retries, recovery, and serialised output.

## Review note

The emitted reasons can duplicate `rate_limit_remaining_low`; this presentation-only defect is isolated in ticket 266.

## Review evidence

`tests/test_adaptive_rate.py` passed; full integrated suite: 1,615 passed, 60 skipped.
