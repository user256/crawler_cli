# Ticket 256: Accept a Semrush Organic Pages export as a URL source

## Status and priority

Proposed — P1. The loader bug is P1 on its own. Owner: unassigned. Share the
loader with 217 (backlink weighting from Ahrefs/Semrush/GSC exports).

## Goal

Let the user drop in a Semrush Organic Research → Pages export (for example
`https___rainbet.com_-organic.PagesV3-us-20260927-2026-09-28T17_29_02Z.csv`)
as a list of URLs, keeping its traffic metrics for prioritisation. The crawl,
`compare-renders`, `compare-agents` (254) and `technical-audit` can all use it.

## Background

The export has a `URL` column plus the columns `Traffic (%)`,
`Number of Keywords`, `Traffic`, `Traffic Change`, `Top Keyword`,
`Primary Intent`, per-intent position/traffic counts, `Answer Engines` and
`LLM Prompts`. It has no date column; the Semrush database (`us`) and data
date (`20260927`) appear only in the filename.

**Current bug:** `load_urls_from_csv` (`src/crawler_cli/csv_urls.py`) matches
the column name case-sensitively against the default `url`. When the name is
missing, it joins each whole row with commas. On the rainbet export,
`--csv-file` yields 542 junk "URLs" such as
`https://rainbet.com/,77.78,434,55926,…`, header row included. Passing
`--csv-column URL` works (541 URLs), but nothing warns the user.

The rainbet export also lists non-production hosts that rank in Google:
`dev.rainbet.com` (5), `staging.rainbet.com` (1), `staging-blog.rainbet.com` (2),
`maintenance.rainbet.com` (1), alongside `help.` (20), `blog.` (1) and
`rainbet.com` (511). Only 223 of 541 rows have traffic > 0.

## Tasks

### Loader hardening (all CSV inputs)

- Match column names ignoring case, surrounding whitespace and a UTF-8 BOM.
- If the first row looks like a header (its first cell is not an absolute URL)
  and no requested column matches, raise an error that lists the headers
  found. Do not fall back to joining rows.
- Validate every value as an absolute http(s) URL. Report the number rejected
  and a sample of them, and never crawl a rejected value.

### Semrush recognition

- Auto-detect a Semrush Organic Pages export from its header signature on
  `--csv-file`, and also accept `--url-source semrush-pages:PATH` explicitly.
- Parse the database and data date from the filename pattern
  `-organic.PagesV3-<db>-<YYYYMMDD>-`. Allow `--source-date` and `--source-db`
  overrides. If the date cannot be determined, record the source as
  "date unknown" rather than guessing.

### Metrics and prioritisation

- Keep `traffic`, `traffic_pct`, `keywords`, `traffic_change`, `top_keyword`
  and `primary_intent` as per-URL source attributes in a run-scoped sources
  artifact/table, together with provenance: tool, database, data date and
  file hash.
- Add `--order-by traffic`, `--top N` and `--min-traffic N`, so the top
  organic pages can drive bounded samples in `compare-agents`,
  `compare-renders` and `--agent-parity` (255).

### Scope

- Report URLs on hosts outside the crawl scope as out-of-scope, and do not
  fetch them.
- In `technical-audit`, list ranking non-production hosts (for example `dev.`,
  `staging`, `maintenance`) as a finding **candidate**. It needs a live check
  (status, `X-Robots-Tag`, auth) before it can be promoted, as required by 248.

### Technical-audit use

- Treat the export as a dated coverage source:
  - organic URLs that the crawl never discovered become a discovery or orphan
    candidate, qualified by coverage (222);
  - organic URLs that now return non-200, noindex, a redirect, or a canonical
    pointing elsewhere are weighted by Semrush traffic, the same way 217
    weights by backlinks.

## Acceptance criteria

- [ ] The rainbet-shaped fixture (trimmed and committed) loads 541 URLs with no
  `--csv-column` flag, and a CSV whose headers do not match fails loudly
  instead of producing junk rows.
- [ ] Database `us` and data date `2026-09-27` are parsed from the filename
  and appear in the output provenance.
- [ ] `--top 50 --order-by traffic` selects the 50 highest-traffic in-scope
  URLs, and zero-traffic rows sort last.
- [ ] Out-of-scope hosts are counted and listed, never fetched, and
  non-production hosts show up as an audit candidate.
- [ ] Existing plain-list and `url`-column CSV inputs behave as before (regression tests).
