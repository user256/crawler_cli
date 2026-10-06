# Ticket 218: Generate a deterministic redirect map for failing URLs

## Goal

Produce a redirect-map artifact that proposes targets for failing URLs using
explicit, testable rules, and flags redirects that land on a failure.

## Background

The rainbet audit needed a hand-built map for 3,850 URLs. Safe rules covered a
useful share: slug unchanged under a new path (`/casino/roulette/<game>` →
`/casino/live/<game>`), dead subdomain to the same path on the apex, and unique
slug matches. String similarity produced plausible but wrong pairs
(`sweet-bonanza-dice` → `sweet-bonanza`, a different game). 138 archived URLs
already redirected straight into a 404. Ticket 186 reports redirect targets but
no map and no redirect-into-failure check.

## Tasks

- Implement ordered rules, each with a named basis: exact path on the
  canonical host, locale-prefix strip, configured path rewrites supplied by the
  analyst, subdomain-to-apex same path, unique slug match.
- Allow similarity candidates only with the basis `review-required`; never
  present them as recommendations.
- Only propose a target that is a live, indexable, self-canonical 200 in the
  run or its recheck.
- Detect and report redirects whose final hop is 4xx/5xx or a DNS failure.
- Order rows by backlink weight (ticket 217) when present.
- Emit CSV and a Sheets-ready tab.

## Definition of Done

- Fixtures cover every rule, a similarity candidate, and a redirect into a 404.
- No proposed target fails the 200/indexable/self-canonical condition.
- The rainbet run reproduces the rule-based suggestions and marks the Sweet
  Bonanza pair as review-required.
