# Ticket 160: First-class raw-versus-rendered SEO parity audit

## Goal

Turn the existing render-comparison helper into a first-class, bounded CLI and
reporting workflow for detecting indexing-relevant differences between the
initial HTML response and the hydrated browser DOM, both for one-off URL checks
and representative sitewide samples.

The primary evidence must compare the main-document response body with the DOM
produced from that same Playwright navigation. It must report what changed,
whether the render completed, and which conclusions remain uncertain. It must
not claim to reproduce Googlebot or Google's Web Rendering Service.

## Background

Ticket 019 added `compare_renders()` and `compare_renders_sampled()`. Ticket 157
later added the stronger primitives this feature should use: a bounded raw main-
document baseline, a hydrated DOM snapshot, settle completeness, render-attempt
provenance, and shared Playwright context lifecycle. Ticket 159 makes raw and
rendered JSON-LD extraction use the current Google-compatible parser semantics.

The library helper is useful but is not currently a complete analyst workflow:

- there is no `crawler-cli compare-renders` command;
- there is no versioned JSON/CSV output or visual HTML report;
- it performs an independent HTTP fetch and a browser fetch, so cookies, cache,
  geo, A/B tests, response timing, or client-specific server behavior can be
  mistaken for JavaScript mutation;
- sampled mode creates two new engines per URL instead of reusing a bounded
  browser context across the sample;
- it compares only title, description, robots, canonical, links, and document
  size, omitting H1s, content, hreflang, language, and structured data;
- its single exclusive verdict can hide simultaneous defects;
- an unsettled or incomplete render can still be classified as `ok`;
- HTML byte-size delta is treated as content evidence even though browser DOM
  serialization, browser-inserted elements, and markup churn make it noisy;
- `_cluster_paths()` receives absolute URLs but clusters by the string before
  the first slash, which collapses ordinary HTTP(S) URLs under `https:` or
  `http:` rather than a real path section;
- differences do not carry explicit source values, timestamps, completeness,
  severity, or an evidence boundary suitable for audit reporting.

This ticket supersedes the analyst-facing behavior of ticket 019 without
removing its public API abruptly. Ticket 157 remains the source of render-time
link and request-discovery evidence; this ticket interprets raw/rendered page
evidence for SEO parity and does not widen the crawl frontier.

## Evidence boundary

The result means: "the initial response HTML observed by this browser navigation
differs from the hydrated DOM observed by this crawler at this time and under
this configuration." It does not mean:

- Googlebot fetched, rendered, indexed, or failed to index the page;
- a spoofed `Googlebot` user-agent represents verified Google traffic;
- a rendered-only signal is necessarily unavailable to Google;
- a browser-visible request succeeded or is crawlable; or
- a raw/rendered difference is automatically a defect.

Search Console live URL Inspection, Google Rich Results Test evidence, verified
Googlebot server logs, or CDN bot-event evidence remains authoritative for
Google-specific conclusions. A report may recommend those checks but must not
claim to perform them.

## Behavior contract

### Primary same-navigation comparison

Add a typed single-navigation parity path that:

1. performs the normal scope, robots, budget, challenge, redirect, body-cap,
   auth, cookie, proxy, and browser-safety checks;
2. captures the bounded main-document response body that Playwright actually
   received and decodes it with shared Content-Type/charset handling rather
   than assuming UTF-8;
3. waits using the configured `domcontentloaded`, network-idle, and optional
   selector conditions;
4. captures `page.content()` as the hydrated DOM;
5. extracts both sides with the same crawler parser and normalization versions;
6. records the response headers once as transport evidence; and
7. computes the comparison without a second page request.

Add an explicit opt-in config/result seam for retaining or immediately
comparing the raw render baseline. Do not overload `discover_render_urls` as a
hidden prerequisite, and do not retain a second unbounded HTML document in
ordinary crawl results.

If the same-navigation raw body is unavailable, the result is
`baseline_unavailable` and inconclusive for parity. The existing independent-
client helper may remain available for client-split measurement, but it must be
labelled `baseline_source=independent_http` and cannot silently substitute for
the primary path. It must surface final-URL, status, response timestamp, user-
agent, proxy identity label, and response-header differences that could explain
the split. It must not retry identities until the content matches.

### Completeness and failure states

Each URL has a typed observation state:

- `complete` — raw baseline and rendered DOM are available, the body is not
  truncated, navigation succeeded, and configured settle conditions completed;
