---
name: technical-seo-audit
description: Run evidence-based technical SEO audits from crawler artifacts, PostgreSQL crawl stores, live fetches, XML sitemaps, robots.txt, Search Console findings, or supplied URL lists. Use when Codex must diagnose crawl/indexability problems, recheck failed URLs, audit internal links, canonicals, hreflang, parameter traps, redirects and URL variants, validate structured data or rich-result eligibility, diff rendered versus raw HTML, detect soft 404s and orphan pages, test locale/geo redirect behaviour through configured proxies, or produce a styled XLSX/Markdown technical-audit deliverable.
---

# Technical SEO Audit

Perform a reproducible audit that separates historical crawl evidence from current live behaviour. Report only demonstrated issues, quantify their scope, provide affected URLs and source links, and state caveats.

## Workflow

1. Reconcile the requested domain, crawl seed/allowed hosts, requested and final response URLs, and declared canonical host before selecting the newest relevant crawl artifact or persisted run. Probe homepage and deep-path equivalents when a mirror or host mismatch appears. Preserve historical request identities; attribute canonical relationships separately rather than rewriting source URLs.
2. Record run ID, dates, status, configuration, URL totals, response totals, and incomplete records.
3. Analyse stored data at scale.
4. Recheck unstable or failed results live with an appropriate browser-like backend.
5. Where public-HTML caching is material to the brief or measured crawl cost, test conditional requests using real HTTP validators.
6. Fetch current `robots.txt` and XML sitemap files independently of stored discovery flags.
7. Render a small representative page sample and diff rendered output against raw HTML for indexing-relevant divergence.
8. Compare current and historical evidence; label each result accordingly.
9. Apply the recipient-value filter before producing the audit and detail tabs.
10. Validate the output artifact before delivery.

## Deterministic evidence bundle

When the evidence is in a `crawler_cli` run, start the stored-data pass with
the repeatable command below. It produces an immutable-input JSON projection
before any live rechecks or client-facing interpretation:

```bash
crawler-cli technical-audit \
  --postgres-dsn "$DSN" --crawl-run-id "$RUN_ID" \
  --out audit-evidence/technical-audit.json
```

The runner combines run-scoped saved-crawl reports into an evidence bundle.
Depending on available data and prerequisites, it covers crawl integrity,
directive conflicts, internal-link quality, tracking parameters, orphan and
redirect candidates, near duplicates, schema diagnostics, image markup,
internal authority, metadata/locale, canonical targets, and HTTP hreflang.
Bounded live checks for link rechecks, current robots/sitemaps, URL variants and
soft 404s, rendered/mobile/resource differences, and conditional requests are
conditional on explicit options, authorized scope, and usable source data. The
registry in each output records the check state and qualification; implemented
does not mean every site's population was testable. Access-log bot identity,
geo-dependent behavior, field Core Web Vitals, independent browser traces,
current rich-result eligibility, and business severity/value remain dependent
on supplied sources or analyst judgment. Missing or partial evidence is
unknown/incomplete, not a clean pass.

The output's `skill_requirements` inventory maps every skill section to its
separate requirement controls, support state, evidence boundary, acceptance
test, and owning ticket. It is a static traceability map, not proof that a
check ran; use `checks` and their denominators for the selected audit run.

The client `Audit Log` is a recipient-filtered action list, not a dump of every
check. Historical link failures do not become client failures until eligible
live rechecks confirm them; recovered and inconclusive targets stay out of
current-failure totals. Summary rows retain historical and live status
separately, quantify grouped link actions, and identify evidence references.
Review candidate inventories and the output check registry before delivery.

To copy a Google Sheets audit template and populate only the tabs that have
evidence, make publishing explicit:

```bash
crawler-cli technical-audit \
  --postgres-dsn "$DSN" --crawl-run-id "$RUN_ID" \
  --out audit-evidence/technical-audit.json \
  --publish-google-sheets \
  --google-sheets-template 'https://docs.google.com/spreadsheets/d/TEMPLATE_ID/edit' \
  --google-sheets-title 'Example Technical SEO Audit'
```

This creates a copy of a compatible v2 template, preserves formatting outside
the managed ranges, and writes the populated summary and evidence tabs. The
contract is versioned at `crawler_cli/templates/technical-audit-sheets-v2.json`;
the publisher does not treat arbitrary workbooks or v1 templates as compatible.
It uses OAuth from `GOOGLE_DOCS_OAUTH_TOKEN_FILE` or an explicitly supplied
service-account credential. Publishing needs `crawler-cli[google-sheets]`; do
not put credentials in the repository or output. It is an optional external
write and must be explicitly requested. See
`crawler_cli/docs/technical-audit-google-sheets.md` for access, receipts,
read-back, and recovery behavior. Local contract/mocked tests do not replace a
live publication check against a disposable copy.

