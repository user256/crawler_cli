---
name: technical-seo-audit
description: Run reproducible technical SEO audits from saved crawls, authorised current-site probes, and supplied search evidence. Use for crawl/indexability, links, canonicals, hreflang, sitemaps, structured data, rendered parity, URL variants, and audit artifacts.
---

# Technical SEO audit

Use this skill for a reproducible technical audit. Start from the saved crawl
run. Add live evidence only when it is explicitly authorised and the required
inputs are available.

## Deterministic audit contract

The table below is the complete set of audit checks. It is the source of truth
for both this skill and `crawler-cli technical-audit`.

Every invocation must emit one row for every ID, in this order, in the report's
`checks[]` array. A row is still emitted when its input was not collected. Use
`unavailable` and say which input is missing; do not silently omit the check or
claim a pass from an absent input.

Procedural guidance elsewhere in this skill explains how to collect and
interpret evidence. It does not create additional checks.

| ID | Deterministic question and required evidence |
|---|---|
| `audit-run-integrity` | Is the selected crawl run complete, identifiable, and internally consistent? Crawl/job metadata, run ID, timestamps, scope and counts. |
| `audit-collection-safeguards` | Did collection observe robots, rate limits, authorised headers, and the declared crawl scope? Collection configuration and event evidence. |
| `discovery-source-provenance` | Which in-scope URLs were discovered by seed, link, robots sitemap, sitemap, or supplied inventory in this run? Run-scoped source evidence. |
| `response-status-and-redirect-history` | What response-status and redirect outcomes occurred, including redirect chains, loops, non-2xx internal targets, and final destinations? Response and redirect evidence. |
| `internal-link-targets` | Which internal links are broken, redirecting, malformed, nofollowed, or point to non-indexable destinations? Link graph and destination evidence. |
| `external-link-integrity` | Which sampled or supplied external links fail, redirect unexpectedly, or use an unsafe scheme? Explicit external-link recheck evidence. |
| `orphan-candidates` | Which indexable URLs lack an in-scope incoming link after applying declared source and exclusion rules? Run-scoped link and discovery evidence. |
| `crawl-depth-distribution` | What is the shortest in-scope click depth of crawlable and indexable URLs, and which pages exceed the configured depth? Root set and run-scoped graph. |
| `internal-authority` | How is internal link equity distributed, including important low-authority pages? Run-scoped internal graph and declared calculation. |
| `image-markup` | Which images lack useful alt text, dimensions, or responsive markup? Raw/rendered image markup. |
| `image-resource-delivery` | Which image resources fail, are oversized, or cause delivery/performance issues? Resource and performance evidence. |
| `url-host-and-variants` | Are host, protocol, slash, case, parameter, and other URL variants consistently normalised? Crawl URLs, redirects, canonicals and link targets. |
| `nonproduction-https` | Are non-production hosts excluded from indexing, and are HTTP/HTTPS controls correct? In-scope host, response, robots and indexability evidence. |
| `robots-controls` | Is robots.txt reachable, syntactically usable, scoped correctly, and consistent with crawl directives? Current robots fetch plus crawl evidence. |
| `sitemap-integrity` | Are declared sitemaps reachable, parseable, current, in scope, and consistent with canonical/indexable URLs? Current sitemap fetches plus crawl evidence. |
| `rendered-robots-links` | Do rendered pages expose links that robots disallows or that the crawl could not follow? Raw/rendered link extraction and robots evaluation. |
| `indexability-segmentation` | Which URLs are indexable, blocked, noindex, canonicalised, redirected, errored, or unknown, and are directives contradictory? Stored page directives and responses. |
| `crawl-waste-url-families` | Which URL families create crawl waste through sessions, search, sort/filter, dates, tracking, pagination, or other repeats? URL-family analysis with denominators. |
| `parameter-and-faceted-controls` | Are parameterised and faceted URLs linked, canonicalised, indexable, and controlled as intended? Link, canonical, indexability and URL-family evidence. |
| `soft404-error-routes` | Do error routes, thin template responses, and suspicious 200 pages behave as genuine errors or soft 404s? Response, title/body and template evidence. |
| `metadata-basics` | Which indexable pages have missing, short, long, malformed, or otherwise invalid titles and meta descriptions? Metadata inventory. |
| `metadata-duplicates-aliases` | What are the true duplicate title/description counts after canonical and alias grouping, with the raw counts retained? Metadata, canonical and alias evidence. |
| `content-quality` | Which indexable pages are thin, boilerplate-heavy, empty after extraction, or carry material content warnings? Extracted-content evidence and declared thresholds. |
| `locale-html-lang` | Are HTML `lang` values present, valid, and consistent with the URL locale convention where one exists? HTML attributes and declared locale rules. |
| `near-duplicate-content` | Which canonical page pairs remain near-duplicates after the declared text normalisation and extraction process? Content hashes/similarity evidence and comparison population. |
| `canonical-declarations` | Are canonical declarations present, absolute where required, singular, syntactically valid, and internally consistent? Raw HTML canonical inventory. |
| `canonical-target-validation` | Are canonical targets reachable, indexable, in scope where expected, and free of chains or loops? Canonical target and response/indexability evidence. |
| `hreflang-html-http` | Are HTML and HTTP-header hreflang annotations parseable, reciprocal, self-referencing where required, and targeted at valid URLs? Hreflang inventory and target evidence. |
| `hreflang-sitemap` | Are sitemap hreflang annotations retained and validated separately from HTML/HTTP annotations? Sitemap extension inventory and target evidence. |
| `hreflang-noindex` | Do noindex, blocked, canonicalised, or redirected alternates invalidate hreflang clusters? Hreflang, canonical and indexability evidence. |
| `locale-redirects` | Do locale and geo requests redirect consistently without trapping users or search bots? Explicitly authorised geo/locale probe evidence. |
| `schema-parser-diagnostics` | Which JSON-LD, Microdata, or RDFa blocks fail to parse or have detectable structural defects? Structured-data parser evidence. |
| `structured-data-feature-rules` | Do implemented schema types meet the relevant rich-result feature rules, including required and conditional properties? Typed structured-data evidence and documented rule set. |
| `rendered-indexing-parity` | Do raw and rendered pages materially differ in canonicals, directives, metadata, primary content, internal links, or schema? Paired raw/rendered evidence. |
| `mobile-rendering-parity` | Does mobile rendering expose the same indexable content, directives, canonical, links, and critical resources as the declared baseline? Explicit mobile render evidence. |
| `critical-resource-impact` | Do blocked, failed, or challenged CSS, JavaScript, fonts, APIs, or third-party resources materially affect rendering or indexing? Render trace and resource evidence. |
| `nonhtml-search-assets` | Are PDFs, feeds, video/image assets, and other search-relevant non-HTML resources discoverable, indexable, and correctly served where applicable? Supplied or collected asset inventory. |
| `performance-distribution` | What are the URL-level performance distributions and worst outliers for the collected metrics? Performance samples, percentiles and denominators. |
| `conditional-cache-behaviour` | Do conditional requests and cache validators behave correctly for the sampled URLs? `ETag`/`Last-Modified` and conditional-request evidence. |
| `validated-bot-log-analysis` | What do verified search-bot logs show about crawling, response outcomes, and waste? Supplied logs with verified bot identity. |
| `supplied-search-evidence` | What do supplied Search Console, URL Inspection, CDN, origin, or analytics records add to the crawl conclusions? Supplied source evidence and time range. |
| `recipient-action-eligibility` | Which findings have a named owner, evidence, impact, next action, and any needed business/context qualification? Audit finding records and supplied context. |
| `healthy-overview` | Which controls have affirmative evidence of healthy behaviour and may be reported as healthy? Passed/qualified rows from this contract. |
| `artifact-validation` | Is the produced JSON/Markdown/XLSX internally consistent, reproducible from the selected inputs, and safe to publish? Artifact validation evidence. |

