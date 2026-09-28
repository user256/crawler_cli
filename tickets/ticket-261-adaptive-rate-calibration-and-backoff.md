# Ticket 261: Adaptive rate calibration and origin crawl-budget pressure detection

## Status and priority

Proposed — P2. Owner: unassigned. Extends per-host rate limiting (Ticket 224) and crawl budget/safety checks (relates to question Q81).

## Goal

Provide a pre-crawl latency calibration probe and an adaptive runtime rate limiter that continuously measures origin response time (TTFB) and HTTP backoff signals (429 Too Many Requests, 503 Service Unavailable, `Retry-After`), automatically throttling crawl concurrency and reporting crawl-budget pressure metrics.

## Background

Technical SEO audits of production or staging platforms risk degrading origin server performance or triggering CDN rate limits (e.g. Cloudflare, AWS WAF). Hard-coded concurrency settings either crawl too slowly on resilient architectures or overwhelm delicate origins, producing false 429/500 errors and distorted performance measurements.

While Ticket 224 established a coherent per-host rate limit, `crawler_cli` lacks an automated calibration phase to discover safe baseline concurrency and dynamic runtime backoff when origin degradation is observed.

## Tasks

### Pre-Crawl Calibration Probe
- Before launching full crawl workers, issue a short sequence of bounded test requests (e.g. 5–10 requests across root and sample assets) to establish:
  - Baseline TTFB (median and p95)
  - Presence of rate-limiting headers (`RateLimit-Limit`, `RateLimit-Remaining`, `X-RateLimit-Reset`)
  - Origin HTTP server / CDN identification (Cloudflare, Fastly, Akamai, Nginx, etc.)
- Calculate a recommended initial worker concurrency and request delay.

### Dynamic Runtime Backoff Controller
- Monitor rolling TTFB across active crawl workers:
  - If rolling median TTFB exceeds 2.5x baseline TTFB, trigger an automatic concurrency throttle (reduce concurrency by 50% or insert an inter-request delay).
  - If a 429 or 503 response is encountered, respect `Retry-After` header if present (clamped to a safe max bound, e.g. 60s) or apply exponential backoff.
- Gradually recover concurrency when rolling TTFB normalizes over a sustained window (e.g. 50 successful responses).

### Crawl-Budget & Server Pressure Reporting
- Aggregate crawl safety statistics into the crawl summary and technical audit report:
  - Total rate-limit encounters (429 count)
  - Origin throttled duration (seconds spent backed off)
  - Baseline vs crawl-peak TTFB degradation curve
  - Recommended safe concurrency guidelines for future audits

## Definition of Done

- [ ] Pre-crawl calibration measures baseline TTFB and sets initial concurrency.
- [ ] A mock server responding with 429 + `Retry-After: 2` pauses requests and halves concurrency without dropping URLs.
- [ ] High-latency mock responses trigger automatic rate throttling before origin failure.
- [ ] The final crawl report outputs explicit crawl-budget pressure metrics and throttling history.
- [ ] Unit tests pass with simulated mock latency curves.