The bundle does **not** replace any conditional check that could not run,
Search Console or validated access-log evidence, business intent/severity, or
recipient-value review. Use the per-check registry and qualifications to see
what was run, what was partial, and what remains unavailable or manual; do not
describe an unrequested check as tested merely because its implementation
exists.

When the crawl is stored by `crawler_cli`, include these run-scoped reports in
the evidence pass:

```bash
crawler-cli report image-issues internal-link-quality \
  tracking-parameter-links near-duplicates internal-authority \
  --postgres-dsn "$DSN" --crawl-run-id "$RUN_ID" --format csv --out audit-evidence/
```

Near-duplicate reporting requires a crawl run created with content hashing.
Image reporting requires a v8-or-newer crawl that persisted image references.
Absence of rows from an older run is not evidence that the site has no image
issues.

Do not silently treat a failed or partial crawl as complete. Do not infer missing metadata from a response whose HTML was not decoded or stored.

## Fetching Rules

- Respect robots.txt during discovery unless the user explicitly authorises otherwise.
- Use `curl_cffi` browser impersonation or Playwright when ordinary HTTP clients receive CDN/bot-protection responses. A plain-client 403 does not prove search-engine blocking.
- Never present a 403 to a **spoofed** search-engine user-agent as evidence that the search engine is blocked. Cloudflare and similar providers verify bot identity by reverse DNS/IP, so a fake `Googlebot` from a non-Google address is *expected* to be challenged. Compare three clients - plain, browser user-agent, spoofed bot user-agent - report the pattern, and resolve real bot treatment only through Search Console URL Inspection (live test), CDN bot-event logs, or server logs.
- Follow redirects when validating final status, but also capture the initial status, every hop, final URL, response time, content type, and error.
- Capture full response headers on every live fetch. `X-Robots-Tag` and `Link: rel="canonical"` / `Link: rel="alternate"; hreflang=...` headers carry indexing directives that never appear in the HTML; evaluate them alongside meta tags and flag header-versus-HTML conflicts as defects.
- Keep live concurrency conservative. Record the recheck timestamp.
- Use Search Console URL Inspection, Rich Results Test evidence, CDN events, or origin logs when supplied; distinguish those sources from crawler observations.

### Geo proxies

Geo-dependent checks (locale auto-redirects, geo-blocking, IP-based content variation) require requests from the relevant region. Read proxy definitions from `~/.config/seo-audit/proxies.json`:

```json
{
  "proxies": [
    {"name": "de-res", "geo": "DE", "type": "residential", "url": "http://user:pass@host:port", "notes": ""}
  ]
}
```

- Pass the proxy to the fetch client: curl `-x`, `curl_cffi` `proxies={"http": url, "https": url}`, Playwright `launch(proxy={"server": ..., "username": ..., "password": ...})`.
- Record which proxy (name and geo, never credentials) served each geo-dependent observation.
- If the file is missing or has no proxy for a required geo, report the check as "not testable from geo X" rather than substituting a local fetch.
- Never write proxy URLs or credentials into deliverables, logs, or committed files.

### Rendered versus raw HTML

Plain fetches miss content injected or altered by JavaScript. Render a representative sample (10–20 pages across material templates) with Playwright and diff against the raw HTML for:

- title, meta description, meta robots, and canonical changed or injected after render
- internal links present only in the rendered DOM (client-side navigation, lazy-loaded lists)
- structured data injected by JavaScript
- content blocks absent from raw HTML

For each client-facing metadata allegation, retain the requested URL, HTTP response title/description, rendered values, final browser URL, canonical, observation time and access state. A generic homepage title is not defective on the homepage or an equivalent casino landing page merely because it is reused; establish the page purpose. Historical duplicate/missing counts are candidate inventories until live evidence supports affected examples. When direct loads and internal navigation differ, record both states rather than generalising one to every visit.

For hidden-content allegations, inspect the exact DOM element and its ancestors after readiness and relevant scrolling, compare with visible copies, and retain a screenshot of the actual state. A class name such as seo, one opacity reading, or duplicate text alone does not establish search-only intent or a hidden-text policy violation. Contradictory user evidence requires reconciliation or withdrawal before publication.

