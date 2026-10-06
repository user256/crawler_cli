# Technical audit ticket language

Generated from [`templates/technical-audit-ticket-language.json`](../templates/technical-audit-ticket-language.json); edit the JSON, not this file. One entry per contract check ID, in contract order, giving the default text for the `Tickets` tab of the [Technical SEO Audit template](https://docs.google.com/spreadsheets/d/1T9BRLgaFDZ99Lx3q53Av75eZZM32BIJc0nahVPQpGmU/edit?gid=0#gid=0).

## How a check row becomes a ticket

- **finding**: Write a ticket from the entry below. Fill every placeholder from the check row.
- **partial**: Write the ticket only when affected_count > 0. Append partial_suffix to the Description and to Notes / Documentation. Never present counts as complete.
- **pass**: No ticket. Report in the Overview as healthy with the tested denominator and run ID.
- **not_applicable**: No ticket. Report in the Overview with the reason the control does not apply.
- **unavailable**: No ticket unless the entry has an unavailable_ticket block, in which case write that block as an Improvement ticket. Always list the control in the Overview as not tested with its missing evidence.

## Placeholders

| Placeholder | Filled from |
|---|---|
| `{site}` | Audited host, for example rainbet.com. |
| `{run_id}` | Selected crawl run ID. |
| `{crawl_date}` | Crawl start date of the selected run (YYYY-MM-DD). |
| `{affected_count}` | check.affected_count in the check's unit, formatted with thousands separators (9,831). |
| `{denominator}` | check.denominator (declared population), formatted with thousands separators. |
| `{tested_count}` | check.tested_count. |
| `{affected_pct}` | affected_count / denominator as a whole-number percentage. Omit the sentence when denominator is null. |
| `{unit}` | The check's unit word: pages, URLs, links, images, clusters, sitemaps, blocks. |
| `{sample_urls}` | Up to five example URLs from check.evidence, one per line. |
| `{evidence_tab}` | check.detail_sheet, the workbook tab that holds the full evidence export. |
| `{missing_evidence}` | check.required_evidence when the state is unavailable. |
| `{qualification}` | check.qualification mapped through qualification_text below; empty when absent. |

## Shared text

- `partial_suffix`: Coverage caveat: only {tested_count} of {denominator} {unit} were tested in run {run_id}, so the counts above are a lower bound, not a site total.
- `recheck_note`: Statuses come from a historical crawl on {crawl_date}. Recheck the sampled URLs live before starting work; intermittent failures and already-fixed items are excluded once a live recheck confirms them.
- `replicate_prefix`: Run `crawler-cli technical-audit --crawl-run-id {run_id}` and open the {evidence_tab} tab of the published workbook. Each row carries the source URL and the observed value.
- `evidence_ref`: Evidence: {evidence_tab} tab ({affected_count} rows), run {run_id}.

## Qualification text

- `recheck_required`: Saved-crawl statuses must be rechecked live before this ticket is assigned.
- `review_required`: These rows are candidates for review, not confirmed defects; confirm each before assigning work.
- `coverage_required`: The link graph for this run is not proven complete, so treat the list as candidates until coverage is confirmed.
- `analyst_only`: This row is analyst evidence; it reaches the client register only after manual qualification.
- `live_confirmed`: Every listed failure was confirmed by a live recheck on the audit date.
- `missing_required_evidence`: The required input for this control was not collected in this run.

## Priority rules

1. Start from the check's default priority.
2. Raise one level when the affected share is at least 20% of the declared population, or when a template-level cause reproduces the defect on every page of that template.
3. Raise to High when the affected URLs include pages with external backlinks, sitemap URLs, or the homepage and main navigation targets.
4. Lower one level when the affected URLs are all non-indexable, blocked, or already scheduled for removal.
5. Never raise a partial or unavailable row above Medium on the deterministic count alone.

## Checks

### `audit-run-integrity`

Overview only, never a ticket.

> Run {run_id} on {crawl_date}: {denominator} URLs fetched, completion state and scope recorded. This row never becomes a ticket; it qualifies every other row.

### `audit-collection-safeguards`

Overview only, never a ticket.

> Collection observed robots.txt, the declared scope and rate limits. Listed so the recipient can see the crawl was safe and in scope.

### `discovery-source-provenance`

**Label:** URLs discoverable only through a single source  
**Classification / Priority:** Warning / Low  
**Unit:** URLs  
**Evidence tab:** Discovery sources

**Description**

> {affected_count} of {denominator} in-scope URLs were discovered by only one route in run {run_id} (for example only from the XML sitemap, or only from internal links). A URL that search engines can reach one way is fragile: if that route breaks the page silently drops out of crawling.
> 
> See the {evidence_tab} tab for each URL and the source that found it.

**Suggested Solution**

> Make important URLs reachable by both an internal link and an XML sitemap entry. For sitemap-only URLs, add crawlable links from a relevant hub or parent page. For link-only URLs that should be indexed, add them to the sitemap.

**Acceptance Criteria**

> - Every indexable URL in the {evidence_tab} tab has at least one in-scope internal link and one sitemap entry.
> - A re-crawl from the homepage reaches those URLs without using the sitemap.

**How to Replicate**

> {replicate_prefix} Filter the tab by discovery source to see sitemap-only and link-only URLs.

**Notes / Documentation**

> Sitemap-only URLs are often the same set as orphan candidates; fix them together.

### `response-status-and-redirect-history`

**Label:** Redirect chains, loops and non-200 internal destinations  
**Classification / Priority:** Issue / Medium  
**Unit:** URLs  
**Evidence tab:** Response and redirects

**Description**

> {affected_count} URLs in run {run_id} did not resolve cleanly: they redirect through more than one hop, loop, or end on a 4xx/5xx response. Every extra hop costs crawl budget, slows users, and dilutes the signals passed to the final page. Chains that end in an error are dead ends for both users and search engines.
> 
> See the {evidence_tab} tab for each start URL, the full hop sequence and the final status.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Point every redirect directly at its final 200 destination in one hop. Fix or remove redirects that end in a 404 or 5xx. Where a chain exists because of protocol and host normalisation (http to https to www), collapse it into a single rule at the edge.

**Acceptance Criteria**

> - Every start URL in the {evidence_tab} tab returns either 200 or a single 301/308 to a 200 page.
> - No redirect loop remains.
> - No internal redirect ends on a 4xx or 5xx response.

**How to Replicate**

> {replicate_prefix} Use `curl -sIL <url>` to confirm the hop sequence live.

**Notes / Documentation**

> {recheck_note} Reference: https://developers.google.com/search/docs/crawling-indexing/301-redirects

### `internal-link-targets`

**Label:** Internal links point at failing URLs  
**Classification / Priority:** Error / High  
**Unit:** links  
**Evidence tab:** Internal link failures

**Description**

> {affected_count} internal links across the crawled pages point at URLs that returned a 4xx or 5xx response in run {run_id}. Broken internal links waste crawl budget, send users to error pages and stop link equity reaching working content. Where the same target is linked from many pages the cause is usually a template or navigation element, so one fix removes many links.
> 
> See the {evidence_tab} tab for each failing target, the number of linking pages and sample sources.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> For each failing target either restore the page, redirect it to the closest live equivalent, or update the links to the intended working URL. Fix template and navigation sources first because they account for most link instances. Remove links to pages that are intentionally gone.

**Acceptance Criteria**

> - Every target in the {evidence_tab} tab returns 200, or a single 301 to a 200 page, on a live recheck.
> - No crawled page links to a URL that returns 4xx or 5xx.
> - Template and navigation links no longer reference the retired URLs.

**How to Replicate**

> {replicate_prefix} Confirm each target with `curl -sI <url>` before assigning work.

**Notes / Documentation**

> {recheck_note}

### `external-link-integrity`

**Label:** Outbound links to dead or unsafe external destinations  
**Classification / Priority:** Issue / Medium  
**Unit:** links  
**Evidence tab:** External link rechecks

**Description**

> {affected_count} of {tested_count} sampled external links fail (4xx, 5xx, DNS failure), redirect somewhere unexpected, or use a non-HTTPS scheme. Dead outbound links harm user trust and page quality signals; links that redirect to unrelated domains can expose the site to spam associations.
> 
> See the {evidence_tab} tab for the source page, destination, status and redirect target.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Remove or replace dead external links. Update links whose destination now redirects to a new domain. Switch http:// links to https:// where the destination supports it. For user-generated links, apply rel="nofollow ugc" and validate destinations on submission.

**Acceptance Criteria**

> - Every external destination in the {evidence_tab} tab returns 200 on a live check, or the link has been removed.
> - No external link uses an http:// scheme where an https:// equivalent exists.
> - No external link resolves to a domain unrelated to its anchor text.

**How to Replicate**

> Run the audit with `--check-external-links` and open the {evidence_tab} tab. Results are live fetches taken on the audit date, not crawl history.

**Notes / Documentation**

> External checks are sampled and bounded by --external-link-max-targets; the tab states how many targets were checked.

**When unavailable:** Authorise an external-link recheck (Improvement / Low)

> External link integrity was not tested because the audit ran without the external recheck option. Outbound link failures cannot be inferred from the saved crawl.

> Suggested solution: Approve a bounded external-link recheck and rerun the audit with `--check-external-links`.

> - The external-link-integrity row reports a tested count greater than zero.

### `orphan-candidates`

**Label:** Indexable pages with no internal links  
**Classification / Priority:** Issue / High  
**Unit:** pages  
**Evidence tab:** Orphan candidates

**Description**

> {affected_count} of {denominator} indexable pages ({affected_pct}%) received no internal link from any crawled page in run {run_id}. They were found only through the XML sitemap or a supplied URL list. Pages without internal links are crawled less often, receive no internal authority, and are unlikely to rank even when their content is good.
> 
> See the {evidence_tab} tab for each URL and the source that discovered it.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Add crawlable HTML links (real <a href> elements present in the raw HTML) from relevant hubs, category pages, related-item modules or an HTML sitemap. Where a listing shows only a few items and relies on 'load more' or JavaScript pagination, add server-rendered paginated pages. Remove pages from the sitemap if they are not meant to be indexed.

**Acceptance Criteria**

> - A raw-HTML crawl from the homepage reaches at least 95% of the URLs in the {evidence_tab} tab within four clicks.
> - No indexable sitemap URL has zero internal inlinks in the next crawl run.

**How to Replicate**

> {replicate_prefix} The tab lists the discovery source for every candidate; compare with the sitemap to confirm.

**Notes / Documentation**

> {qualification} Zero observed inlinks is evidence from this crawl's graph only; pages linked from areas the crawl could not reach (behind login, blocked by robots) may appear here and should be excluded once confirmed.

### `crawl-depth-distribution`

**Label:** Important pages sit too deep in the site structure  
**Classification / Priority:** Warning / Medium  
**Unit:** pages  
**Evidence tab:** Crawl depth

**Description**

> {affected_count} of {denominator} indexable pages are more than the configured depth from the homepage by shortest click path in run {run_id}. Deep pages are crawled less frequently and inherit less internal authority. When commercial or key landing pages are deep it usually means they are missing from the main navigation.
> 
> See the {evidence_tab} tab for each URL and its shortest depth.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Add the most important deep pages to the header or footer navigation, or to a hub page that is itself linked from the navigation. Introduce an HTML sitemap linked site-wide. Shorten pagination chains with links to first, last and nearby pages.

**Acceptance Criteria**

> - Every commercial or priority page listed in the {evidence_tab} tab is reachable within three clicks of the homepage.
> - The share of indexable pages deeper than the configured depth falls below 10%.

**How to Replicate**

> {replicate_prefix} Depth is the shortest in-scope path from the seed set recorded for the run.

**Notes / Documentation**

> Depth counts only crawlable HTML links. Pages reachable only through JavaScript navigation appear deeper than users experience them, which is itself the point.

### `internal-authority`

**Label:** Priority pages receive little internal link equity  
**Classification / Priority:** Improvement / Medium  
**Unit:** pages  
**Evidence tab:** Internal authority

**Description**

> The internal link graph for run {run_id} concentrates authority on a small set of pages while pages that matter commercially receive few links. The {evidence_tab} tab lists every indexable page with its relative internal authority score and inlink count so the team can compare templates and priority pages.
> 
> Lowest-scored priority pages:
> {sample_urls}

**Suggested Solution**

> Link the priority pages from high-authority pages that already attract external links (see the top of the {evidence_tab} tab). Add contextual links between sibling pages in the same cluster. Reduce site-wide links to low-value pages (policy pages, login, tag archives) that currently absorb equity.

**Acceptance Criteria**

> - Each agreed priority page has at least five contextual internal links from indexable pages.
> - The priority pages move into the top half of the internal authority distribution in the next crawl run.

**How to Replicate**

> {replicate_prefix} Scores are relative within this run and change with every crawl; compare rank, not absolute value.

**Notes / Documentation**

> This is an inventory, not a defect list. Which pages count as priority is a business decision and must be agreed before this ticket is raised.

### `image-markup`

**Label:** Images missing alt text or dimensions  
**Classification / Priority:** Warning / Low  
**Unit:** images  
**Evidence tab:** Image issues

**Description**

> {affected_count} image references in run {run_id} lack useful alt text, explicit width and height, or responsive srcset markup. Missing alt text removes the image from image search and fails accessibility requirements. Missing dimensions cause layout shift while the page loads.
> 
> See the {evidence_tab} tab for each image, its page and the missing attributes.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Add descriptive alt text to content images and empty alt="" to decorative ones. Set width and height attributes (or CSS aspect-ratio) on every image. Serve responsive images with srcset and sizes. Fix the template or component rather than individual pages.

**Acceptance Criteria**

> - Every content image on the sampled pages has non-empty, descriptive alt text.
> - Every image has explicit dimensions or an aspect-ratio rule.
> - The count of images in the {evidence_tab} tab drops by at least 90% in the next crawl.

**How to Replicate**

> {replicate_prefix} Counts are image references, not unique files; one template image appears once per page.

**Notes / Documentation**

> Decorative-image intent needs a human decision; the deterministic check cannot tell a logo from a product photo.

### `image-resource-delivery`

**Label:** Image resources fail or are oversized  
**Classification / Priority:** Warning / Medium  
**Unit:** images  
**Evidence tab:** Image resources

**Description**

> {affected_count} image resources return errors, exceed the size budget, or are served without modern formats or caching. Broken images degrade the page for users; oversized images slow Largest Contentful Paint and waste bandwidth on mobile.
> 
> See the {evidence_tab} tab for each resource, its status, byte size and the pages that reference it.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Fix or remove image references that return 4xx/5xx. Compress and resize oversized images to their displayed dimensions, serve WebP or AVIF with fallbacks, and set long cache lifetimes for immutable image URLs.

**Acceptance Criteria**

> - No referenced image returns a non-200 response.
> - No above-the-fold image exceeds 200 KB on mobile.
> - Image responses carry a Cache-Control max-age of at least 30 days.

**How to Replicate**

> Run the audit with render comparison enabled (`--compare-current-renders`) and open the {evidence_tab} tab; resource statuses and sizes come from the browser trace.

**Notes / Documentation**

> Requires rendered resource evidence; the raw crawl records references only.

### `url-host-and-variants`

**Label:** Inconsistent URL variants (host, protocol, slash, case)  
**Classification / Priority:** Issue / Medium  
**Unit:** URLs  
**Evidence tab:** URL variants

**Description**

> {affected_count} URL variants in run {run_id} resolve inconsistently: http and https, www and non-www, trailing-slash and non-slash, or upper- and lower-case paths return different outcomes, or more than one variant returns 200 for the same content. Each live variant is a duplicate that splits signals and wastes crawl budget.
> 
> See the {evidence_tab} tab for each probed variant and its response.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Choose one canonical form (https, one host, one slash convention, lower-case paths) and 301 every other variant to it in a single hop at the edge or web server. Make internal links use the canonical form directly.

**Acceptance Criteria**

> - Every non-canonical variant in the {evidence_tab} tab returns a single 301 to the canonical URL.
> - The canonical URL returns 200 with a self-referencing canonical tag.
> - Internal links use the canonical form only.

**How to Replicate**

> Run the audit with `--probe-url-variants` and open the {evidence_tab} tab. Confirm with `curl -sI` against each variant.

**Notes / Documentation**

> Variant probes are synthetic requests made on the audit date and are bounded by --variant-max-probes.

### `nonproduction-https`

**Label:** Non-production host is crawlable or HTTPS controls are broken  
**Classification / Priority:** Error / High  
**Unit:** URLs  
**Evidence tab:** Host and HTTPS

**Description**

> {affected_count} URLs on staging, development or other non-production hosts are crawlable and indexable, or production URLs are served over plain HTTP without redirecting to HTTPS. Indexed non-production hosts duplicate the live site and can outrank it; unencrypted pages are flagged as not secure and lose the HTTPS ranking signal.
> 
> See the {evidence_tab} tab for each host, URL and its robots and indexability state.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Put non-production hosts behind HTTP authentication or an IP allowlist (preferred). Until then, serve `X-Robots-Tag: noindex, nofollow` on every response and `Disallow: /` in their robots.txt. Redirect every http:// production URL to https:// with a 301 and enable HSTS.

**Acceptance Criteria**

> - Non-production hosts require authentication or return noindex on every response.
> - A `site:` search for the non-production host returns no results within 30 days.
> - Every http:// production URL returns a single 301 to its https:// equivalent.

**How to Replicate**

> {replicate_prefix} Confirm with `curl -sI https://<staging-host>/` and `curl -sI http://{site}/`.

**Notes / Documentation**

> Remember to remove blocking rules from any environment that is later promoted to production; blocking directives pushed live are a very common incident.

### `robots-controls`

**Label:** robots.txt is unreachable, invalid, or blocks needed content  
**Classification / Priority:** Error / High  
**Unit:** rules  
**Evidence tab:** Robots

**Description**

> The current robots.txt for {site} could not be fetched, does not parse, or contains rules that conflict with what the site needs crawled: {affected_count} problems were found. An unreachable robots.txt makes Google assume everything is allowed (or, on a 5xx, stop crawling); rules that block CSS, JavaScript or indexable sections prevent proper rendering and indexing.
> 
> See the {evidence_tab} tab for the fetched file, its status and each flagged rule.

**Suggested Solution**

> Serve robots.txt with a 200 status and text/plain content type. Remove rules that block indexable pages or rendering resources. Keep one Sitemap: line per sitemap index. Validate the file with Google's robots.txt report in Search Console before deploying.

**Acceptance Criteria**

> - https://{site}/robots.txt returns 200 and parses without errors.
> - No indexable URL from the crawl is disallowed for Googlebot.
> - No CSS or JavaScript path required for rendering is disallowed.
> - The file references the current sitemap index URL.

**How to Replicate**

> Run the audit with `--fetch-current-robots-sitemaps` and open the {evidence_tab} tab. The fetch time is recorded in the tab.

**Notes / Documentation**

> This is current-site evidence taken on the audit date, separate from the historical crawl. Reference: https://developers.google.com/search/docs/crawling-indexing/robots/intro

### `sitemap-integrity`

**Label:** XML sitemaps list dead, non-indexable or non-canonical URLs  
**Classification / Priority:** Issue / Medium  
**Unit:** sitemap URLs  
**Evidence tab:** Sitemaps

**Description**

> The declared sitemaps for {site} contain {affected_count} of {denominator} entries that return non-200 responses, are noindex, canonicalise elsewhere, or sit outside the crawl scope, or the sitemap files themselves fail to fetch or parse. Sitemaps that list dead or excluded URLs waste crawl budget and reduce Google's trust in the file; missing sections (for example locale folders) leave those pages undiscovered.
> 
> See the {evidence_tab} tab for each sitemap file, its status and every flagged entry.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Generate sitemaps only from URLs that return 200, are indexable and self-canonical. Remove retired URLs at source rather than filtering. Emit a real per-URL lastmod that changes only when the page changes. Add sitemaps for any indexable section that is missing. Check generators for hard row caps.

**Acceptance Criteria**

> - Every sitemap file returns 200 and parses as valid XML.
> - Every listed URL returns 200, is indexable and has a self-referencing canonical.
> - lastmod values are not identical across the file and reflect real changes.
> - Every indexable section of the site is covered by a sitemap.

**How to Replicate**

> Run the audit with `--fetch-current-robots-sitemaps` and open the {evidence_tab} tab. Entry statuses are matched against the selected historical run and flagged where they differ.

**Notes / Documentation**

> Sitemap files are fetched live on the audit date; the crawl statuses they are compared with come from run {run_id} on {crawl_date}. Reference: https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap

### `rendered-robots-links`

**Label:** Rendered pages expose links that robots.txt blocks  
**Classification / Priority:** Warning / Medium  
**Unit:** links  
**Evidence tab:** Rendered robots links

**Description**

> {affected_count} links that appear only after JavaScript renders point at URLs that robots.txt disallows or that the crawl could not follow. Googlebot renders the page, finds the links, and is then refused; the linked pages can be indexed with no content, and the links themselves leak equity into a dead end.
> 
> See the {evidence_tab} tab for each source page, the rendered link and the blocking rule.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Either allow the blocked paths (if the pages should be crawled) or stop rendering them as <a href> links and use buttons or plain elements instead. Add noindex on the target pages if they must remain blocked from indexing.

**Acceptance Criteria**

> - No rendered link on the sampled pages points at a disallowed URL.
> - Blocked targets that remain linked are converted to non-anchor controls.

**How to Replicate**

> Run the audit with `--compare-current-renders` and open the {evidence_tab} tab; links are extracted from the rendered DOM and evaluated against the fetched robots.txt.

**Notes / Documentation**

> Requires both rendered evidence and a current robots.txt fetch.

### `indexability-segmentation`

**Label:** Conflicting indexability directives  
**Classification / Priority:** Error / High  
**Unit:** pages  
**Evidence tab:** Index conflicts

**Description**

> {affected_count} of {denominator} pages in run {run_id} send contradictory indexing signals: the HTML meta robots tag and the X-Robots-Tag HTTP header disagree, or a page is noindex while also being linked, listed in the sitemap and declared canonical. Google resolves conflicts by taking the most restrictive directive, so pages the team expects to rank may be silently excluded.
> 
> See the {evidence_tab} tab for each URL with both directives and the indexability outcome.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Decide the intended state for each affected template and set it in exactly one place (HTML meta robots or HTTP header, not both). Remove noindex from pages that should rank; remove noindexed pages from sitemaps and hreflang sets if the noindex is intentional.

**Acceptance Criteria**

> - No crawled page has an HTML meta robots value that differs from its X-Robots-Tag header.
> - Every sitemap URL is indexable.
> - Each affected template renders its intended directive on a live fetch.

**How to Replicate**

> {replicate_prefix} Confirm with `curl -sI <url> | grep -i x-robots` and view-source for the meta tag.

**Notes / Documentation**

> Reference: https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag

### `crawl-waste-url-families`

**Label:** Internal links generate unbounded URL families  
**Classification / Priority:** Issue / Medium  
**Unit:** URLs  
**Evidence tab:** URL families

**Description**

> Internal links in run {run_id} create {affected_count} URLs in a small number of parameter or path families (session IDs, sort and filter combinations, search results, modal states, calendar dates, tracking parameters). These families grow with every user action, return 200, and consume crawl budget that should reach real content.
> 
> See the {evidence_tab} tab for each family, its URL count, link instances and example URLs.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Stop generating the URLs as crawlable links: render state changes, modals, sorts and filters as <button> elements or use the History API without an href. Where a parameter family must stay linkable, canonicalise to the clean URL and, if it is never useful in search, disallow it in robots.txt.

**Acceptance Criteria**

> - Raw HTML of the sampled pages contains no internal hrefs from the listed families.
> - The next crawl run records fewer than 1% of internal links pointing at parameter URLs.

**How to Replicate**

> {replicate_prefix} Families are grouped by parameter name and path pattern; the tab gives the count per family.

**Notes / Documentation**

> Canonical tags reduce duplicate indexing but do not stop the crawl waste; the links themselves have to go.

### `parameter-and-faceted-controls`

**Label:** Internal links publish tracking or faceted parameter URLs  
**Classification / Priority:** Issue / Medium  
**Unit:** links  
**Evidence tab:** Tracking parameters

**Description**

> {affected_count} internal links in run {run_id} point at URLs carrying tracking parameters (utm_*, gclid, fbclid and similar) or facet parameters whose target canonicalises back to a clean URL. Linking to tracked or non-canonical variants sends crawlers to duplicate URLs, can overwrite attribution for real campaigns, and leaves the linked pages unable to rank on their own.
> 
> See the {evidence_tab} tab for each source page, the linked URL and its parameters.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Change internal links to the clean canonical URL. If facet pages (for example provider or category filters) deserve to rank, give them clean paths with self-referencing canonicals and crawlable listings; otherwise render the filters as non-anchor controls.

**Acceptance Criteria**

> - No internal link contains a tracking parameter.
> - Every internally linked facet URL is either self-canonical and indexable or no longer an anchor.

**How to Replicate**

> {replicate_prefix} The tab lists the parameter names per link so template sources can be found quickly.

**Notes / Documentation**

> Whether a facet deserves its own landing page is a content decision; agree the list before changing the links.

### `soft404-error-routes`

**Label:** Error pages return 200 (soft 404s)  
**Classification / Priority:** Error / High  
**Unit:** URLs  
**Evidence tab:** Soft 404s

**Description**

> {affected_count} URLs that show 'not found' or empty-template content returned a 200 status in the audit probes. Search engines have to guess that these are errors, keep crawling them, and may index empty pages. Genuine 404 and 410 responses let Google drop the URLs quickly and stop wasting requests on them.
> 
> See the {evidence_tab} tab for each probed URL, its status, title and content signals.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Return a real 404 (or 410 for permanently removed content) with the same helpful page body. Fix route handlers that render the not-found template with a 200 status. For catalogue items that are out of stock or expired, keep 200 only while the page offers real content and links.

**Acceptance Criteria**

> - Every URL in the {evidence_tab} tab returns 404 or 410 on a live check, or has been given real content.
> - A request for a random non-existent path returns 404, not 200.

**How to Replicate**

> Run the audit with `--probe-url-variants` and open the {evidence_tab} tab. Confirm with `curl -sI https://{site}/this-path-does-not-exist`.

**Notes / Documentation**

> Reference: https://developers.google.com/search/docs/crawling-indexing/http-network-errors#soft-404-errors

### `metadata-basics`

**Label:** Missing, duplicate-in-page or malformed titles and descriptions  
**Classification / Priority:** Warning / Medium  
**Unit:** pages  
**Evidence tab:** Metadata

**Description**

> {affected_count} of {denominator} indexable pages in run {run_id} have a missing, empty, very short, very long, or multiply-declared title or meta description. Titles are the strongest on-page relevance signal and the headline users click; descriptions drive click-through. Google rewrites poor ones, but the rewrite is rarely better than a deliberate one.
> 
> See the {evidence_tab} tab for each URL, the current values and the flagged problem.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Give every indexable template a title pattern of roughly 50 to 60 characters and a unique description of roughly 120 to 155 characters, populated from page data. Ensure exactly one <title> and one meta description per page. Add H1 handling if the same template also lacks headings.

**Acceptance Criteria**

> - Every indexable page has exactly one non-empty title and one non-empty meta description.
> - No title exceeds 70 characters and no description exceeds 170 characters.
> - The {evidence_tab} tab is empty on the next crawl run.

**How to Replicate**

> {replicate_prefix} Values are read from the stored raw HTML, not the rendered page.

**Notes / Documentation**

> Length limits are guidance, not Google rules; the goal is readable, unique metadata per page.

### `metadata-duplicates-aliases`

**Label:** Duplicate titles and descriptions across distinct pages  
**Classification / Priority:** Warning / Medium  
**Unit:** pages  
**Evidence tab:** Duplicate metadata

**Description**

> After grouping canonical aliases together, {affected_count} of {denominator} indexable pages in run {run_id} still share a title or meta description with another distinct page. Duplicate metadata usually means a template ignores page-specific data, and it makes it hard for search engines to pick the right page for a query.
> 
> See the {evidence_tab} tab for each duplicate group, its member URLs and the shared value. Raw counts before alias grouping are retained in the tab.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Populate titles and descriptions from unique page attributes (name, category, location, model). Where two pages genuinely serve the same purpose, consolidate them with a redirect or canonical rather than rewriting the metadata.

**Acceptance Criteria**

> - No two indexable, canonical pages share the same title.
> - No two indexable, canonical pages share the same meta description.
> - Remaining duplicates are pages that have been consolidated with a canonical or redirect.

**How to Replicate**

> {replicate_prefix} The tab shows both the raw duplicate count and the count after canonical grouping.

**Notes / Documentation**

> Pagination and locale variants are grouped by canonical before counting, so remaining duplicates are real.

### `content-quality`

**Label:** Thin or empty indexable pages  
**Classification / Priority:** Warning / Medium  
**Unit:** pages  
**Evidence tab:** Content quality

**Description**

> {affected_count} of {denominator} indexable pages in run {run_id} contain fewer than the declared minimum words of main content after boilerplate removal, or extracted no content at all. Thin pages dilute site quality signals, rarely rank, and in volume can affect how the whole site is assessed.
> 
> See the {evidence_tab} tab for each URL, its extracted word count and the reason it was flagged.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Add substantive content to pages that deserve to rank, consolidate near-empty pages into their parent, and noindex or remove pages that exist only for navigation or state. Where extraction returned nothing on a page that is visibly full, the content is probably injected by JavaScript and should be server-rendered.

**Acceptance Criteria**

> - Every indexable page has at least the agreed minimum of main-content words, or is noindexed, or has been consolidated.
> - Pages whose content is rendered client-side serve it in the raw HTML.

**How to Replicate**

> {replicate_prefix} Word counts come from the stored extracted text with the extractor version recorded in the run.

**Notes / Documentation**

> The word threshold is declared in the run options; it is a screening threshold, not a ranking rule.

### `locale-html-lang`

**Label:** Missing or wrong HTML lang attribute  
**Classification / Priority:** Warning / Low  
**Unit:** pages  
**Evidence tab:** Locale language

**Description**

> {affected_count} of {denominator} pages in run {run_id} have no <html lang> attribute, an invalid value, or a value that does not match the locale in the URL (for example /fr/ pages declaring lang="en"). Browsers, assistive technology and some search features use this attribute to pick the right language handling; a mismatch also hints that locale pages are untranslated copies.
> 
> See the {evidence_tab} tab for each URL, its declared lang and the expected locale.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Set <html lang> from the page's locale using a valid BCP 47 tag (en, en-GB, fr, pt-BR). Where locale pages still show English content, either translate them or stop publishing them until they are translated.

**Acceptance Criteria**

> - Every page declares a valid lang attribute.
> - The declared lang matches the URL locale convention on every locale page.

**How to Replicate**

> {replicate_prefix} The expected locale is derived from the run's declared URL locale rule.

**Notes / Documentation**

> Untranslated locale pages are usually also flagged under duplicate metadata and hreflang; treat them as one problem.

### `near-duplicate-content`

**Label:** Near-duplicate pages  
**Classification / Priority:** Warning / Medium  
**Unit:** pages  
**Evidence tab:** Near duplicates

**Description**

> {affected_count} of {tested_count} compared indexable pages in run {run_id} are near-identical to at least one other page after boilerplate removal and text normalisation. Near duplicates compete with each other, split links and engagement, and lead Google to choose a canonical the team did not intend.
> 
> See the {evidence_tab} tab for each pair, its similarity score and the shared template.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> For each duplicate group choose one URL to keep: redirect or canonicalise the others to it. Where pages must remain separate (locales, variants), differentiate their main content or noindex the weaker ones. Fix the template if boilerplate dominates the page.

**Acceptance Criteria**

> - Every pair in the {evidence_tab} tab is resolved by a redirect, a canonical, a noindex, or materially different content.
> - The next run reports no near-duplicate pairs among indexable canonical pages above the declared threshold.

**How to Replicate**

> {replicate_prefix} Comparison uses the simhash threshold and page limit recorded in the run options; both are shown in the tab header.

**Notes / Documentation**

> {qualification} Similarity is evidence for review; confirm the pair visually before assigning work.

### `canonical-declarations`

**Label:** Missing, multiple or malformed canonical tags  
**Classification / Priority:** Error / High  
**Unit:** pages  
**Evidence tab:** Canonicals

**Description**

> {affected_count} of {denominator} indexable pages in run {run_id} declare no canonical, more than one canonical, a relative or malformed canonical URL, or a canonical that points at a different protocol or host without reason. Invalid canonicals are ignored by Google, and conflicting ones let it pick any URL it likes as the version to index.
> 
> See the {evidence_tab} tab for each URL and its declared canonical values.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Emit exactly one absolute, self-referencing canonical on every indexable page, matching the final URL after redirects. Remove canonical tags injected by plugins or components that duplicate the template's own tag.

**Acceptance Criteria**

> - Every indexable page has exactly one canonical link element with an absolute https URL.
> - The canonical matches the page's own URL unless consolidation is intended and documented.

**How to Replicate**

> {replicate_prefix} Values are read from the raw HTML head; HTTP Link headers are listed separately.

**Notes / Documentation**

> Reference: https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls

### `canonical-target-validation`

**Label:** Canonical targets that are broken, noindex or chained  
**Classification / Priority:** Error / High  
**Unit:** pages  
**Evidence tab:** Canonical targets

**Description**

> {affected_count} pages in run {run_id} declare a canonical whose target returns a non-200 status, is itself noindex, redirects, canonicalises onward to a third URL, or forms a loop. A canonical that points at an unusable page is ignored, and both pages may drop out of the index.
> 
> See the {evidence_tab} tab for each source URL, its canonical target and the target's status and directives.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Point each canonical at a URL that returns 200, is indexable and is self-canonical. Remove canonical chains by pointing every member directly at the final URL. Replace canonicals to redirecting URLs with the redirect destination.

**Acceptance Criteria**

> - Every canonical target returns 200 and is indexable.
> - Every canonical target is self-referencing (no chains, no loops).

**How to Replicate**

> {replicate_prefix} Target status is taken from the same run; uncrawled targets are marked as unknown rather than failing.

**Notes / Documentation**

> {recheck_note}

### `hreflang-html-http`

**Label:** Broken or non-reciprocal hreflang annotations  
**Classification / Priority:** Issue / Medium  
**Unit:** clusters  
**Evidence tab:** Hreflang

**Description**

> {affected_count} hreflang clusters in run {run_id} have invalid language or region codes, missing self-references, alternates that do not link back, or alternate URLs that return non-200 or are not crawlable. Google ignores annotations that are not reciprocal, so the wrong locale version can be shown to users and locale pages compete with each other.
> 
> See the {evidence_tab} tab for each source URL, each alternate, and the reason it fails.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Generate hreflang from a single locale map so that every page in a cluster lists every member including itself, using valid ISO 639-1 language and ISO 3166-1 region codes. Include an x-default. Remove alternates for locales that do not exist or return errors.

**Acceptance Criteria**

> - Every hreflang alternate returns 200 and lists the source URL back.
> - Every cluster member includes a self-referencing entry.
> - All codes are valid and lower-case language, upper-case region.

**How to Replicate**

> {replicate_prefix} HTML and HTTP-header annotations are shown as separate channels in the tab.

**Notes / Documentation**

> Reference: https://developers.google.com/search/docs/specialty/international/localized-versions

### `hreflang-sitemap`

**Label:** Sitemap hreflang annotations disagree with page annotations  
**Classification / Priority:** Issue / Medium  
**Unit:** sitemap entries  
**Evidence tab:** Sitemap hreflang

**Description**

> {affected_count} sitemap hreflang entries in the declared sitemaps conflict with the HTML annotations, point at URLs that fail, or are missing for pages that declare alternates in HTML. Google treats the sitemap channel independently; conflicting channels cancel each other out.
> 
> See the {evidence_tab} tab for each sitemap entry and the matching HTML annotation.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Generate sitemap xhtml:link alternates from the same locale map as the HTML annotations, or use only one channel consistently. Remove alternates for URLs that do not return 200.

**Acceptance Criteria**

> - Sitemap and HTML hreflang sets are identical for every sampled cluster.
> - Every sitemap alternate URL returns 200.

**How to Replicate**

> Run the audit with `--fetch-current-robots-sitemaps` and open the {evidence_tab} tab.

**Notes / Documentation**

> This channel is unavailable on runs stored before sitemap hreflang retention was added (ticket 164).

### `hreflang-noindex`

**Label:** Hreflang alternates that are noindex, blocked or redirected  
**Classification / Priority:** Issue / Medium  
**Unit:** pages  
**Evidence tab:** Hreflang noindex

**Description**

> {affected_count} hreflang alternates in run {run_id} point at pages that are noindex, disallowed by robots.txt, canonicalised elsewhere or redirected. An alternate that cannot be indexed invalidates the cluster, so the remaining locale pages lose their annotations too.
> 
> See the {evidence_tab} tab for each alternate and the directive that invalidates it.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Remove noindex, blocked or redirected URLs from hreflang sets, or make those pages indexable if they should be. Keep hreflang only between indexable, self-canonical pages.

**Acceptance Criteria**

> - No hreflang alternate is noindex, blocked or non-self-canonical.
> - Every cluster member is indexable on a live recheck.

**How to Replicate**

> {replicate_prefix} Directive data comes from the stored response headers and HTML of the same run.

**Notes / Documentation**

> Often caused by a blanket noindex on a section (for example a blog) that still emits alternates from the template.

### `locale-redirects`

**Label:** Geo or locale redirects trap users or search bots  
**Classification / Priority:** Issue / High  
**Unit:** probes  
**Evidence tab:** Locale redirects

**Description**

> {affected_count} of {tested_count} locale probes redirected based on request region or Accept-Language in a way that prevents reaching the requested locale, redirects Googlebot away from locale pages, or lands on an error. Because Googlebot crawls mostly from the US, forced geo redirects can hide every other locale from the index.
> 
> See the {evidence_tab} tab for each probe: region, headers sent, redirect path and final URL.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Do not redirect on IP or Accept-Language for crawlable URLs. Serve the requested locale and offer a non-blocking banner or switcher to the suggested one. If a redirect must exist, apply it only on the homepage, exempt verified search bots, and keep every locale URL directly reachable.

**Acceptance Criteria**

> - A request for any locale URL from any tested region returns that locale with a 200.
> - Googlebot user agents are never redirected between locales.
> - No locale probe ends on a 4xx or 5xx.

**How to Replicate**

> Run the audit with the configured geo proxies and open the {evidence_tab} tab; each probe records region, proxy and fetch time.

**Notes / Documentation**

> Requires the geo proxy matrix; a local request is never substituted for a regional one.

**When unavailable:** Provide regional access for locale redirect testing (Improvement / Low)

> Locale and geo redirect behaviour was not tested because no regional proxy matrix was configured for the audit.

> Suggested solution: Approve the regions to test and configure the proxy matrix, then rerun the audit.

> - The locale-redirects row reports a tested probe count for every agreed region.

### `schema-parser-diagnostics`

**Label:** Structured data that fails to parse  
**Classification / Priority:** Error / Medium  
**Unit:** blocks  
**Evidence tab:** Schema diagnostics

**Description**

> {affected_count} JSON-LD, Microdata or RDFa blocks in run {run_id} fail to parse or have structural defects (invalid JSON, wrong @context, nested types without @type, empty required containers). Invalid markup is ignored entirely, so the page loses any rich result it was eligible for.
> 
> See the {evidence_tab} tab for each URL, the block, the diagnostic code and the suggested fix.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Fix the generating template so the block is valid JSON-LD with a single @context and a @type on every node. Remove blocks that are injected by third-party scripts and duplicate the page's own markup. Validate with the Rich Results Test after deploying.

**Acceptance Criteria**

> - Every structured-data block on the sampled pages parses without error.
> - The Rich Results Test reports no parsing errors for one URL per affected template.

**How to Replicate**

> {replicate_prefix} The diagnostic code in each row maps to a specific parser rule.

**Notes / Documentation**

> Reference: https://search.google.com/test/rich-results

### `structured-data-feature-rules`

**Label:** Structured data missing required properties for rich results  
**Classification / Priority:** Warning / Medium  
**Unit:** items  
**Evidence tab:** Structured data

**Description**

> {affected_count} structured-data items in run {run_id} use a type that Google supports for rich results but omit required properties, use placeholder values, or contain ItemList or BreadcrumbList entries that are out of order or point at broken URLs. These items are valid markup but not eligible for the feature the team presumably wants.
> 
> See the {evidence_tab} tab for each URL, the schema type, and the missing or invalid properties.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Populate every required property from real page data and add the recommended ones where available. Order breadcrumb and list items by position with correct item URLs. Remove markup for content that is not visible on the page.

**Acceptance Criteria**

> - Every item of an affected type has all required properties for its feature.
> - BreadcrumbList items are sequential from 1 and each item URL returns 200.
> - The Rich Results Test reports the item as eligible for one URL per affected template.

**How to Replicate**

> {replicate_prefix} Rules are applied per type from the documented rule set version shown in the tab.

**Notes / Documentation**

> Static property checks are not final eligibility; content policy and visibility rules still apply. Reference: https://developers.google.com/search/docs/appearance/structured-data/search-gallery

### `rendered-indexing-parity`

**Label:** Rendered page differs from raw HTML in indexing signals  
**Classification / Priority:** Issue / High  
**Unit:** pages  
**Evidence tab:** Rendered parity

**Description**

> {affected_count} of {tested_count} paired page samples show material differences between the raw HTML and the rendered DOM in canonical, robots directives, title, main content, internal links or structured data. Google indexes from the rendered version but discovers and prioritises from raw HTML; when they disagree, links are missed and directives may flip after rendering.
> 
> See the {evidence_tab} tab for each URL and every signal that differs.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Server-render (or statically generate) the indexing signals and primary content so the raw HTML already contains the final canonical, directives, metadata, links and schema. Do not change canonical or robots values with client-side JavaScript.

**Acceptance Criteria**

> - Raw and rendered canonical, robots and title values match on every sampled page.
> - At least 95% of rendered internal links are present in the raw HTML.
> - Primary content and structured data are present in the raw HTML.

**How to Replicate**

> Run the audit with `--compare-current-renders` and open the {evidence_tab} tab; each row records the browser configuration and fetch time.

**Notes / Documentation**

> Rendered evidence is current-site data taken on the audit date. A challenge or interstitial page is recorded as a blocked sample, not as a parity failure.

### `mobile-rendering-parity`

**Label:** Mobile rendering hides content or links present on desktop  
**Classification / Priority:** Issue / Medium  
**Unit:** pages  
**Evidence tab:** Mobile rendering

**Description**

> {affected_count} of {tested_count} paired samples render less content, fewer internal links, different directives or a different canonical in a mobile viewport than in the desktop baseline. Google indexes with a mobile user agent, so anything missing on mobile is missing from the index.
> 
> See the {evidence_tab} tab for each URL and the signals that differ between viewports.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Serve the same content, links and indexing signals in both viewports. Collapse rather than remove content on mobile (accordions and tabs are fine; conditional omission is not).

**Acceptance Criteria**

> - Mobile and desktop renders expose the same canonical, directives, title and structured data on every sampled page.
> - Mobile internal link count is at least 95% of desktop on every sampled page.

**How to Replicate**

> Run the audit with `--compare-current-renders --render-mobile-viewport` and open the {evidence_tab} tab.

**Notes / Documentation**

> Requires explicit mobile render evidence; desktop-only renders leave this row unavailable.

### `critical-resource-impact`

**Label:** Blocked or failing resources break rendering  
**Classification / Priority:** Issue / High  
**Unit:** resources  
**Evidence tab:** Critical resources

**Description**

> {affected_count} CSS, JavaScript, font, API or third-party resources needed to render the sampled pages are blocked by robots.txt, fail with 4xx/5xx, time out, or are challenged. When Googlebot cannot load them the rendered page loses content, links or layout, and may be indexed as an empty shell.
> 
> See the {evidence_tab} tab for each resource, the pages that need it, and its outcome.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Allow crawler access to every resource used for rendering. Fix failing resource URLs and remove references to retired ones. Move critical CSS and data calls off third-party hosts that challenge or rate-limit bots.

**Acceptance Criteria**

> - No resource on the sampled pages is disallowed by robots.txt.
> - No render-critical resource returns a non-200 response.
> - The rendered page's main content and links are present with all resources loaded.

**How to Replicate**

> Run the audit with `--compare-current-renders` and open the {evidence_tab} tab; resource outcomes come from the browser trace.

**Notes / Documentation**

> Confirm with the URL Inspection tool's 'Tested page' resources list in Search Console.

### `nonhtml-search-assets`

**Label:** PDFs, feeds or media assets are not discoverable or correctly served  
**Classification / Priority:** Warning / Low  
**Unit:** assets  
**Evidence tab:** Non-HTML assets

**Description**

> {affected_count} non-HTML assets that should appear in search (PDFs, video and image files, RSS or Atom feeds) are unlinked, blocked, served with the wrong content type, or return errors. Assets that are invisible to crawlers cannot appear in search or in image and video features.
> 
> See the {evidence_tab} tab for each asset, its type, status and discovery source.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Link important assets from indexable pages, include them in a sitemap of the matching type, serve the correct Content-Type, and make sure robots.txt does not block them. Remove or noindex assets that should not be indexed.

**Acceptance Criteria**

> - Every listed asset returns 200 with the correct Content-Type.
> - Every asset meant for search is linked from an indexable page or listed in a sitemap.

**How to Replicate**

> {replicate_prefix} Assets come from the supplied inventory or from references collected during the crawl.

**Notes / Documentation**

> Requires a supplied or collected asset inventory; the HTML-only crawl does not fetch asset bodies.

### `performance-distribution`

**Label:** Slow responses concentrated in specific templates  
**Classification / Priority:** Warning / Medium  
**Unit:** URLs  
**Evidence tab:** Performance

**Description**

> Across {tested_count} sampled URLs, the slowest responses cluster in identifiable templates: {affected_count} URLs exceed the agreed response-time threshold. Slow server responses reduce how many pages Googlebot fetches per visit and lower the crawl rate; on user devices they show up as poor Time to First Byte and Largest Contentful Paint.
> 
> See the {evidence_tab} tab for per-URL timings, percentiles by template and the worst outliers.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Profile the worst templates for slow database queries or uncached API calls, add server or edge caching for anonymous requests, and reduce page weight on the heaviest pages. Re-measure with the same method after each change.

**Acceptance Criteria**

> - The 95th-percentile response time for each affected template is under the agreed threshold on a repeat measurement.
> - No sampled URL exceeds twice the threshold.

**How to Replicate**

> {replicate_prefix} Timings are crawler measurements from run {run_id}; the tab records the timing mode and sample size.

**Notes / Documentation**

> Crawler timings are lab evidence, not field Core Web Vitals. Use CrUX or Search Console for user-experienced values.

### `conditional-cache-behaviour`

**Label:** Conditional requests are not honoured (no 304 responses)  
**Classification / Priority:** Improvement / Low  
**Unit:** URLs  
**Evidence tab:** Conditional requests

**Description**

> {affected_count} of {tested_count} sampled URLs either send no ETag or Last-Modified validator, or return a full 200 body to a conditional request whose validator still matches. Honouring conditional requests lets Googlebot confirm a page is unchanged cheaply, which frees crawl budget for pages that did change.
> 
> See the {evidence_tab} tab for each URL, the validators sent, and the conditional response.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Emit a stable ETag or Last-Modified on HTML responses and return 304 Not Modified when If-None-Match or If-Modified-Since matches. Make sure the CDN passes validators through and does not regenerate them per request.

**Acceptance Criteria**

> - Every sampled HTML URL returns a validator header.
> - A conditional request with a matching validator returns 304 with no body.

**How to Replicate**

> Run the audit with `--probe-conditional-gets` and open the {evidence_tab} tab; each row holds the initial and conditional request pair.

**Notes / Documentation**

> A missing validator and a broken validator are recorded separately in the tab.

### `validated-bot-log-analysis`

**Label:** Search-bot crawl activity is wasted on errors and low-value URLs  
**Classification / Priority:** Issue / Medium  
**Unit:** requests  
**Evidence tab:** Bot logs

**Description**

> Verified search-bot requests in the supplied logs show {affected_count} of {tested_count} hits going to error responses, redirects, parameter families or non-indexable URLs. Crawl spent on those URLs is crawl not spent on pages that should rank.
> 
> See the {evidence_tab} tab for hits by status, URL family and bot, with the verification method used.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Fix the error and redirect targets first (they overlap with the link and redirect tickets), then remove or block the URL families that attract crawl without value. Re-check the log share after 30 days.

**Acceptance Criteria**

> - Fewer than 5% of verified bot hits return 4xx or 5xx.
> - Fewer than 10% of verified bot hits go to non-indexable or parameter URLs.

**How to Replicate**

> Supply the access logs to the audit and open the {evidence_tab} tab; only requests whose source IP passed reverse and forward DNS verification are counted.

**Notes / Documentation**

> User-agent strings alone are never accepted as bot identity.

**When unavailable:** Supply verified search-bot access logs (Improvement / Low)

> Bot-log analysis was not performed because no server or CDN access logs were supplied. Crawl-budget conclusions from the crawl alone are indirect.

> Suggested solution: Export at least 30 days of raw access logs (or CDN logs) including source IP, user agent, URL and status, and provide them with the next audit request.

> - The validated-bot-log-analysis row reports a verified request count greater than zero.

### `supplied-search-evidence`

**Label:** Search Console reports issues the crawl cannot see  
**Classification / Priority:** Issue / Medium  
**Unit:** records  
**Evidence tab:** Supplied search evidence

**Description**

> The supplied Search Console, URL Inspection or analytics exports add {affected_count} records that change or extend the crawl conclusions: URLs Google reports as excluded, crawled-not-indexed, or with server errors that were not visible in the crawl. These reflect Google's own view of the site and take precedence over inferred crawl findings.
> 
> See the {evidence_tab} tab for each record, its source, date range and how it maps to a contract check.
> 
> Examples:
> {sample_urls}

**Suggested Solution**

> Work through the records by Google's reason category, linking each to its matching ticket in this register. Use URL Inspection to confirm fixes and request indexing for high-value URLs once corrected.

**Acceptance Criteria**

> - Every record in the {evidence_tab} tab is linked to a ticket or documented as accepted.
> - The relevant Search Console report shows the excluded count falling on the next export.

**How to Replicate**

> Supply the exports to the audit; the tab records the source and export date for each record.

**Notes / Documentation**

> Supplied evidence is dated; note the export date next to any conclusion drawn from it.

**When unavailable:** Grant Search Console access or supply exports (Improvement / Low)

> No Search Console, URL Inspection or analytics data was supplied, so Google's own indexing view could not be compared with the crawl.

> Suggested solution: Grant read access to the Search Console property, or export the Pages (indexing) and Crawl stats reports for the last 90 days.

> - The supplied-search-evidence row reports a record count and export date.

### `recipient-action-eligibility`

Overview only, never a ticket.

> Counts how many tickets in this register have an owner, evidence, impact and next action. Findings that fail this gate stay in the evidence workbook and are not written to the Tickets tab.

### `healthy-overview`

Overview only, never a ticket.

> Lists the controls that passed with their tested population and run ID. Only pass and not-applicable rows appear here; unavailable rows are listed separately as not tested.

### `artifact-validation`

Overview only, never a ticket.

> Confirms the JSON, Markdown and workbook agree on IDs, counts and states for run {run_id}. Internal quality gate; never a client ticket.

