# Ticket 103: AMP/page-variant awareness — explicit classification, extraction, and canonical hygiene

## Goal
The crawler discovers and fetches AMP variants but nothing in the pipeline
*knows* they are AMP: exclusion from intent-overlap currently depends entirely
on each AMP page happening to declare a canonical. Classify page variants
(AMP first; the mechanism should extend to print/feed variants later)
structurally, extract the `rel="amphtml"` edge we currently drop, and report
AMP canonical hygiene.

## Background (evidence: thompsons-scotland.co.uk run, 2026-07-15)
- **648 AMP pages fetched 200** (Joomla wbAMP-style `/amp` path suffix, plus
  `?amp=1`/`&amp=1` query forms), all discovered via `link` source — real
  crawl budget spent.
- This run they were all kept out of pairing, but only incidentally: 477
  excluded `canonicalised-elsewhere`, 49 `non-200`, 1 `url-variant`, ~121
  never got signatures. **171 of the 648 declare no canonical at all** — on a
  site where those pages' canonicals are simply missing (a genuine site
  finding this tool should surface, and on another site such pages WILL leak
  into the analysis as duplicate noise).
- `grep -rn amphtml src/crawler_cli/` → nothing: the extractor captures
  canonical/hreflang `<link>` edges but not `rel="amphtml"`, so the
  authoritative page↔AMP pairing signal is dropped at extraction time.
- `compute_exclusion` (intent_overlap.py:524) reasons: non-html/non-200/
  noindex/canonicalised-elsewhere/url-variant — no variant-kind concept.

## Tasks
- **Extraction**: capture `<link rel="amphtml" href=…>` in extract.py
  alongside canonical (new extracted field + persistence, mirroring the
  canonical_urls pattern — e.g. an `amphtml_urls` table or a `rel` column).
- **Classification**: detect AMP variants from crawler-captured evidence:
  (a) target of another page's `rel="amphtml"`; (b) URL shape — `/amp` path
  tail or `amp=1` query param — confirmed by content (signature hash matches
  the non-AMP base, or the page canonicals to it). Record kind on the page
  identity (e.g. `variant_kind='amp'`, extensible enum).
- **Analysis**: new exclusion reason `amp-variant` in `compute_exclusion`,
  ranked before `canonicalised-elsewhere` so AMP pages report as AMP whether
  or not their canonical tag is present. Manifest/summary count them.
- **Hygiene report**: AMP pages missing a canonical to their base page (171
  here) — new columns in pages.csv or a small `amp_issues.csv`, with the
  paired base URL when known from `rel="amphtml"`/URL shape.
- **Crawl budget (optional flag)**: `--skip-amp-variants` to not enqueue
  detected AMP URL shapes at discovery time (default OFF — crawl-and-classify
  remains the default so hygiene reporting keeps working).
- Tests: extraction of rel=amphtml, URL-shape+content confirmation (incl. a
  `?amp=1` query case and a non-AMP page whose slug merely ends in "amp" —
  e.g. `/revamp` must NOT match), exclusion precedence, hygiene report shape.

## Definition of Done
- Re-run on the thompsons-scotland store: 648 AMP pages classify
  `variant_kind=amp`; exclusion reason reads `amp-variant`; the 171
  missing-canonical AMP pages appear in the hygiene output; zero AMP URLs in
  overlap_pairs.csv. ruff/mypy/tests green; README workflow section notes the
  new report.

## Constraint
100% crawler-powered — variant detection uses only crawler-captured link
edges, URL structure, and signature hashes. No external import surface.

## Status
done (2026-07-15, PR #18; remediation 108) — merged in the dependency-ordered review batch. `rel=amphtml` extraction/persistence, AMP classification and precedence, canonical-hygiene reporting, and the optional discovery skip are live. Ticket 108 owns the bounded evidence-hardening follow-up: URL shape plus mere base existence must not remain sufficient confirmation for long-term classification.