## Result model

Use these states exactly:

| State | Meaning |
|---|---|
| `pass` | The declared population was tested and produced no qualifying issue. |
| `finding` | The declared population was tested and produced one or more qualifying issues. |
| `partial` | Only a stated subset was tested, or a material qualification limits the result. |
| `unavailable` | The check could not run because a required input was absent, unusable, or out of scope. |
| `not_applicable` | The check does not apply to the declared site or audit scope, with evidence for that conclusion. |

Each row must contain: the stable ID, state, denominator and tested count where
applicable, affected count, exclusions, input provenance, evidence references,
collection timestamp or selected run ID, and a concise qualification. Counts
must never be presented as complete if the row is `partial` or `unavailable`.

`check_registry` may describe implementation details, but it cannot replace a
row in `checks[]`. A check is considered covered only when its runtime row is
present with an admissible state and evidence.

## Workflow

1. Select one saved crawl run and record its ID, scope, crawl start/end,
   collector version, settings, seeds, and data freshness.
2. Run the deterministic audit first. Emit all contract rows before producing
   narrative findings or a ticket queue.
3. Add authorised current-site probes only as evidence for the matching rows.
   Record request configuration, fetch time, locale/proxy, user agent and the
   response artefact. Never overwrite the saved-run result with a live probe.
