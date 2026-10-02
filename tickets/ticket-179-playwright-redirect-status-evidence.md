# Ticket 179: Preserve redirect status evidence under Playwright

## Goal

Store the requested URL's real redirect status and complete redirect evidence
when the browser follows a navigation redirect; never write a final 200 as if
the requested URL itself returned 200.

## Background

`PlaywrightBackend.fetch()` returns `response.status`, which is normally the
final navigation response. It reconstructs prior hops in `redirect_chain`, but
the crawl snapshot's initial status therefore becomes 200 for a real 301→200.
Redirect reports and migration checks consequently under-report redirects.

## Tasks

- Define a backend-neutral requested/final status contract. For a followed
  redirect, retain the requested URL's first response status, final URL/status,
  and ordered hop evidence; for a direct response, the two status values agree.
- Populate the contract from Playwright's request/response chain without a
  second live request. If a hop's status is unavailable, expose an explicit
  incomplete-evidence state rather than manufacturing 200.
- Verify persistence, crawl artifact, redirect-chain reports, and comparison
  consumers preserve the distinction. HTTP and curl backends must retain their
  existing semantics.

## Definition of Done

- A Playwright 301→200 fixture persists initial status 301, final status 200,
  target URL, and ordered redirect evidence.
- Multi-hop and unavailable-hop cases are deterministic and honest.
- Redirect reports agree between HTTP and Playwright for the same fixture.
- Regression tests cover persistence/output contracts.

## Status

Consumed by [technical audit ticket 186](./ticket-186-technical-audit-link-graph-correctness.md)
and [live recheck ticket 185](./ticket-185-technical-audit-live-rechecks-publication-gate.md).
The new lane reuses this backend fix; report multi-issue classification belongs to 186.

proposed (2026-09-23, Priority: **P1**) — redirect-report correctness; found in Shopify crawls.
