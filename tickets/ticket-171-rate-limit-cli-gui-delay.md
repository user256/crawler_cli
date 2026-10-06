# Ticket 171: Wire CLI/GUI rate limit (`delay` → `rate_limit_per_second`)

## Goal
Expose `CrawlConfig.rate_limit_per_second` on the CLI and map the GUI’s Delay
control to it, ending the “no crawl-side equivalent” lie.

## Background (2026-07-22 wiring audit)

`CrawlConfig.rate_limit_per_second` (default 5.0) drives `RateLimiter` via
`min_interval_seconds` (`config.py` / `engine.py`). There is no `--rate-limit*`
flag in `__main__.py`. The GUI Configuration modal stores `delay`
(`app.js` / `index.html`), but `startLiveCrawl` omits it from the POST payload,
`CrawlSpec` has no delay field, and `build_crawl_argv` documents it as having
“no crawl-side equivalent” (`crawler_gui/server.py`). README examples show
library-only rate limiting.

The adjacent GUI concurrency control is labelled “URLs per second” even though
it maps to `--concurrency` (simultaneous workers), which further blurs throughput
and request-rate semantics.

Operators tuning politeness from the GUI get a silent no-op; library callers
can set the field, CLI users cannot without code.

## Tasks
- Add a CLI flag (e.g. `--rate-limit-per-second`; 0 disables) wired to
  `CrawlConfig.rate_limit_per_second`, with validation via existing numeric
  helpers.
- Wire the complete GUI path: configuration state → `startLiveCrawl` JSON
  payload → validated `CrawlSpec.delay` → `build_crawl_argv` → CLI config.
- Keep the GUI's stated unit, seconds between requests: positive `delay` maps to
  `rate_limit_per_second = 1 / delay`; define `delay=0` as rate limiting disabled
  and avoid division-by-zero/empty-field ambiguity.
- Relabel the concurrency control as concurrent workers/requests rather than
  “URLs per second”.
- Update README + GUI README.
- Test the full GUI request/payload/spec/argv path, zero and fractional delay,
  and CLI config build—not only direct construction of a `CrawlSpec`.

## Definition of Done
- CLI can set the engine rate limiter without library code.
- GUI Delay changes crawl politeness.
- Docs and help match the mapping.

## Status
proposed (Priority: **P2**) — CLI/GUI wiring; found in 2026-07-22 audit.