- `partial` — both documents exist but a settle/selector wait timed out;
- `inconclusive` — baseline unavailable, unsupported content, truncation,
  unresolved challenge, robots/scope refusal, or another condition prevents a
  valid comparison;
- `failed` — navigation or extraction failed and bounded error evidence exists.

`partial`, `inconclusive`, and `failed` must never receive an `equivalent`/`ok`
summary. Preserve the exact typed reason and bounded error text. A timeout may
still yield partial differences, but every such finding carries the partial
evidence qualifier.

### Compared SEO signals

Extract and retain both source values, a normalized comparison value, and a
typed change state (`same`, `added_after_render`, `removed_after_render`, or
`changed`) for:

- title and meta description;
- meta robots directives, compared semantically rather than by token order;
- canonical URL;
- hreflang target set, language codes, and `x-default`;
- HTML `lang`;
- H1 values and counts;
- structured-data block count, detected types, parse validity, compatibility
  diagnostics, and stable semantic hashes;
- crawlable internal `<a href>` links on both sides, including raw-only and
  rendered-only normalized URLs; and
- main-body text extracted from both HTML documents through the shared
  `extract_main_text()` path, extraction method/confidence, word count,
  directional word-count delta, similarity/fingerprint distance, and bounded
  raw-only/rendered-only excerpts.

Evaluate `X-Robots-Tag`, HTTP `Link` canonical/hreflang directives, initial and
final status, redirect chain, content type, and final URL alongside the DOM
signals. Headers are response evidence, not a raw/rendered field that JavaScript
can mutate. Report header-versus-HTML conflicts explicitly.

Keep raw and rendered values in the result even when normalization considers
them equivalent. Use field-appropriate normalization: URL normalization for
URLs, set semantics for directives/hreflang, and conservative whitespace
normalization for text. Do not apply one global lowercase transform to all
fields.

Document byte-size delta may remain as a diagnostic metric but must not drive a
content-only verdict. Content findings use normalized main-body text and
directional evidence. A fallback/full-document extraction is lower-confidence
evidence and cannot by itself support a High primary-content finding. Path
clustering must parse URLs and cluster normalized paths; it must never group by
scheme.

### Findings, severity, and summary

Replace the exclusive heuristic as the authoritative result with zero or more
typed findings. At minimum support:

- `indexing_directive_changed` — robots/noindex behavior changed;
- `canonical_changed`;
- `metadata_render_dependency`;
- `hreflang_changed`;
- `structured_data_changed`;
- `primary_content_render_dependency`;
- `content_removed_after_render`;
- `internal_links_added_after_render`;
- `internal_links_removed_after_render`;
- `header_dom_conflict`; and
- `render_comparison_incomplete`.

Each finding contains severity, affected field, raw/rendered values or bounded
evidence, impact explanation, remediation guidance, observation completeness,
and a stable detector/ruleset version. Severity reflects demonstrated indexing
impact: indexing directives, canonical conflicts, or material primary-content
loss may be High; systemic discovery or schema changes may be Medium; small
non-indexing metadata differences may be Low. Do not escalate from document
size alone.

Retain a deterministic `primary_summary` for sorting and backward-friendly CLI
display, but never discard secondary findings. `equivalent` is valid only for a
complete comparison with no material findings. Version thresholds and make
them configurable only where a stable semantic rule is not possible.

### Inputs and sampling

Support mutually exclusive input sources:

- one or more exact positional URLs;
- a newline/CSV URL file, with an optional operator-supplied `template` column;
  or
- a PostgreSQL crawl run selected by explicit run ID, used only to select live
  recheck URLs.

The command never recursively crawls or follows rendered-only links. Default to
a finite maximum of 20 rendered pages and browser concurrency 1; allow an
explicit maximum of 2. Exact supplied URLs remain deterministic and input-
ordered within the cap.

For a stored run, select only successfully decoded HTML records from that run
and record run ID, run status, interruption/completeness state, selection time,
candidate count, sample size, and sampling basis. Prefer an operator-supplied
template label. Without one, use deterministic host/locale/path-section/depth
strata and call them `path strata`, not inferred templates. Aim for 10–20 pages
across material strata and publish every selected URL. A partial historical run
may supply candidates but must be identified as partial.

The stored HTML is not the default raw side: mixing historical raw HTML with a
current live render introduces time drift. The default always performs a live
same-navigation comparison. A future historical-versus-current mode requires a
separate explicit contract.