Flag any divergence that changes an indexing signal. If key signals exist only in rendered output, state that all raw-HTML-based conclusions for that template carry a rendering caveat, and prefer rendered evidence for those checks. State the sample size and templates covered.

Maintain a compact coverage matrix in analyst evidence: template, locale, device, raw/rendered extraction, denominator and outcome (tested, inconclusive, unavailable, or not applicable). Include representative mobile renders by default for public search audits; compare desktop where parity is relevant. Expand samples around divergent templates instead of treating 10-20 pages as universal sufficiency. Use a bounded, recorded readiness condition for primary content and indexing signals; recheck empty or incomplete states after a longer wait and inspect failed API/resource requests before treating them as content defects. Exclude hidden text, shared boilerplate and restriction overlays from primary-content readiness or thin-content measures; document the access state and avoid prescribing removal of required regional controls. Capture pre-interaction links separately from links revealed by scrolling or controls. JavaScript-rendered content or links are not inherently unindexable; distinguish demonstrated failures from rendering dependencies and optional server-rendering improvements.

## Crawl Integrity

Check:

- run completion state and interruption reason
- crawled, blocked, skipped, failed, persisted, and HTML-decoded counts
- robots and sitemap configuration
- host/path restrictions and seed source
- CDN challenges, compression/decoding gaps, timeouts, and persistence failures
- material locale or template coverage differences

Exclude undecoded/absent HTML records from title, H1, canonical, schema, word-count, and indexability conclusions. Report the excluded population.

### Discovery-source integrity

Count URLs by discovery source (seed, link, sitemap, robots sitemap, archive) for analyst QA. These are crawl-tool observations, not automatically site findings:

- **Zero sitemap-sourced URLs while sitemap discovery was enabled.** Fetch the current sitemap independently and avoid claims that require historical sitemap ingestion. Do not put provenance counts, client user-agent experiments, resume behaviour, or a suspected crawler/CDN cause in the client Audit Log when there is no site action. At most, add a concise scope caveat if the gap materially limits a conclusion.
- **Zero redirects recorded.** Verify important redirect paths live. Do not report missing crawler redirect history, “redirect hygiene not assessed,” or other tooling limitations as a site defect. Report only demonstrated live redirect problems.

### Multi-run and multi-site stores

