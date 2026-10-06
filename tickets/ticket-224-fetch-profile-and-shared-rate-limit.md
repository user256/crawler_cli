# Ticket 224: Coherent browser fetch profile and a shared live-check rate limit

## Goal

Make impersonated fetches present a consistent browser identity by default,
and keep all live-check modules of one audit under a single per-host budget.

## Background

On rainbet.com (Cloudflare) `--impersonate firefox` still sent the default
`crawler_cli/0.1` User-Agent and every request got 403 until a matching
Firefox UA was passed by hand. A Chrome fingerprint was blocked outright. Later,
live checks running beside the crawl pushed the host into HTTP 429 for 214 URLs.
Each technical-audit live module (185, 192, 193, 196, 211) has its own limits
but no shared per-host budget.

## Tasks

- When `--impersonate` names a browser and no UA is given, send that browser's
  matching default User-Agent. Warn when an explicit UA contradicts the
  impersonated fingerprint. Coordinate precedence with ticket 169.
- Add one per-host token bucket shared by every live-check module in a
  `technical-audit` invocation, with a configurable rate and backoff on 429 or
  `Retry-After`.
- Record 429 outcomes as `rate-limited, unverified`, never as failures
  (consistent with 181 and 207).
- Confirm the live modules use the same fetch profile as the crawl, or report
  the difference in the check registry.

- The live modules hard-code their own identities
  (`crawler_cli-audit-recheck/1`, `crawler_cli-technical-audit-external-check/1`)
  or use the default `crawler_cli/0.1` over aiohttp. On rainbet.com the
  conditional-GET pass on master found 5/5 ordinary responses unavailable.
  Let every live module take the same fetch profile as the crawl, and record
  the profile in the check registry.
- Retain per-URL live responses (status, final URL, challenge detection) in
  the output; the conditional-GET pass kept only its coverage summary, so the
  cause could not be confirmed from the audit file.

## Definition of Done

- A fixture server rejecting mismatched UA/fingerprint pairs accepts the
  default profile.
- Concurrent live modules never exceed the shared rate in a timing test.
- 429 responses never appear in failure totals.
