# Ticket 215: Do not classify a 200 page embedding Turnstile as a challenge interstitial

## Goal

`detect_challenge()` must only report a Cloudflare interstitial when the
response itself is a challenge, never because a normal page loads the
Turnstile widget script for its own login or registration form.

## Background

On 2026-09-25 a rainbet.com crawl recorded 399 real HTTP 200 pages as
`blocked by bot-challenge (cloudflare)` and stored no content for them. The
pages simply include
`https://challenges.cloudflare.com/turnstile/v0/api.js` in their markup. That
string sits in the `cf_strong` marker list in `challenge.py`, which is treated
as sufficient on its own regardless of status. The crawl had to be re-run with
`--no-challenge-detection`, which also disables legitimate detection.

## Tasks

- Move `challenges.cloudflare.com/turnstile` (and any other widget-embed
  marker) out of the status-independent strong list. Require a challenge
  status (403/503/429), a `cf-mitigated: challenge` header, or an interstitial
  title such as `Just a moment...` before a 200 body can be called a challenge.
- Add a fixture: 200 HTML with a Turnstile script tag and ordinary content
  must return `None`; a 403 `Attention Required` body must still return
  `cloudflare`.
- Log the matched marker and status in the engine warning so a future false
  positive is diagnosable from the crawl log.

## Definition of Done

- The rainbet fixture above passes; existing challenge fixtures still pass.
- A crawl of a Turnstile-embedding site stores content for its 200 pages
  without `--no-challenge-detection`.
