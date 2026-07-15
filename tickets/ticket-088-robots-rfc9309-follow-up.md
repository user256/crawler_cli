# Ticket 088: Close remaining robots.txt RFC 9309 and configuration gaps

## Goal
Make the advertised default robots enforcement correct for real URLs, user-agent
groups, temporary failures, and configured network routes.

## Background
Ticket 050 fixed several robots issues, but the current runtime still has gaps:

1. A 5xx/network failure calls `mark_failed()`, while `check()` returns
   `allowed=True` for failed domains. This contradicts the nearby comment saying
   failures are conservatively treated as fully disallowed and makes default
   enforcement fail open.
2. `check()` passes only `parsed.path` to rule matching. Query-sensitive rules
   such as `Disallow: /*?` work in direct unit tests but not during a real crawl.
3. Consecutive `User-agent` lines are not represented as one group; directives
   attach only to the last declaration.
4. Robots selection uses `config.user_agent`, not `user_agent_for(url)`, so
   per-domain `--ua` crawls may fetch as one bot and evaluate rules as another.
5. The dedicated aiohttp fetch does not consistently use proxy-pool selection,
   proxy auth, and the configured request path.

## Tasks
- Choose, document, and implement a standards-aligned temporary-failure policy;
  do not retain the current comment/behavior contradiction.
- Match robots rules against the path plus query component as required.
- Parse consecutive UA declarations into a shared group and combine repeated
  matching groups correctly.
- Use the effective per-URL user agent for fetching, rule selection, and
  `Crawl-delay` lookup.
- Route robots requests through the effective proxy configuration without
  leaking target-site credentials or cookies across hosts.
- Add end-to-end policy-cache tests, not only direct `_RobotsRules.check()` tests.

## Definition of Done
- 5xx/network behavior is explicit, internally consistent, and tested.
- Query rules and multi-UA groups work through `RobotsPolicyCache.check(url)`.
- The UA evaluated against robots is the UA sent for that URL.

## Status
done (2026-07-15, PR #22) (Priority: **P0**) — fail-closed 5xx/network, path+query matching, consecutive UA groups, `user_agent_for(url)`, proxy-routed robots fetch; compliance/politeness; found in 2026-07-15 audit.

