# Ticket 161: Run-backed render-parity selection, strata coverage, and persistence

## Goal

Close the two remainders of ticket 160 so the render-parity audit can be driven
from a stored crawl run instead of only from operator-typed URLs, and so a
comparison session can be retained for later review. Specifically: implement
`crawler-cli compare-renders --crawl-run-id RUN_ID` selection with deterministic
sampling and honest run provenance, add operator-supplied template labels and
path-strata coverage to the sample metadata and reports, and add the optional
run-scoped persistence seam that ticket 160 explicitly permitted to be split
out.

## Background

Ticket 160 shipped in PR #68 (merged 2026-08-24 as `9427ec3`). The delivered
first increment covers exact positional URLs and `--csv-file` input, the
same-navigation raw-versus-hydrated comparison, typed completeness states,
multiple typed findings, the `crawler-cli/render-comparison/1` JSON schema, CSV
and self-contained HTML reports, and the `--fail-on` / `--fail-on-incomplete`
exit contract. The absolute-URL clustering defect from ticket 019 is fixed:
`_cluster_paths()` in `src/crawler_cli/compare_renders.py` now parses the URL and
clusters the first path segment, never the scheme.

Three parts of ticket 160's contract were not delivered:

- `--crawl-run-id` is parsed by the shared crawl option group but rejected at
  runtime in `_run_compare_renders()`
  (`src/crawler_cli/__main__.py`, exit code 2, message
  "`--crawl-run-id selection is not available for compare-renders yet`").
- The sampling metadata only ever reports
  `sampling_basis = "exact_operator_supplied_urls"`. There is no template label,
  no path-strata computation, and no strata coverage in the JSON, CSV, or HTML
  report. `--csv-file` supports `--csv-column` for the URL column but has no
  `template` column.
- Nothing persists a render-comparison session. There are no
  `render_comparison` tables or store methods in
  `src/crawler_cli/persistence.py`; results exist only as the files written by
  `--output` and `--html-report`.

Until these land, ticket 160 stays `partially done` in the register. This ticket
does not reopen anything PR #68 already delivered, and it must not change the
default behaviour of the exact-URL and CSV input paths.

## Behavior contract

### Run-backed selection

Replace the rejection in `_run_compare_renders()` with real selection. Given an
explicit run ID and the existing PostgreSQL options:

- select candidates only from that run, and only records that are successfully
  decoded HTML; exclude absent, non-HTML, and undecoded records;
- keep the input sources mutually exclusive — positional URLs, `--csv-file`, and
  `--crawl-run-id` cannot be combined, and combining them is a validation error
  (exit code 2);
- record run ID, run status, interruption/completeness state, selection time,
  candidate count, sample size, and sampling basis in the JSON payload's `input`
  block, and surface the same facts in the HTML report;
- identify a partial or interrupted source run honestly rather than presenting
  its candidate set as a full inventory; and
- publish every selected URL, as the exact-URL path already does.

Selection supplies URLs only. The comparison itself always performs a live
same-navigation render. Stored raw HTML from the run is never used as the raw
side of a comparison — that time-differential mode remains out of scope and
needs its own explicit contract.

### Sampling, strata, and template labels

- Prefer an operator-supplied template label. For `--csv-file`, add an optional
  template column (default column name `template`, overridable) that labels each
  URL; unlabelled rows fall back to computed strata.
- Without operator labels, compute deterministic strata from host, locale,
  path section, and depth. Call them `path strata` in every output. Never call
  them inferred templates.
- Aim for 10 to 20 pages spread across material strata, still bounded by
  `--max-pages` (default 20) and the existing render concurrency cap of 2.
- Sampling must be deterministic: the same run and the same options select the
  same URLs in the same order. No wall-clock or random-seeded selection.
- Report stratum coverage — strata present in the candidate set, strata
  sampled, and per-stratum counts — in JSON, CSV, and the HTML report, and add
  the stratum filter that ticket 160's report contract names.

