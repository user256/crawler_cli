# Ticket 181: Distinguish rate limiting from bot challenges

## Goal

Treat HTTP 429 as rate limiting with actionable crawl-throttle guidance, not
as a generic fingerprinting/challenge escalation signal, and count affected
URLs rather than retry attempts in challenge summaries.

## Background

Challenge detection includes 429 in several vendor signatures and engine
escalation can therefore select the browser path after a rate limit. That does
not reduce request pressure and makes operators think they need a different
fingerprint. `CrawlJobResult.challenge_blocked_count` also derives from result
rows, so retries/escalations can inflate the apparent number of distinct URLs
blocked.

## Tasks

- Add a typed rate-limit outcome carrying status, `Retry-After` when present,
  host, and the affected requested URL. It must bypass browser escalation and
  advise lowering per-host concurrency/rate limit.
- Preserve a genuine vendor challenge that happens to use 429 only when strong
  challenge evidence is present; document the precedence.
- Expose separate, deterministic counts for distinct rate-limited URLs,
  distinct challenge-blocked URLs, and attempts/retries. Do not use a counter
  change to hide persistence or circuit-breaker facts.
- Update summary, saved output/artifact, logs, and relevant GUI presentation.

## Definition of Done

- Plain 429 is rate limited, never escalated to browser, and gives throttle
  guidance.
- 429 with strong challenge evidence retains the documented challenge class.
- Repeated retries for one URL count once in URL-level challenge/rate-limit
  totals; attempt totals remain available separately.
- Tests cover 429, vendor 429, retry accounting, and summary/artifact output.

## Status

proposed (2026-09-23, Priority: **P2**) — crawl-control correctness; found in Shopify crawl review.
