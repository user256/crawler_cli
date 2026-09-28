# Ticket 262: Multi-source discovery provenance and graph discrepancy reconciliation

## Status and priority

Proposed — P2. Owner: unassigned. Extends sitemap union (Ticket 186/204), CSV URL loader (Ticket 256), and crawl provenance checks (relates to question Q82).

## Goal

Provide a unified cross-reconciliation command (`crawler-cli reconcile-sources`) that joins all discovery sources (internal HTML link graph, XML sitemaps, GSC URL exports, Semrush/Ahrefs backlink exports), computing a deterministic Venn-diagram provenance matrix that identifies untracked, orphaned, and non-canonical URL populations.

## Background

An authoritative technical SEO audit requires reconciling what is discovered across disparate channels:
1. **HTML Link Graph:** What users and ordinary crawlers find by following `<a href>` links.
2. **XML Sitemaps:** What the site owner formally declares as canonical, indexable inventory.
3. **Google Search Console (GSC) Exports:** What Googlebot has actually discovered, crawled, or indexed.
4. **Third-Party Backlink Exports (Ahrefs/Semrush):** What external referring sites point to (including legacy dead URLs).

Currently, `crawler_cli` can ingest sitemaps into the run graph (Tickets 186, 204) and load Semrush exports (Ticket 256), but it lacks an automated reconciliation report that compares all available sources and segments URLs by discovery origin.

## Tasks

### Reconciliation Command Contract
- Implement CLI command:
  ```bash
  crawler-cli reconcile-sources \
    --crawl-run-id N \
    [--sitemap-url URL | --sitemap-file PATH] \
    [--gsc-export PATH] \
    [--backlinks-export PATH] \
    --out reconciliation.json [--sheets-tab Reconciliation]
  ```

### Provenance Segmentation Matrix
- Cross-join normalized URLs across all active sources and classify into mutually exclusive populations:
  - `graph_and_sitemap`: Present in internal link graph and XML sitemaps (ideal state).
  - `sitemap_orphan`: Present in XML sitemap but unreachable via internal HTML link graph (0 inlinks).
  - `unmapped_in_sitemap`: Discovered in HTML link graph (200 OK, indexable) but omitted from XML sitemaps.
  - `backlink_dead_end`: Present in external backlink export but returning 404/410 or missing from both crawl graph and sitemaps.
  - `gsc_unlinked`: Present in Google Search Console discovered URLs but absent from current site architecture.

### Output & Recipient Reporting
- Output summary counts for each discovery quadrant.
- Generate a detailed breakdown listing URL, discovery sources, HTTP status, canonical declaration, and recommended remediation action.

## Definition of Done

- [ ] A multi-source fixture with overlapping sitemap, backlink, and crawl datasets accurately partitions all URLs into the 5 provenance segments.
- [ ] Orphaned sitemap URLs and unmapped indexable pages are identified with 100% precision.
- [ ] Export produces a deterministic JSON payload and optionally populates a `Reconciliation` tab in recipient Google Sheets.
- [ ] Unit tests pass with local CSV and database fixtures.