### Persistence

Add an opt-in run-scoped render-comparison session:

- one session row per invocation, linked to the source crawl run when selection
  came from a run and standalone otherwise;
- typed findings and bounded signal evidence per URL; never a second copy of the
  raw or rendered HTML document;
- every query scoped by comparison session and crawl run, so sites and runs
  cannot mix;
- retention, compaction, deletion, and secret-absence behaviour follow the
  existing analysis contracts and the ticket 153 redaction contract; and
- the same `CorrelationDigest` redaction already applied to the file outputs is
  applied to persisted rows.

Persisting stays optional; the file and report path remains fully usable with no
database configured.

## Implementation tasks

1. Add run-candidate selection to the store: successfully decoded HTML records
   for one run ID, with run status and completeness metadata.
2. Add deterministic strata computation and operator template labelling, shared
   by all three input sources.
3. Extend the payload `input` block and the CSV and HTML reports with run
   provenance, strata coverage, and the stratum filter.
4. Implement `--crawl-run-id` dispatch in `_run_compare_renders()`, including
   mutually exclusive input validation.
5. Add the render-comparison session schema, writes, and scoped reads to
   `persistence.py`, behind an explicit opt-in flag.
6. Update the command documentation, cost guidance, and the ticket 160 status
   note once all three parts land.

## Test matrix

- Run selection returns only successfully decoded HTML records for the given
  run, and excludes records from every other run.
- A partial or interrupted source run is reported as partial in JSON and in the
  HTML report.
- The same run and options select the same URLs in the same order across
  repeated invocations.
- Positional URLs, `--csv-file`, and `--crawl-run-id` in any combination fail
  validation with exit code 2, and each alone succeeds.
- Operator template labels win over computed strata; unlabelled rows fall back
  to path strata, and no output calls computed strata "templates".
- Strata coverage totals reconcile exactly with the selected URL count and with
  the per-URL detail rows.
- Stored run HTML is never used as the raw side of a comparison; the raw side
  always comes from the live navigation.
- Persisted sessions are scoped by session and run, contain no full HTML
  document, and contain no secrets or sensitive query values in any column.
- Running with persistence disabled produces identical file output to the
  current behaviour, proving no regression for the PR #68 paths.
- JSON schema, CSV columns, and HTML escaping keep their golden and contract
  tests green; the schema version increments only if a field changes meaning.
- Focused tests, the full non-integration suite, lint, typecheck, formatting,
  and the configured PostgreSQL integration selection pass; any unavailable
  external check is recorded as not run.

## Out of scope

- Comparing historical stored raw HTML with a current live DOM.
- Recursive crawling or following rendered-only links from this command.
- Any change to the finding codes, severity rules, or completeness states that
  PR #68 froze.
- Raising the render concurrency cap above 2 or the default page cap above 20.

## Definition of Done

- `crawler-cli compare-renders --crawl-run-id RUN_ID` performs a bounded, live,
  deterministic sample selected from that run and reports the run's identity and
  completeness honestly.
- Template labels and path strata are computed, published, and filterable, and
  are never described as inferred templates.
- An optional run-scoped comparison session can be persisted, is correctly
  scoped, and holds no duplicate documents and no secrets.
- The exact-URL and CSV paths delivered in PR #68 are unchanged.
- Ticket 160 can be closed as `done` with this ticket's evidence attached.

## Status

done (2026-09-07, Priority: **P1**; depends on completed tickets 153, 157, 159,
and the first delivery of 160. Delivered run-backed `--crawl-run-id` selection
with deterministic host/locale/path/depth strata and honest source-run
completeness, operator template labels via the optional CSV `template` column,
per-URL `stratum`/`stratum_source` plus stratum coverage in JSON, CSV, and the
HTML report with a stratum filter, and the opt-in `--persist`
render-comparison session that stores redacted bounded evidence and no HTML
document. Closes ticket 160)