Reuse one bounded Playwright engine/context across a sample. Do not launch a
new browser per URL. Context recycling, memory watermarks, page cleanup,
timeouts, and existing browser-profile/CDP options continue to apply.

### CLI and automation contract

Add:

```text
crawler-cli compare-renders URL [URL ...]
crawler-cli compare-renders --csv-file urls.csv --url-column url
crawler-cli compare-renders --crawl-run-id RUN_ID [PostgreSQL options]
```

Reuse relevant crawl controls: timeout, rate limit, robots policy, auth/cookies,
proxy, headed/CDP/profile selection, network-idle timeout, selector wait,
response cap, scope manifest, and redaction. Reject unsupported Portal-policy
browser comparison until that policy advertises the required browser/live-
comparison capabilities.

Provide `--max-pages` (default 20), `--render-concurrency` (default 1, maximum
2), `--output`, `--html-report`, `--fail-on high|medium|any`, and
`--fail-on-incomplete`. Use the project's established validation and exit-code
contracts: validation errors are 2, successful runs are 0, and matched
`--fail-on` findings use `EXIT_FINDINGS`. A run where every selected URL is
inconclusive or failed returns `EXIT_FAILURE` (1), not a clean result.
`--fail-on-incomplete` also returns 1 when any selected URL is not `complete`;
operational incompleteness takes precedence over a findings gate.

### Output and report contract

Define `crawler-cli/render-comparison/1` as a separate versioned result schema
rather than silently changing the general crawl artifact. JSON includes:

- schema and detector/ruleset versions;
- observed-at timestamps and secret-free browser/runtime configuration;
- input/run and sampling metadata;
- complete/partial/inconclusive/failed totals;
- finding counts by code and severity;
- one result per selected URL with both signal values, completeness, findings,
  links, content metrics, and bounded evidence; and
- explicit caveats about browser evidence and Googlebot.

CSV is a stable, analyst-friendly flattened finding/detail export. The self-
contained HTML report provides:

- scope, time, sample, template/path-strata coverage, and completeness summary;
- finding counts and healthy aggregate checks;
- filters by severity, finding code, stratum, and completeness;
- a per-URL raw-versus-rendered signal table;
- bounded highlighted text/link/schema differences; and
- remediation and Google-verification guidance.

Do not embed full raw/rendered documents, response headers, cookies, auth data,
or browser storage in the report by default. All URLs, query values, excerpts,
errors, and runtime metadata pass through the ticket 153 redaction contract.
Provide complete URL/link inventories only in redacted machine output when
within configured caps; label any sampled/capped detail honestly.

### Persistence

If results are persisted, use a separate run-scoped render-comparison session
linked to the source crawl run when present. Store typed findings and bounded
signal evidence, not duplicate full HTML documents. Scope every query by the
comparison session and crawl run; never mix sites or runs. Retention,
compaction, deletion, and secret-absence behavior must follow existing analysis
and ticket 153 contracts.

Persistence may be delivered after the versioned file/report path only if the
ticket is split before implementation; the CLI, same-navigation evidence,
completeness semantics, and report must remain one coherent first delivery.

## Implementation tasks

1. Add a typed raw/render parity observation/result model with provenance,
   completeness, signals, multiple findings, and versioned rules.
2. Expose a bounded same-navigation raw baseline through the normal engine path
   without making ordinary crawl artifacts retain a second document body.
3. Build field-specific comparison functions for directives, URLs, hreflang,
   headings, structured data, links, and normalized main-body content.
4. Refactor the ticket 019 API onto shared primitives while preserving a
   clearly labelled independent-client compatibility path.
5. Add shared-engine sampled orchestration with deterministic input/run
   selection, finite cost limits, conservative concurrency, and reliable
   cleanup.
6. Add the `compare-renders` parser, validation, config mapping, dispatch, exit
   behavior, JSON/CSV serializers, and self-contained HTML report.
7. Add optional run-scoped persistence or split it into an explicitly linked
   follow-up before implementation begins.
8. Document commands, cost guidance, interpretation, raw/render caveats, and
   the boundary between crawler evidence and Google-specific verification.

## Test matrix

- Static fixture: complete comparison, no findings, `equivalent` summary.
- JavaScript adds/changes/removes title, description, canonical, robots,
  hreflang, lang, H1, primary text, links, and JSON-LD; every change produces
  its typed finding without suppressing simultaneous findings.
- Robots directive order/case and equivalent absolute/relative URLs normalize
  correctly while source values remain visible.