4. Reconcile the rows, preserve raw and normalised counts, and write findings
   only from rows whose evidence supports the claim.
5. Validate the published artifacts against `artifact-validation`.

The report must identify the run as a historical crawl when it is historical.
Current robots, sitemap, HTTP, render, performance, geo and log observations
must carry their own collection time and source.

## Evidence collection rules

### Crawl and database evidence

Use only records attributable to the selected run for any count about discovery,
inlinks, orphan candidates, click depth, authority, or crawl outcomes. A
database table without run identity cannot support a run-level conclusion; emit
`unavailable` or `partial` until a run-scoped source exists.

State the population before calculating a percentage. Examples: indexable
canonical HTML URLs, crawlable HTML URLs, all raw URLs, or sampled external
links. Retain a URL-level evidence export for every finding.

### Live and rendered evidence

Fetch live pages only where the audit authorisation permits it. Honour robots,
stay within the supplied hosts and rate limits, use only supplied credentials
and request headers, and stop when access controls or challenges invalidate the
observation.

Raw/rendered and desktop/mobile comparisons require paired requests of the same
URL, recorded configuration, and a declared comparison basis. A challenge page
is evidence of an access challenge, not evidence of page parity or content
quality.

Locale/geo tests require configured proxies and an explicit test matrix. Bot-log
claims require verified bot identity; reverse DNS alone is insufficient unless
the verification procedure records the required forward confirmation.

### Robots and sitemaps

Keep robots.txt and each sitemap document as current-site evidence. Check
declared sitemap URLs, parser results, status, scope, recursion, duplicate URL
entries, `lastmod` plausibility, and XML hreflang extensions. Do not treat a
sitemap channel as unavailable simply because the saved crawl did not retain
its records; report the distinction between current fetch and historical run.

### Content, metadata, canonical, and hreflang evidence

For near duplicates, record the extractor version, normalisation steps,
comparison universe, threshold, source URLs, and post-normalisation hashes.
Confirm a suspected collision by re-hashing the pages after any extractor fix;
do not promote an inferred cause to a root cause without that reproduction.

Calculate duplicate metadata counts both before and after declared canonical or
alias grouping. Confirm the grouping from canonical targets before reporting a
true duplicate count of zero.

Treat HTML, HTTP-header, and sitemap hreflang as separate channels. Hreflang
target validity depends on the target's final response, canonical, indexability
and reciprocal relationship, not on syntax alone.

### Structured data

Parse every discovered syntax before applying feature rules. Apply a feature
rule only to matching types and distinguish physical-event requirements from
virtual-event eligibility. Required, recommended, conditional and inapplicable
properties must produce different outcomes. `BreadcrumbList` validation must
inspect its `itemListElement` items, their position/order, names and item URLs;
the list's existence alone is not a pass.

### Performance and conditional requests

Report URL-level samples, timing mode, population size, percentiles, outliers,
and collection conditions. For conditional requests, preserve initial response
headers and the subsequent request/response pair; distinguish a missing
validator from a broken validator.

## Findings, tickets, and reporting

A finding must name the corresponding contract ID, exact evidence, population,
affected count, impact, proposed action, owner where known, and a validation
method. Qualify uncertainty rather than using absolute language that the
evidence cannot support.

Create remediation tickets only for `finding` or action-bearing `partial` rows.
Each ticket must include the check ID, reproduction query or function, affected
URL examples, acceptance criteria, expected state after remediation, and a
rerun command or evidence recipe.

Report healthy controls only from `healthy-overview`; it must link back to
qualifying `pass` or `not_applicable` rows. Apply any recipient/request filter
to the presentation after computing the complete result. Keep excluded findings
in the full artifact with their filter rationale.

Before delivery, validate that:

- `checks[]` has every contract ID once and in contract order;
- every claim and ticket links to an emitted row and evidence;
- totals reconcile with their URL-level exports and declared denominator;
- unavailable/partial inputs are visible in the summary;
- rendered, current-site, log, and supplied evidence remain distinguishable
  from the saved crawl run; and
- JSON, Markdown, spreadsheet, and ticket artifacts agree on IDs, counts,
  states, and scope.
