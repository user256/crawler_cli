# Ticket 146: Authorised exposure inventory (no exploit payloads)

## Goal

Give an authorised technical-SEO crawl a small, deterministic **exposure
inventory**: non-production host DNS/HTTP, soft-404 fingerprint, published
error/test URLs in the sitemap set. Observe and report. Do not fuzz, inject,
or authenticate past access controls.

## Background (2026-08-21)

Definition (2) of “adversarial crawler” (security testing) includes exposed
endpoints and unsafe behaviour. `crawler_cli` does not meet that description
and must not grow a pentest payload suite (ticket **144**).

The sapiens and Timber Living audits still had to do, by hand, the subset that
*is* crawler work:

- Probe `dev.` / `staging.` / `test.` / `preview.` / `uat.` / `cms.`
- Probe a deliberately missing path (soft-404 vs real 404 vs 200 error
  template). `probes.soft_404_fingerprint` already exists and is not wired
  to the CLI.
- Notice `/page-404/` and `/page-for-tests/` **in the sitemap** as indexable
  200s — that is inventory, not an exploit.

Depends on **144** so this cannot be ticketed as “find SQLi”. It also depends
on **148–149** because deriving and resolving additional hostnames expands the
network target set and must be both declared and destination-safe.

## In scope

- CLI mode or post-crawl step, opt-in, same robots/auth as the parent job.
- Require a valid ticket-148 scope manifest. Candidate non-production origins
  must be enumerated in that manifest; deriving a hostname does not authorise
  it. Apply ticket-149 destination checks before DNS/HTTP evidence is recorded.
- Non-prod hostname list derived from crawled registrable domain; DNS failure
  is a valid result; HTTP GET only if it resolves; record status, `x-robots-tag`,
  title, whether auth was demanded (401/403) **without** trying to bypass it.
- Wire `soft_404_fingerprint` into the CLI; compare the fingerprint to
  crawled 200s that look like the error template (title/simhash), especially
  sitemap URLs whose path contains `404` or `page-for-tests`.
- Independent sitemap fetch (already done in engine) plus a report of sitemap
  locs on hosts that were not the preferred host (NXDOMAIN, legacy CDN,
  `content.` / `en.` leftovers).

## Candidate-host and DNS contract

- Derive the registrable domain with a maintained Public Suffix List
  implementation; do not assume “last two labels” (`example.co.uk` must remain
  intact).
- Default labels are a versioned, documented finite set such as `dev`,
  `staging`, `stage`, `test`, `preview`, `uat`, and `cms`. Operator additions
  are allowed; wildcard/brute-force dictionaries are not.
- Derivation creates candidates, not authorization. Filter candidates against
  the exact origins in ticket 148 before DNS. Undeclared candidates appear as
  `not_authorised_not_resolved` without a lookup.
- Distinguish NXDOMAIN, no-address, timeout, resolver error, private/special IP
  denied by ticket 149, public address, HTTP error, and HTTP response. DNS
  existence alone is an inventory fact, not a vulnerability.
- Make at most one bounded normal GET per authorised/resolved candidate origin,
  at `/` unless the manifest names another exact path. Never search that host.
- Record redirect target and stop before an out-of-scope/private destination.

## Soft-404 and sitemap contract

- Refactor `soft_404_fingerprint`: it currently aliases `engine.config` and
  sets `follow_redirects=False` on the live object. The CLI path must use an
  isolated request/config so the probe cannot change later crawl behavior.
- Generate one collision-resistant, non-sensitive missing path under an
  authorised prefix, record it explicitly, and spend one request from the same
  run budget. Do not retry with multiple invented paths.
- Preserve raw status and redirect evidence. Compare title, bounded body
  length, and SimHash to already-crawled 200 pages with a documented Hamming
  threshold; classify similarity separately from indexability.
- Report suspicious sitemap locs based on path/title/provenance and fingerprint
  similarity. A URL containing `404` or `test` is a candidate, not a finding by
  itself.
- Inventory every host explicitly published by an already-authorised sitemap,
  including rejected/dead hosts, without treating publication as permission to
  resolve or fetch it. DNS/HTTP enrichment needs manifest authorization.
- Directory-index/debug/error-content detection belongs to ticket 154 so this
  command does not grow a second detector implementation.

## Artifact and persistence

- Version JSON output independently and include the scope-manifest digest,
  candidate source, authorization decision, DNS state, destination-policy
  decision, HTTP facts, and soft-404 comparison facts.
- Use ticket 153's redacted URL/evidence contract; candidate and redirected
  URLs may contain sensitive query values even when this command did not add
  them.
- Keep `not_tested`, `not_authorised`, `nxdomain`, `blocked_by_policy`,
  `reachable`, and `finding_candidate` distinct.
- Persist run-scoped normalized candidates/results when a store is configured;
  otherwise emit the same contract to JSON. Never treat absent enrichment as a
  clean result.

## Out of scope

- Injection, XSS, SSRF, or IDOR payloads.
- Forced browsing of `/wp-admin/` beyond what robots already allow or block.
- Credential stuffing, default-password checks.
- Crawling a 401 with guessed paths until it becomes 200.

## Tasks

- Public CLI + JSON artifact fields; run-scoped if a store is present.
- Tests with a local fixture host: NXDOMAIN label, 404 probe, sitemap loc on
  a second host, 200 “Page 404” path flagged when it matches the error
  fingerprint.
- Add Public Suffix List, no-DNS-before-authorization, private-address,
  redirect escape, probe-budget, no-config-mutation, and one-invented-path
  regressions.
- Freeze the JSON contract and test run isolation/persistence when configured.
- Docs: authorised operators only; this is exposure *inventory*.

## Definition of Done

- sapiens-class findings (dead `en.` host in sitemap, published `/page-404/`,
  genuine 404 vs indexable error template) can be produced by the tool, not
  only by a chat script.
- No payload generation in the implementation.
- Derived-but-undeclared hosts cause no DNS or HTTP traffic, and every outcome
  distinguishes untested/denied/failed/reachable states.

## Status

done (2026-09-23; landed in PRs #80–#87) — `exposure-inventory` has the
scope-manifest gate, bounded declared-host probes, destination-policy checks,
soft-404 evidence, redacted versioned artifact, and regression coverage in
`tests/test_exposure_inventory*.py`. Authorised SEO/security *hygiene*, not a
vulnerability scanner.
