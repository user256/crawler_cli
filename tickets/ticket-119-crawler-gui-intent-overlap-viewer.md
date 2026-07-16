# Ticket 119: Replicate the intent-overlap viewer in crawler_gui

**Status:** proposed
**Priority:** P2 product presentation
**Depends on:** Tickets 095, 106, 107, and the crawler_gui shell

## Goal

Keep Ticket 107's self-contained `render-report` HTML export as the portable,
offline deliverable, and expose the same intent-overlap analysis inside
`crawler_gui` for operators reviewing a crawl.

## Background

Ticket 106 defines the `report_data.json` envelope. Ticket 107 renders that
envelope as a dependency-free canvas map with filters and report tables. The
GUI should reuse that data contract rather than fork the calculations or parse
the CSV report files. Ticket 095 must land first so any selected crawl/run has
deterministic snapshot semantics.

## Tasks

- Add an Intent Overlap / Cluster Report view to `crawler_gui`, preserving the
  existing standalone `render-report` export unchanged.
- Load the Ticket 106 `report_data.json` shape through one adapter: a static
  fixture for the prototype now and the future run-scoped GUI/API endpoint
  later. Do not duplicate intent-overlap computation in browser code.
- Recreate the Ticket 107 operator interactions in the GUI: canvas cluster
  map with hover/pin, zoom/pan, URL search, relation/page-type and risk
  filters, cluster selection, and pages/pairs/clusters tables.
- Synchronise selection between a map point and the table/detail area, and
  make the view work in both crawler_gui light and dark themes.
- Clearly identify the selected run and provide an Export HTML action that
  points users to the retained standalone report artifact (or invokes the
  future API export endpoint); the GUI is an additional surface, not a
  replacement for client-shareable offline HTML.
- Add fixture/DOM interaction coverage for the adapter, filters, selection
  synchronisation, and both themes. Keep the implementation dependency-free
  and make no network requests from the rendered viewer.
- Document the GUI/report-data contract, intended run selector, and the
  distinction between the GUI view and offline export.

## Definition of Done

Given a run-scoped Ticket 106 report payload, crawler_gui displays the same
cluster map, filters, summary, and searchable pages/pairs/clusters information
available in Ticket 107. A user can move from a map point to its table row and
open/export the standalone report without losing the offline `render-report`
workflow. The view remains responsive for the documented Ticket 107 payload
size and works in light and dark themes.
