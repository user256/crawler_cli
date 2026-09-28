# Ticket 255: Add a UA-parity check to the technical audit's server-configuration group

## Status and priority

Proposed — P2. Owner: unassigned. Depends on 254 (compare-agents) and 224.
Follows the interpretation rules in 249 and the check contract (ec7fc4d, 69ce77b).

## Goal

Run the UA comparison from 254 as a standard `technical-audit` check, next to
the existing server-configuration probes: www/non-www, HTTPS/HTTP and made-up
URLs / soft-404 (193, 236). Its results then flow into the check registry and
the client sheet like every other check.

## Tasks

- Register an `agent-parity` check in the check contract, in the same group as
  `url-host-and-variants` and `soft404-error-routes`. Declare its inputs,
  coverage fields and the statuses it can emit.
- Pick a bounded, stratified sample: the homepage, one URL per template
  stratum, top organic URLs when a Semrush/GSC source is supplied (256), and
  the URLs that the variant and soft-404 probes already touched. Enable it
  with `--agent-parity` and keep it off by default, because every extra agent
  multiplies live requests.
- Use the crawl's fetch profile as the baseline agent (224), so the audit
  compares what it actually crawled.
- Map the 254 classes to statuses:
  - `identical` and `volatile-only` become pass, kept internally only (247).
  - `access-difference` becomes coverage-limited / unverified.
  - `seo-significant`, `bot-only-content` and `user-only-content` become
    "Review", never "Issue", unless an analyst adds claim-specific evidence
    (248).
- Client-facing wording: "The server returns different <field> to crawler
  and browser User-Agents on N of M sampled URLs." Always include the spoofed-UA
  limitation, and never write "cloaking".
- Record the sample size, agents, egress, dates and A/A noise rate in the
  check's coverage block, so counts reconcile (250).
- When the variant probes (193/236) are in the same run, cross-reference
  them: flag a variant that redirects differently for Googlebot than for the
  browser.

## Acceptance criteria

- [ ] `technical-audit --agent-parity` against the 254 fixture server emits an
  `agent-parity` row with Review status and per-field evidence.
- [ ] A run with only volatile differences produces no client row, but keeps
  the internal ledger entry.
- [ ] A spoofed-Googlebot 403 produces coverage-limited status, not an Issue.
- [ ] The check registry lists the agents, sample, egress and noise rate.