A persisted store often holds several sites and runs in shared tables. Scope every query by run ID (or the run's snapshot table) before quoting any number. Totals taken from the global tables will silently mix sites and inflate every count.

## HTTP Status and Link Graph

For every non-2xx URL:

- group by final status and page template
- recheck live
- distinguish persistent 404/410, recovered transient 5xx, redirect, challenge, and fetch failure
- count internal link instances and unique source pages
- export source URL, target URL, anchor text, XPath/location, source indexability, and historical/live status

Recommend the closest relevant 301 for replaced content, 410 only when removal is intentional and no substitute exists, and removal of internal/sitemap references in either case.

After live rechecks, build broken-link counts and detail tabs from **currently failing targets only**. If a historical 5xx URL now returns a successful response:

- exclude the URL from persistent-error and failed-link tabs
- exclude all links to it from broken-link totals and source-to-target exports
- add only one aggregate warning that periodic 5xx responses occurred and recommend availability monitoring
- do not recommend changing links solely because of a resolved transient response

Retain URL-level detail for 5xx responses only when they still fail, remain unstable across repeated checks, or logs demonstrate an ongoing pattern.

### Soft 404s and error handling

- Detect soft 404s: 200 HTML pages whose content is an error or empty-result template (error phrases, near-zero unique content, near-duplicate of the site's error page). Use template-aware thresholds and confirm examples live before reporting. Recommend a real 404/410 or, for replaced content, a 301.
- Probe a deliberately non-existent path per host and template area. Prefer a genuine 404/410. Check rendered error handling and noindex before calling a 200 SPA response an indexability defect; Google also documents client-side noindex or a redirect to a real 404 endpoint. A successful fallback is a soft-404 risk, not proof Google indexed the URL. Synthetic probes alone do not demonstrate substantial crawl waste or justify High severity.

### Orphan pages and crawl depth

Join the sitemap URL set and any Search Console-known URLs against the internal link graph. URLs with zero observed internal inlinks are orphan candidates until crawl coverage and reliable link extraction support a stronger conclusion. An incomplete graph, sitemap-only discovery, or an application shell with no raw links cannot establish orphan status, true click depth or internal authority. For JavaScript sites, validate representative navigation and pagination in rendered output, recording discovery edges and bounded coverage; export candidates with their discovery source and indexability. Report the crawl-depth distribution (clicks from the seed/homepage) for indexable pages, and flag templates whose inventory sits materially deeper than comparable templates.

When an analytics landing-page export is supplied, add its URLs as a labelled
discovery source before calculating orphans. Live-validate every resulting URL;
historical traffic does not prove that a URL should remain indexable.

### Internal authority and link quality

Calculate relative internal authority over canonical, indexable HTML pages and
review important URLs whose score, unique inlinks, or crawl depth is materially
worse than peer templates. Also inventory empty anchors and internal links to
redirecting, failing, non-indexable, parameterised, or non-canonical targets.
Use the site's distribution and template purpose rather than universal score or
outlink thresholds. Rendered-only important navigation belongs in the
raw/rendered divergence evidence.

### External-link integrity

For a bounded crawl of external links, use conservative concurrency and recheck
failures before reporting. Export source URL, target URL, anchor text, DOM
location, initial/final status, redirect chain, DNS/TLS error, and recheck time.
Report confirmed 4xx/5xx, DNS, and certificate failures; do not turn third-party
latency or one transient response into a defect. Separately identify insecure
form actions, protocol-relative resources, and user-supplied outbound links that
lack appropriate `ugc`, `nofollow`, or `sponsored` treatment. Never recommend
blanket `nofollow` for ordinary editorial citations.

### Image and critical-resource evidence

Inventory `img/src`, `srcset`, `<picture>` sources, rendered lazy-loaded images,
and important CSS backgrounds. Distinguish a missing `alt` attribute from an
intentional empty `alt=""`; do not flag decorative images merely for having
empty alternative text. Map every issue to its source page and DOM location.
Check response status, MIME type, robots accessibility, intrinsic versus display
dimensions, explicit width/height, transfer size, and image sitemap inclusion
where image search matters. Report sizing/format findings only when measured
delivery or layout evidence supports them.

Map failed or robots-blocked CSS, JavaScript, font, and image resources back to
affected pages. Report only dependencies that change visible primary content,
links, metadata, structured data, or measured rendering/layout behaviour.

## Domain and URL Configuration

Test both homepage and representative deep paths for:

- `http://domain`
- `http://www.domain`
- `https://domain`
- `https://www.domain`
- trailing slash and no trailing slash
- mixed-case/CamelCase path and locale variants
- encoded versus decoded forms when applicable
- duplicate query ordering when applicable

Establish the intended canonical HTTPS hostname. Use direct permanent redirects for retired host variants; an intentionally retained equivalent mirror may use cross-domain canonical annotations instead. Evaluate business intent and signal consistency before prescribing retirement. Flag demonstrated multi-hop or inconsistent redirects. Test several page templates before calling slash behaviour systemic.

Treat case sensitivity carefully. Test it if useful for diagnosis, but do not include mixed-case/CamelCase failures in the deliverable unless internal links, sitemaps, logs, backlinks, or a supplied migration requirement demonstrate real affected URLs. Never recommend blind lowercasing when identifiers may be case-sensitive. Pair case, trailing-slash, index.html, plus/percent-encoding and query probes with valid route/entity controls and deliberately nonexistent routes. Synthetic probes can corroborate an existing route-validation or soft-404 finding without proving discovery demand. Derive recommended canonical identities from validated route/entity mapping: redirect recognised equivalent aliases directly with 301/308, and return 404 for nonexistent entities. Preserve intended locale slash conventions and case-sensitive identifiers; a plus in a path is not automatically equivalent to an encoded space. Distinguish tracking parameters from parameters that identify meaningful content. A small probe set supports an observed pattern, not a universal claim about application source code.

### Non-production hosts and HTTPS hygiene

- Inventory every host observed in the crawl, canonicals, hreflang, sitemaps, and redirects. Probe likely non-production hosts (`dev.`, `staging.`, `test.`, `preview.`, bare CDN hosts) for indexable duplicate content; spot-check exposure with `site:` queries or URL Inspection where available. Recommend authentication or `noindex` plus canonical for exposed environments - not robots.txt alone, which leaves already-indexed URLs stranded.
- On HTTPS pages, check for mixed content (`http://` scripts, stylesheets, iframes, images) and for internal links, canonicals, and hreflang targets still pointing at `http://` URLs. Report certificate errors encountered during fetching.

## Robots and XML Sitemaps

Fetch the live sitemap index and every child sitemap. Do not rely only on a persisted `is_from_sitemap` flag or discovery-source table; sitemap contents may have changed after the crawl.

Check sitemap URLs for:

- final 200 status
- canonical indexable HTML
- absence of `noindex`
- canonical URL equality
- host/protocol consistency
- duplicates and parameter variants
- locale placement
- credible `lastmod` values

Select sitemap live checks from both crawled matches and never-crawled entries, stratified across material templates and locales. Preserve the selection basis and exact selected URL list. Report metadata/content anomalies alongside status, canonical and indexability signals: 200 plus self-canonical alone is not a healthy-content verdict. State sample imbalance and do not extrapolate a game-heavy sample to every template or the full corpus. Child sitemaps discoverable through a valid sitemap index do not each require a robots declaration.

Compare the live sitemap URL set with stored indexability. Label a mismatch as “current sitemap versus saved crawl” unless live indexability was also rechecked. Spot-check live examples before prioritising the issue.

Use per-locale counts as corroboration, not just per-URL joins: compare the URL count of each locale sitemap with the number of indexable pages the crawl found in that locale. A close match corroborates consistency but does not establish intended eligibility: the same faulty rule could generate both outputs. Validate URL-level overlap and corroborate intent with the eligibility policy, configuration or site owner before describing suppression as deliberate. Where sitemaps could not be ingested by the crawl, fetch a representative subset of locale sitemaps live and state the sample size and date.

Check robots.txt for:

- sitemap declaration, including malformed ones - a bare sitemap URL on its own line with the `Sitemap:` prefix missing is ignored by search engines, so the file reads as declaring no sitemap even though one is published and healthy. Probe any bare `.xml` URL found in the file before concluding a site has no sitemap, and report a one-line syntax error as exactly that rather than as a missing sitemap
- accidental blocking of intended organic pages or assets
- crawl traps and utility endpoints
- parameter rules
- user-agent-specific contradictions

Validate the robots parser before filtering discovery or reporting blocked links. Use Google-compatible RFC 9309 matching, including user-agent groups, blank directives/comments, wildcard/end anchors, longest matching rule and Allow on equal specificity. Test at least one known allowed and one known blocked URL against the actual file; a silently empty ruleset must not become an all-allowed finding. Record the matched rule and user agent. Do not fetch disallowed targets just to confirm their status.

Evaluate rendered internal links against all applicable robots rules, not only sort/filter parameters. Export source URL, device, target, anchor, matched rule and timestamp. Report instances, unique targets and unique sources separately. Classify each blocked family by navigation purpose: necessary utility links are not automatically defects, and removing useful navigation or unblocking private/utility pages solely to eliminate a count is not an acceptable recommendation.

Do not use robots.txt as a replacement for canonicalisation, noindex processing, redirects, or crawl-path cleanup. Blocking a URL can prevent search engines from seeing those signals.

## Indexability and Crawl Waste

For successfully parsed 200 HTML pages, segment indexable, noindex, and unknown pages by locale and template. Quantify:

- URL count and share
- clean-path versus parameter URLs
- internal link instances and unique linking pages
- XML sitemap inclusion
- canonical presence
- content depth only when extraction is reliable

Decide whether a large noindex population represents intentional eligibility rules or accidental suppression. Recommend reducing internal discovery and sitemap exposure for intentionally excluded inventory.

### Growing URL families and crawl traps

Group rendered links by route family as well as query key. Look for live-feed bet/transaction IDs, user profiles, session URLs, calendars and other potentially unbounded spaces. Quantify unique targets, link instances, source pages, device observations and share of internal links, with the internal-only denominator stated. Repeated observations with timestamps are required to claim an ID growth rate; discovery evidence alone does not measure Google crawl cost.

Prefer removing unnecessary crawlable anchors while preserving accessible interactions. If public pages should be excluded, Google must be allowed to crawl their noindex directive. Any later robots restriction is a separate crawl-management decision after considering existing indexation; do not prescribe robots blocking plus noindex as a simultaneous solution. Nofollow alone is not reliable primary prevention.

Validate extraction schemas before counting: a missing link field or unsupported parser result means unknown/failed extraction, not zero issues. Retain analyst/parser diagnostics outside the client action list unless needed to interpret a result.

### Hreflang on noindex pages

Do not report missing self-reference, reciprocity, or incomplete hreflang clusters as separate defects on noindexed pages. State only that it is advisable not to output hreflang at all on noindexed pages because they cannot participate in indexed alternate clusters.

## Parameter and Faceted URLs

Inventory parameter keys and combinations. Segment them by indexability, canonical target, hreflang target, content uniqueness, and internal discovery source.

Explicitly identify internal links containing known analytics/session parameters
such as `utm_*`, `gclid`, `_ga`, and `_gl`. These links create crawl variants and
can overwrite attribution; export the source, target, anchor, and DOM location.

Review at least:

- sort/order parameters
- filters, status, theme, country, location, and search parameters
- date/availability parameters
- tracking and internal metadata parameters
- pagination

Identify every parameter URL that canonicalises to another URL and still receives internal links. Quantify both unique targets and complete link instances, then export source URL, target parameter URL, canonical URL, anchor text, XPath/location, source indexability, and parameter keys. Treat links to these non-canonical variants as the primary crawl-path defect; canonical/noindex directives do not prevent crawlers from repeatedly discovering and fetching the linked URLs.

For state-only sort/filter/date controls with no independent search value:

- remove `<a href="?...">` links to the parameter variants; do not leave a crawlable href and merely intercept it with JavaScript
- render the control as an accessible `<button>`, `<select>`, or equivalent non-anchor UI element
- handle `click`/`change` with JavaScript to update results and, where useful, client-side History API state
- keep clean canonical and noindex handling as secondary safeguards, not as substitutes for removing crawlable links
- preserve keyboard access, labels, focus behaviour, and a functional user experience

Use POST only when it matches the interaction semantics and application architecture. For agreed UI-only interactions, prefer accessible buttons with JavaScript handlers to remove unnecessary anchor discovery, preserving useful navigation and pagination. Do not classify every robots-blocked utility link as a defect. Google supports robots restrictions for unwanted crawl spaces; distinguish crawl prevention from index removal, and do not prescribe noindex as a crawl-saving mechanism. Nofollow is a hint, not a guaranteed exclusion mechanism.

Keep necessary pagination crawlable. If paginated pages remain indexable, use stable self-canonicals, useful metadata, and equivalent hreflang pagination where genuine alternates exist. Do not collapse pagination blindly when it is needed to discover inventory.

Flag conflicting signals such as a parameter URL self-canonicalising while hreflang points to the clean URL.

## Metadata and Content

Analyse indexable, successfully parsed pages first. Check:

- missing or blank title, meta description, and H1
- multiple H1s when semantically problematic
- title and description length as guidance, not automatic defects
- duplicate titles and descriptions within the same locale
- pagination and alias clusters
- thin or empty content with template-aware thresholds
- `html lang` presence and agreement with the locale path

An absent H1 is not evidence of indexing failure. Inspect the existing primary heading and page purpose; where a visible title merely lacks semantic heading markup, recommend marking up that title as a low-priority structure improvement rather than adding redundant copy or inferring missing content.

Do not count expected cross-locale reuse as same-locale duplicate metadata. Provide every affected URL for actionable duplicate clusters.

Cluster near-duplicate primary content using normalized main-content fingerprints
in addition to exact hashes. Analyse indexable pages by default, exclude exact
duplicates from the near-duplicate population, and provide representative pairs,
similarity evidence, template, and canonical/indexability state. An optional
all-URLs pass is appropriate when investigating crawl waste.

## Conditional Access-Log Analysis

When sufficiently complete CDN/origin access logs are supplied, verify genuine
search-bot identities using published IP ranges or reverse-DNS rules and analyse
bot crawl frequency by URL/template/directory, repeated redirects and errors,
response-time trends, inconsistent statuses, non-canonical crawl waste,
important URLs never fetched, and bot-discovered orphans. Keep this separate
from crawler observations. A claimed bot user-agent without identity validation
is not search-engine evidence, and absence of logs means this module was not
tested-not that bot crawling is healthy.

## Canonicals

Check indexable pages for missing, multiple, malformed, non-HTTPS, cross-host, parameterised, and non-self canonicals. For every non-self canonical, validate that the target:

- resolves directly or through an intentional redirect
- returns 200
- is indexable
- is the intended equivalent
- is not itself canonicalised elsewhere

Distinguish deliberate consolidation from contradictory “index + canonical elsewhere” behaviour.

Evaluate `Link: rel="canonical"` HTTP headers and `X-Robots-Tag` headers together with the HTML tags: a header directive contradicting the meta tag on the same URL is a defect, and non-HTML resources (PDFs, feeds) can carry directives only via headers.

## Hreflang on Indexable Pages

For indexable source pages, check:

- valid language/region codes
- self-reference
- reciprocal references
- canonical, indexable 200 targets
- matching content purpose
- one intended `x-default`
- parameter/page equivalence

Do not extend these defect checks to noindexed source pages; apply the noindex guidance above.

Hreflang may be declared in HTML `<link>` elements, XML sitemap `xhtml:link` entries, or HTTP `Link` headers. Check all channels the site uses; where more than one channel declares annotations for the same URL, flag disagreements between them as defects and identify which channel is authoritative for the fix.

### Locale auto-redirects

Search engines crawl mostly from US IPs with no `Accept-Language` preference. If the site 302s or rewrites visitors to a local version based on IP or `Accept-Language`, alternate URLs may never be crawlable as distinct pages and the hreflang cluster silently collapses.

- Fetch representative alternate URLs with no `Accept-Language` header and from a non-matching geo (use the configured geo proxies) and confirm each alternate returns its own 200 content rather than redirecting away.
- Flag forced IP/language redirects on alternate URLs as a High defect. Recommend suggesting the local version via banner or hreflang instead of redirecting, and never auto-redirecting away from a URL that hreflang points to.
- If no proxy covers the needed geo, state that geo-conditional behaviour was tested only from the audit location.

## Structured Data and Rich Results

Do not equate valid JSON or Schema.org syntax with Google rich-result eligibility. Inspect raw live JSON-LD and validate Google-required properties by feature.

For each detected type, establish the currently supported Google feature, eligible content type, page format and any regional restrictions before testing required properties. Consult the current [feature documentation](https://developers.google.com/search/docs/appearance/structured-data/search-gallery); distinguish required fields, recommended fields and ordinary Schema.org validity. Unsupported rich-result eligibility or absent optional markup is not a defect by itself.

For `ItemList`/Carousel, use the [current format-specific requirements](https://developers.google.com/search/docs/appearance/structured-data/carousel). A summary-page `ListItem` can use `@type`, `position` and `url`; do not universally require outer `name`/`numberOfItems`, item names, or nested `item` objects. Where counts or positions are declared, check consistency. Validate nested content only for formats that use it, and check relevant URLs/images for accessibility and content equivalence.

When one page fails Rich Results Test, find the precise item/position, then scan every stored `ItemList` across the corpus for the same structural defect. Export listing page, position, item name, target URL, defect, and fix.

Also inspect Breadcrumb, FAQ, LocalBusiness, Organization, WebSite, and other detected types for required properties relevant to their Google feature. Treat JSON-LD found only inside comments or inert templates cautiously; confirm it is actually exposed as structured data before flagging it.

## Performance as a Crawl-Budget Signal

Report response-time distribution from stored crawl timings, not a single average: mean, p90, p99, and worst case for TTFB and total duration. Relate it to crawl surface - a slow origin combined with a large crawlable URL count is a direct constraint on how much of the site gets refetched, and it is often the cheapest fix on the list. Flag outliers by template rather than by individual URL, and separate CDN-cached from origin-rendered responses when the headers allow it.

Where browser traces are available, diagnose lab performance with render-blocking
resources, unused CSS/JavaScript, main-thread work, cache policy, network payload,
DOM size, LCP request discovery, font loading, responsive image selection, and
layout shifts. Keep CrUX or GSC field Core Web Vitals separate from Lighthouse or
local lab observations; never present a lab score as real-user field performance.
Report large DOMs/files or unused code only when they contribute materially to a
measured performance or rendering problem.

## Conditional Mobile and Non-HTML Checks

Include representative mobile rendering in public search audits. When responsive divergence, separate mobile URLs, consent layers, or intrusive
overlays are relevant, compare paired mobile and desktop viewports for
primary text, links, metadata, schema, images, and usable controls. Record any
overlay that prevents access to primary content; do not turn this into a generic
visual-design or full accessibility audit.

When PDFs, feeds, video, or other searchable assets are present and important,
check response/indexability, internal discovery, sitemap inclusion where
supported, HTTP `Link` canonicals, `X-Robots-Tag`, obsolete duplicates, and the
quality of the linking/landing-page context. Do not create a large asset audit
when the site has no material non-HTML search surface.

## Conditional Requests and 304 Rechecks

When conditional caching is material to the brief or observed delivery cost, select a deterministic sample of canonical public HTML across relevant templates and locales. Scale the sample to variation and state its selection basis. Do not require a dedicated caching ticket or tab when results show no fault or meaningful optimisation opportunity.

For each sampled URL:

1. Make an ordinary GET and capture final status/URL, `ETag`, `Last-Modified`, `Cache-Control`, `Age`, CDN cache status, response bytes, and timestamp.
2. Send `If-None-Match` and/or `If-Modified-Since` only when the server supplied the corresponding validator.
3. Capture the conditional status, response bytes, and whether a repeated `200` body was unchanged.
4. Never fabricate a validator or use the response `Date` as a substitute for `Last-Modified`.

Report validator coverage across the whole sample and the 304 rate among validator-eligible pages. If no validators are exposed, say that conditional requests were not testable and recommend ETag/Last-Modified plus correct 304 handling where safe for public HTML. If validators exist but unchanged pages return `200`, flag cache/origin configuration for review. A changed repeated representation returning 200 does not establish faulty validator handling. Keep speculative caching improvements as optional notes, not remediation defects. Present measured inefficiency as a crawl-efficiency warning, not a ranking factor.

## Report What Is Healthy

An audit that lists only defects is easy to dismiss and hard to prioritise. Include a short evidence table for the indexable population - counts of missing title/H1/meta description/canonical/hreflang, thin pages, duplicate-content groups, average depth - even when most rows are zero. This establishes that the checks ran, sets the denominator for every percentage quoted elsewhere, and makes the genuine defects stand out instead of competing with routine findings.

## Reporting

Lead with evidence and business impact. Use these severity defaults:

- High: demonstrably prevents indexing of important pages, causes persistent errors, or creates material crawl waste. Prioritise rich-result defects by affected reach and business value rather than assigning High automatically.
- Medium: conflicting signals, duplicate indexable URLs/metadata, transient availability, or systemic quality risk.
- Low: defensive hardening or cleanup without demonstrated search impact.

### Recipient-value filter

The Audit Log is a decision list, not a transcript of every check. Include only demonstrated site issues and material warnings that a recipient can understand, prioritise, or monitor.

Before adding any row, require at least one of:

- a verified current defect
- a persistent historical defect confirmed live
- a quantified systemic risk with a practical recommendation
- an explicitly requested warning such as resolved periodic 5xx or missing 304 support

Do not populate the Audit Log or issue tabs with:

- crawler implementation details, resume behaviour, missing provenance, parser limitations, or fetch-client experiments that create no site action
- zero-result checks or statements that an area was not assessed
- defensive mixed-case, encoding, or URL variants without demonstrated internal/external demand
- resolved transient URLs or links to them
- healthy page-by-page inventories where an aggregate Overview metric is sufficient

Keep a necessary crawl caveat to one concise Overview/scope note. Store analyst diagnostics outside the deliverable unless they are required to interpret a result. If a check is healthy, summarise it in Overview; do not create a large “all clear” detail tab.

For XLSX output:

- include only `Audit Log` and `Overview` as summary sheets
- omit a separate methodology or duplicate summary sheet
- add focused detail tabs such as failed rechecks, links to failures, noindex inventory, orphan pages, soft 404s, parameter URLs, sitemap/noindex overlap, duplicate metadata, schema defects, rendered-versus-raw divergences, and redirect checks
- use green headers, filters, frozen header rows, readable widths, and clickable URL cells
- include Problem, Explanation, Fix, SEO Impact, Action Needed, and Resolved columns in the audit log
- include responsible team, named owner (unassigned unless supplied), concrete acceptance criteria, retest status/date and evidence reference for each action; do not claim resolution without verifying the deployed fix
- keep historical and live status in separate columns
- include only persistent live failures in failed-URL and failed-link tabs; summarise resolved 5xx responses as one warning
- include a focused `304 Recheck` tab only when the conditional-request evidence merits recipient attention; otherwise retain it in analyst evidence
- avoid exceeding Excel’s row limit; aggregate huge link graphs and provide a clearly labelled sample plus complete per-target inventory

For Markdown output, include scope/date, priorities, evidence counts, examples, recommendations, and caveats.

## Validation

Before delivery:

1. Re-run every historical failed URL live and remove resolved 5xx URLs/links from failure populations.
2. Document conditional-request results when relevant; do not manufacture a caching defect from changed 200 responses.
3. Confirm current sitemap and robots responses.
4. Apply the recipient-value filter and remove crawler noise/non-actionable diagnostics.
5. Open generated XLSX files with a spreadsheet parser.
6. Verify sheet names, headers, hyperlinks, representative rows, and file size.
7. Confirm counts in the overview agree with detail tabs or explicitly explain sampling.
8. Remove stale claims superseded by live evidence.
9. State only uncertainty that materially affects interpretation.
10. Verify coverage prerequisites, sampled versus complete populations, current owner/retest fields, and acceptance criteria. Keep optional optimisation notes separate from remediation totals.
11. Reconcile each client-facing allegation to an exact evidence record and reproduction path. Remove superseded wording from both the summary and detail tabs. Formatting/count checks do not validate the truth of a finding; review observation, interpretation, severity and recommendation separately.