- Header canonical/robots/hreflang conflicts with both raw and rendered HTML are
  reported without pretending JavaScript changed the header.
- Main-body similarity is directional and ignores ordinary DOM serialization
  noise; byte-size delta alone never produces a content finding, and fallback
  extraction carries lower confidence.
- Absolute rendered-only URLs cluster by parsed path, proving the current
  scheme-clustering defect is fixed.
- Missing baseline, non-HTML, redirect-only/no-response navigation, challenge,
  robots refusal, scope refusal, truncated response, selector timeout, network-
  idle timeout, extraction error, and browser crash map to the correct typed
  state and never `equivalent`.
- UTF-8, declared non-UTF-8, BOM, missing/invalid charset, and decode-failure
  fixtures use the shared bounded decoder and preserve a typed failure rather
  than silently corrupting the baseline.
- Same-navigation mode emits one main-page navigation; the compatibility dual-
  client mode is explicitly labelled and records differing client evidence.
- A 20-URL sample reuses the browser/context, honors concurrency and page caps,
  recycles contexts when configured, and leaks no pages/processes on success,
  timeout, cancellation, or exception.
- Positional, newline, CSV template-label, and run-ID selection are
  deterministic; run selection excludes absent/undecoded HTML and records a
  partial source run honestly.
- Historical stored HTML is never silently compared with a current live DOM.
- JSON schema, CSV columns, HTML escaping, filtering, counts, caps, and
  redaction have golden/contract tests. Malicious page text cannot execute in
  the self-contained report.
- `--fail-on`, `--fail-on-incomplete`, all-inconclusive behavior, and exit-code
  precedence are frozen in CLI tests.
- Auth/cookies remain origin-scoped; secrets and sensitive query values are
  absent from logs, JSON, CSV, HTML, database rows, and failure messages.
- Portal-policy capability rejection is fail-closed and occurs before browser
  launch.
- Real Chromium smoke proves a raw title/content/link/schema set and a distinct
  hydrated set from one navigation, plus settle state and browser cleanup.
- Focused tests, full non-integration suite, lint, typecheck, formatting,
  compile, artifact/report contracts, and configured PostgreSQL integration
  pass; unavailable external checks are recorded as not run.

## Out of scope

- Claiming exact Googlebot or Web Rendering Service parity.
- Search Console URL Inspection or Rich Results Test API integration.
- Spoofing Googlebot as proof of Google behavior.
- Rendering every crawled URL by default or recursively following hydrated
  links from this command.
- Clicking controls, scrolling to trigger infinite/lazy inventories, submitting
  forms, replaying network requests, or mutating page/application state.
- Pixel/screenshot visual regression; the HTML report highlights SEO signal and
  bounded content differences, not paint-level layout changes.
- Full-document character diffs or unbounded duplicate HTML persistence.
- Treating every rendered-only item as a defect or rich-result eligibility
  conclusion.
- Comparing historical stored raw HTML with a current render without a future,
  explicit time-differential contract.

## Definition of Done

- An operator can run one bounded command over exact URLs, a URL file, or a
  deterministic live sample selected from one crawl run and receive versioned
  JSON/CSV plus a safe self-contained HTML report.
- The default comparison uses the raw response and hydrated DOM from one
  Playwright navigation, reuses a bounded browser context, and makes no hidden
  second page request.
- Every material SEO signal difference is represented independently with both
  values, evidence completeness, severity, remediation, and stable provenance.
- Partial or unavailable evidence cannot be reported as equivalent, and report
  totals reconcile exactly with URL and finding detail.
- Sampling, caps, run status, observation time, browser configuration, and the
  Googlebot evidence boundary are explicit and auditable.
- The existing ticket 019 API remains compatible or has a documented migration
  path; the absolute-URL clustering and lossy single-verdict defects are
  regression-tested.
- Redaction, scope, robots, budget, auth, Portal-policy, artifact, persistence,
  browser lifecycle, and real-Chromium acceptance checks pass.

## Status

done (2026-09-07, Priority: **P1**; the first delivery in PR #68 implemented the
direct/CSV same-navigation CLI comparison and reports, and ticket 161 delivered
the remainders — run-backed `--crawl-run-id` selection with honest run
provenance, operator template labels plus computed path strata with coverage and
filtering in JSON/CSV/HTML, and the optional run-scoped persistence seam. Builds
on completed tickets 019, 031, 097, 153, 157, and 159)
