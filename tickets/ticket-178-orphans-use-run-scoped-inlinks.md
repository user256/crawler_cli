# Ticket 178: Define orphan pages from same-run internal inlinks

## Goal

Make the `orphans` report mean “no internal incoming link observed in this
crawl run”, rather than “was initially put on the frontier without a parent”.

## Background

`CrawlReports.orphan_pages()` currently tests `frontier.parent_id IS NULL`.
Every seed therefore appears as an orphan even when another crawled page links
to it, while frontier provenance is not the link graph. This produces
plausible-looking but wrong report output.

## Tasks

- Select pages in the requested run that have no qualifying incoming edge
  from that run's immutable `page_run_snapshots.links_json` (or a proven
  run-keyed edge table). Joining mutable `internal_links` to a source snapshot
  does not make the edge historical. Do not let links from another run make
  a page non-orphan.
- Define and document the treatment of self-links, nofollow links, redirected
  sources/targets, and links whose target was not crawled. The default should
  answer the crawl's observed internal-link question, not claim sitewide truth.
- Retain an explicit seed/provenance field in the output if it is useful, but
  do not use it as the orphan predicate.
- Ensure the implementation has a truthful legacy-store fallback rather than
  accidentally combining unrelated historical links.

## Definition of Done

- A seeded URL with a same-run inlink is not reported as orphaned.
- A crawled page with no same-run inlink is reported even if it has a frontier
  parent artifact.
- Two runs sharing URLs/links cannot contaminate each other's orphan result.
- CLI/JSON report regression coverage and documentation are updated.

## Status

Consumed by [technical audit ticket 186](./ticket-186-technical-audit-link-graph-correctness.md).
2026-09-24 review clarified immutable-edge requirements; scope remains proposed.

proposed (2026-09-23, Priority: **P1**) — reporting correctness; found in Shopify crawls.
