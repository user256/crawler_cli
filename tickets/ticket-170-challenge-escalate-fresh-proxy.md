# Ticket 170: Challenge escalate must take a fresh list-mode proxy

## Goal
Make HTTP→browser challenge escalation actually change egress for list-mode
proxy pools (or document that “fresh IP” only applies to gateway mode).

## Background (2026-07-22 wiring audit)

Ticket **074** promised escalate “through a fresh IP”. `_get_challenge_backend`
builds a new Playwright backend from `dataclasses.replace(...,
backend="playwright")` (`engine.py`). That backend creates a **separate** proxy
pool with the same ordered list. Both pools start at index zero, and list-mode
Playwright binds its first selection at context creation via `select("")` (see
also ticket **168**), so escalation deterministically tends to reuse the same
proxy despite not sharing the pool object.

Gateway mode rotates server-side per request, so it often “works by accident”.
List proxies commonly retry the same blocked egress IP against Cloudflare et al.

## Scope constraint (ticket 144, 2026-08-21)

Challenge escalation in this ticket is bounded to **one alternate-egress
attempt** for an authorised crawl that has already selected a proxy pool. The
purpose is to stop a single transient block from silently truncating an
authorised crawl, not to defeat bot management. If the pool cannot supply a
different live entry, the crawler logs that clearly and proceeds with whatever
result it has. This is never "keep trying identities until a 200": no loop over
identities or egress points, no CAPTCHA or WAF solving, and no escalation for
crawls that did not already configure a proxy pool. A later agent must not
"finish" this ticket as an evasion loop. See the "What This Is / What This Is
Not" section of `README.md` for the product boundary.

## Tasks
- Make the original HTTP request's selected proxy observable to the escalation
  coordinator, then exclude it when choosing from a list pool with another live
  entry. A second call to an independent pool's `select()` is not proof of a
  fresh proxy.
- Bind the chosen alternate proxy to a newly created/recycled browser context.
  Coordinate this with ticket **168** rather than adding a second incompatible
  context-selection mechanism.
- If the pool cannot provide a different proxy, log clearly and proceed.
- Document gateway vs list freshness in README / challenge module docs.
- Tests assert the actual proxy URLs differ when size > 1, not merely that
  `select()` was called twice; cover size 1 and all-alternates-cooled-down.

## Definition of Done
- Escalate path does not silently reuse the same list proxy when alternatives
  exist.
- Docs match behaviour.
- Automated fake-pool coverage.

## Status
proposed (Priority: **P2**) — challenge/proxy wiring; partial intent of
ticket **074**, not implemented; found in 2026-07-22 audit.
