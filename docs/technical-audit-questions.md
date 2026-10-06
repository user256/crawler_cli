# Technical audit questions

Generated from [`templates/technical-audit-questions.json`](../templates/technical-audit-questions.json); edit the JSON, not this file. Every question is phrased so that **Yes means a problem**; `Issue if` is the rule that makes the answer Yes.

## Statuses

- **Issue**: The issue_if rule matched on a complete population.
- **Healthy**: The rule was tested on a complete population and did not match (or the control does not apply, with the reason given).
- **Needs validation**: The rule matched or was tested on partial coverage, a heuristic group, or a run that failed Q26.
- **Pending**: Not tested: a required input, profile key or external tool was missing.

## Groups

| Group | Answerable | Ticket policy | Questions |
|---|---|---|---|
| crawl | Yes | on Issue, at the entry's classification | Q1, Q3, Q4, Q13, Q14, Q82, Q93, Q8, Q9, Q10, Q11, Q12, Q15, Q16, Q41, Q53, Q71, Q73, Q80, Q84, Q85, Q87, Q94, Q70, Q88, Q89, Q2, Q5, Q6, Q7, Q22, Q25, Q28, Q39, Q42, Q72, Q74, Q76, Q79, Q91, Q92, Q63 |
| crawl+profile | Yes, with site profile | on Issue; Pending when a profile key is missing | Q97, Q23, Q40, Q44, Q46, Q48, Q49, Q75, Q98, Q100, Q20, Q21, Q36, Q37, Q57, Q59, Q62, Q78, Q24, Q34, Q101, Q27, Q43, Q77, Q102, Q103, Q96 |
| best-practice | Yes | on Issue, classification capped at Improvement or Warning, priority at most Medium | Q45, Q17, Q47, Q51, Q54, Q55, Q56, Q58, Q60, Q83, Q64, Q65, Q66, Q67, Q86 |
| heuristic | Partly | never automatic; status is at most Needs validation until a person confirms | Q38, Q95, Q99, Q32, Q52, Q61, Q35, Q33, Q29, Q68, Q69 |
| supplied-input | With supplied data | on Issue when the input is supplied; otherwise Pending | Q90, Q30, Q19 |
| external | No | never; always Pending with the tool needed | Q18, Q31, Q50, Q104 |
| run-gate | Yes | never; a failure downgrades every other crawl answer to Needs validation | Q26, Q81 |

## Crawlability

### Q1 · Robots.txt

**Does robots.txt block any URL the site needs crawled: an indexable page, a sitemap URL, an internally linked page, or a script, stylesheet or API resource that a page needs to render its copy?**

- Issue if: At least one sitemap URL, internally linked HTML URL or render-critical resource has allowed_by_robots = false.
- Why it matters: Google cannot crawl a blocked URL, so it cannot read or rank its content; a blocked page can still be indexed from links as a bare URL with no snippet. When a script or API that builds the page copy is blocked, Google renders the page without that copy.
- Group: crawl · Ticket: Error / High · Unit: URLs
- Needs: crawl, robots, sitemaps, render
- Evidence owners: `robots-controls`, `critical-resource-impact`
- Note: Resource-level blocking needs a rendered crawl (--js); without it only HTML URLs are tested.
- Original: Are any important paths blocked by robots.txt, including paths needed to build or populate page copy?

### Q97 · Robots.txt

**Does any discovered URL fail its approved crawl, noindex or authentication policy?**

- Issue if: A URL designated for crawl blocking is allowed by robots.txt; a public URL designated for noindex lacks the directive or is Disallowed; or a protected path exposes its content without authentication.
- Why it matters: Uncontrolled search, account, preview and other low-value URL paths can waste crawl capacity and expose pages not intended for discovery. robots.txt alone does not prevent a linked URL appearing in search.
- Group: crawl+profile · Ticket: Warning / Medium · Unit: URLs
- Needs: crawl, robots, probes, site-profile
- Evidence owners: `robots-controls`, `indexability-segmentation`, new detector `unwanted-path-policy`
- Note: Planned: no dedicated answerer yet. Requires an approved per-path policy, with distinct crawl-block, public-noindex and authentication routes. A saved crawl cannot establish undiscovered paths or live authentication; missing inputs remain Pending.
- Original: Are there any paths we should be blocking via robots.txt such as /search /admin or other paths found in the crawl we wouldn't want indexed?

### Q3 · Sitemaps

**Does any XML sitemap list a URL that does not return 200, is noindex, or canonicalises to a different URL?**

- Issue if: At least one sitemap URL has status != 200, a noindex directive, or a canonical that is not itself.
- Why it matters: A sitemap should list only the canonical, indexable version of each page. Redirects, errors, noindex and non-canonical entries waste crawl requests, send conflicting canonical signals and make Search Console's sitemap coverage report meaningless.
- Group: crawl · Ticket: Issue / High · Unit: URLs
- Needs: crawl, sitemaps
- Evidence owners: `sitemap-integrity`, `canonical-target-validation`
- Original: Are all sitemap URLs 200, indexable and self-canonical?

### Q4 · Sitemaps

**Is any indexable, self-canonical page that returns 200 in the crawl missing from every XML sitemap?**

- Issue if: At least one crawled 200, indexable, self-canonical HTML URL is absent from all discovered sitemaps.
- Why it matters: The sitemap is Google's list of pages the site wants indexed. Pages left out are found only through links, so they are discovered and recrawled more slowly, which matters most for new and deep pages.
- Group: crawl · Ticket: Warning / Medium · Unit: pages
- Needs: crawl, sitemaps
- Evidence owners: `sitemap-integrity`, `discovery-source-provenance`
- Original: Are there indexable pages missing from the sitemaps?

### Q13 · Internal linking

**Does any indexable sitemap URL receive no internal link from any crawled page?**

- Issue if: At least one indexable sitemap URL has zero run-scoped internal inlinks.
- Why it matters: Pages with no internal links receive no internal authority and are crawled less often. Google treats them as unimportant, so they rarely rank even when the content is good.
- Group: crawl · Ticket: Issue / High · Unit: pages
- Needs: crawl, sitemaps
- Runner: answered today (orphan-candidates rows)
- Evidence owners: `orphan-candidates`
- Note: Pages linked only from areas the crawl could not reach (login, robots-blocked) can appear here.
- Original: Are there orphaned pages, in the sitemaps but without internal links?

### Q14 · Internal linking

**Does any page carry more unique internal outlinks than the threshold?**

- Issue if: At least one HTML page has more than 300 unique internal outlinks.
- Why it matters: Every extra link on a page divides the value passed to each target. Very high counts usually mean an oversized mega-menu or an unbounded link module, which flattens internal priority so key pages get no more weight than trivial ones.
- Group: crawl · Ticket: Warning / Low · Unit: pages
- Needs: crawl
- Runner: answered today (internal-authority unique_outlinks above threshold)
- Evidence owners: `internal-authority`, new detector `link-count-outliers`
- Note: High inlink counts are not a defect in themselves (the homepage and navigation targets always have them), so only outlinks are tested.
- Original: Do any pages have an excessive number of outlinks or inlinks?

### Q18 · Crawl access

**Does Google's own smartphone renderer, from a Google IP, fail to render the primary content of key templates?**

- Issue if: URL Inspection or the Rich Results Test shows missing primary content, blocked resources or a render error for a key template.
- Why it matters: If Google's renderer is blocked, geo-gated or times out, the indexed version of the page lacks its content, and nothing else in the audit will show it.
- Group: external · Ticket: Error / High · Unit: templates
- Needs: external-api
- Evidence owners: `mobile-rendering-parity`
- Note: A US mobile Playwright render (mobile-rendering-parity) is supporting evidence only; confirmation needs URL Inspection.
- Original: Does Googlebot (US, smartphone) actually render the page?

### Q23 · Internal linking

**Are any inventory items (for example games) reachable only after clicking, scrolling or filtering, and absent from both the raw HTML and the initial render?**

- Issue if: At least one inventory URL from the profile pattern appears only in the post-interaction link set.
- Why it matters: Google does not click, scroll or submit forms. Items that appear only after 'load more', a filter or infinite scroll are never discovered through links, and have to rely on the sitemap alone.
- Group: crawl+profile · Ticket: Error / High · Unit: URLs
- Needs: crawl, render, interaction, site-profile
- Runner: answered today (supplied pre/post-interaction inventory capture)
- Evidence owners: `rendered-robots-links`
- Site profile keys: `templates.inventory`
- Original: Can Google discover the game inventory without interacting with the page?

### Q31 · Crawl access

**Does the site serve Google's crawler materially different content from what it serves visitors?**

- Issue if: Content, links or directives fetched as verified Google differ materially from a visitor fetch of the same URL.
- Why it matters: Showing search engines different content from users breaks Google's spam policies and can lead to a manual action that removes pages from search.
- Group: external · Ticket: Error / High · Unit: URLs
- Needs: external-api
- Evidence owners: outside crawler_cli
- Note: crawler_cli can compare a Googlebot user agent with a browser user agent from the same IP, which catches user-agent cloaking only; IP-based cloaking needs a fetch from Google's own IPs (URL Inspection).
- Original: Is the site showing search engines something different from visitors (cloaking)?

### Q38 · Crawl access & JS

**Do filter or category controls on listing templates change the listing without an <a href> to a distinct URL?**

- Issue if: A filter or category control on a listing template is a button or scripted element with no crawlable href.
- Why it matters: Category and useful filter states that exist only as JavaScript state have no URL, so they cannot be crawled, indexed or linked to. Search demand for those subsets goes to competitors.
- Group: heuristic · Ticket: Warning / Medium · Unit: templates
- Needs: crawl, render, site-profile
- Evidence owners: `parameter-and-faceted-controls`, `rendered-robots-links`, new detector `js-only-navigation-controls`
- Site profile keys: `templates.listing`
- Note: Only filters with search demand need crawlable URLs; turning every facet into a link creates crawl waste (see Q24).
- Original: Are interactive faceted filters and category selectors implemented as static <a href> links with distinct URLs rather than client-side SPA state changes?

### Q40 · Information architecture

**Does the primary navigation in the raw HTML lack a direct <a href> to any commercial hub listed in the site profile?**

- Issue if: At least one profile commercial hub has no <a href> inside the header or <nav> of the raw HTML of the homepage and main templates.
- Why it matters: Navigation links appear on every page, so they pass the most internal authority and tell Google which pages matter most. A hub missing from the raw-HTML navigation depends on JavaScript or deep links to be found and ranked.
- Group: crawl+profile · Ticket: Issue / High · Unit: hubs
- Needs: crawl, stored-html, site-profile
- Evidence owners: new detector `nav-hub-links`
- Site profile keys: `commercial_hubs`
- Original: Does the primary navigation (e.g. meganav, header hierarchy) provide direct, crawlable <a href> links to top commercial hubs and priority categories?

### Q44 · Crawl depth & discoverability

**Is any priority landing page more than three clicks from the homepage?**

- Issue if: At least one URL matching the profile's priority templates or hub list has crawl depth > 3.
- Why it matters: The further a page sits from the homepage, the less often it is crawled and the less internal authority it gets. A sitewide HTML sitemap or directory is one fix; the defect is the depth, not the missing sitemap.
- Group: crawl+profile · Ticket: Warning / Medium · Unit: pages
- Needs: crawl, site-profile
- Evidence owners: `crawl-depth-distribution`
- Site profile keys: `commercial_hubs`, `templates.priority`
- Original: Is there an HTML sitemap or curated directory linked sitewide to reduce click depth for critical commercial and review landing pages?

### Q45 · International & internal linking

**Do localized pages with hreflang alternates fail to link to their language siblings with a crawlable link?**

- Issue if: At least 20% of pages with hreflang alternates have no <a href> to any of their alternates.
- Why it matters: Hreflang tags are not links. A crawlable language switcher lets users and crawlers move between editions and helps new locale pages get discovered.
- Group: best-practice · Ticket: Improvement / Low · Unit: pages
- Needs: crawl, stored-html
- Evidence owners: `hreflang-html-http`, new detector `locale-sibling-links`
- Original: Are localized articles and language siblings cross-linked contextually to strengthen semantic clustering across regional editions?

### Q46 · DOM completeness & rendering

**On article templates, are footer navigation links missing from the raw HTML and present only after rendering or scrolling?**

- Issue if: At least one article-template page has footer links in the rendered DOM that are absent from its raw HTML.
- Why it matters: Links added only after rendering or scrolling are invisible to raw-HTML crawlers and may never be seen by Google's renderer, so the sitewide footer stops passing authority from article pages.
- Group: crawl+profile · Ticket: Issue / Medium · Unit: templates
- Needs: crawl, render, stored-html, site-profile
- Evidence owners: `rendered-indexing-parity`, new detector `footer-link-parity`
- Site profile keys: `templates.article`
- Original: Are primary footer navigation and commercial links rendered in the static HTML of article templates rather than suppressed or deferred by infinite scroll?

### Q48 · Information architecture

**Does any guide or sub-category page lack a link to its parent hub or to at least one peer hub?**

- Issue if: At least 20% of pages on the guide template link neither to their profile parent hub nor to a peer hub.
- Why it matters: Links between a guide, its parent and its peers show Google the topic cluster and move authority to the hub pages that target the head terms.
- Group: crawl+profile · Ticket: Improvement / Medium · Unit: pages
- Needs: crawl, site-profile
- Evidence owners: `internal-authority`, new detector `hub-cluster-links`
- Site profile keys: `templates.guide`, `hub_clusters`
- Original: Do sub-category and guide templates feature secondary contextual navigation that links directly to peer guide hubs and parent topic clusters?

### Q49 · Internal linking & clusters

**Do news and article pages lack an in-body link to any commercial or guide hub?**

- Issue if: At least 20% of article-template pages have no in-body <a href> to a profile commercial hub.
- Why it matters: News and articles attract most external links and fresh crawls. Without links to the commercial hubs, that authority stays on short-lived articles instead of reaching the pages that earn revenue.
- Group: crawl+profile · Ticket: Improvement / Medium · Unit: pages
- Needs: crawl, stored-html, site-profile
- Evidence owners: `internal-authority`, new detector `article-to-hub-links`
- Site profile keys: `templates.article`, `commercial_hubs`
- Original: Are automated or taxonomy-driven internal links deployed across informational news/articles to pass link equity to commercial betting and guide hubs?

### Q75 · Commercial links & compliance

**Does any outbound affiliate link lack both rel="sponsored" (or nofollow) and routing through a robots-disallowed redirect path?**

- Issue if: At least one link to a profile affiliate domain or path has neither a sponsored/nofollow rel nor a robots-disallowed /go/-style route.
- Why it matters: Google requires paid and affiliate links to be qualified. Unqualified affiliate links can be treated as a link scheme, which risks a manual action and passes authority to partners.
- Group: crawl+profile · Ticket: Issue / High · Unit: links
- Needs: crawl, robots, site-profile
- Evidence owners: `external-link-integrity`, `robots-controls`, new detector `affiliate-link-qualification`
- Site profile keys: `affiliate`
- Original: Are outbound affiliate and partner links routed through a disallowed redirect path (e.g. /go/), obfuscated, or tagged with rel="sponsored"?

### Q82 · Crawl discovery provenance

**Is any URL population found in one discovery source (sitemaps, internal links, supplied Search Console or backlink exports) but missing from the others?**

- Issue if: At least one URL family is present in one source and absent from the internal link graph and the sitemaps.
- Why it matters: URLs that Google or other sites know about but the site no longer links or lists are unmanaged: old, parameter or orphan URLs that still use crawl budget and can stay indexed.
- Group: crawl · Ticket: Warning / Medium · Unit: URLs
- Needs: crawl, sitemaps
- Evidence owners: `discovery-source-provenance`
- Sheet said answerable: No (changed)
- Note: Crawl and sitemap sources are always available; Search Console and backlink exports widen the comparison when supplied.
- Original: Does the crawl audit cross-reference multiple discovery sources (XML sitemaps, internal HTML graph, GSC, and external backlink exports) to identify untracked URL populations?

### Q90 · Access-log bot verification

**Do verified search-bot hits in the server logs show a crawl drop, repeated 4xx/5xx responses, or crawling concentrated on non-canonical URLs?**

- Issue if: Supplied logs show any of: a week-on-week verified Googlebot hit drop over 30%, a URL with repeated 4xx/5xx to Googlebot, or over 20% of bot hits on non-canonical URLs.
- Why it matters: Server logs are the only direct record of what Googlebot actually requests. They show crawl budget spent on errors and duplicates, and falling crawl rates that come before ranking drops.
- Group: supplied-input · Ticket: Issue / Medium · Unit: requests
- Needs: logs
- Evidence owners: `validated-bot-log-analysis`
- Sheet said answerable: No (changed)
- Original: Does server access-log analysis of reverse-DNS verified search bot hits reveal crawl frequency drops, repeated 4xx/5xx errors, or non-canonical crawl waste?

### Q93 · XML sitemap architecture

**Does any XML sitemap fail to parse, exceed 50,000 URLs or 50MB uncompressed, or sit outside a sitemap index when the site has more than one sitemap?**

- Issue if: At least one sitemap file is unparseable or over a protocol limit, or multiple sitemaps exist with no index referencing them.
- Why it matters: Search engines reject a sitemap file that breaks the protocol, so none of its URLs are read.
- Group: crawl · Ticket: Error / High · Unit: sitemaps
- Needs: sitemaps
- Evidence owners: `sitemap-integrity`
- Note: Gzip is optional in the sitemap protocol, so an uncompressed sitemap is not a defect.
- Original: Do XML sitemaps strictly adhere to protocol limits (maximum 50,000 URLs and 50MB uncompressed per file) and use gzip compression within a valid sitemap index?

### Q95 · Mobile & interstitial compliance

**On a mobile render, does an overlay cover most of the viewport on load, or remove the primary content from the rendered DOM?**

- Issue if: A mobile render of a key template shows an overlay covering over 50% of the viewport, or rendered primary-content word count drops below 50% of the raw HTML.
- Why it matters: Intrusive interstitials count against page experience on mobile, and a gate that removes the content from the DOM stops it being indexed at all.
- Group: heuristic · Ticket: Warning / Medium · Unit: templates
- Needs: mobile-render
- Evidence owners: `mobile-rendering-parity`, new detector `interstitial-coverage`
- Note: Legally required cookie and age gates are allowed if they are reasonably sized and the content remains in the DOM.
- Original: Do mobile cookie consent dialogs, age gates, or promotional overlays comply with Google's intrusive interstitial guidelines by keeping underlying primary content crawlable?

### Q98 · Robots.txt

**Does a host's robots.txt fail its approved availability, syntax, sitemap-declaration or broad-rule policy?**

- Issue if: For a host required to publish robots.txt, the response is not a usable 200 file, a recognised directive is malformed, an approved sitemap declaration is missing or a broad Disallow rule violates the approved policy.
- Why it matters: An unavailable, malformed or over-broad robots.txt file can stop intended crawling and hide the sitemap routes that guide controlled discovery.
- Group: crawl+profile · Ticket: Warning / Medium · Unit: hosts
- Needs: crawl, robots, sitemaps, site-profile
- Evidence owners: `robots-controls`, `sitemap-integrity`, new detector `robots-file-policy`
- Note: Planned: no dedicated answerer yet. Needs raw robots response/body and approved host rules and sitemap declarations. Absence of robots.txt or of a Sitemap directive is not inherently a crawl failure; report policy non-compliance separately from observed blocking.
- Original: Does robots.txt return 200, parse correctly, declare the intended XML sitemap index and avoid broad accidental Disallow rules?

### Q99 · Directory and file exposure

**Does any tested document, upload or asset directory expose an unintended generated file listing?**

- Issue if: A scoped directory probe returns a generated file listing that exposes file or child-directory links and is not an approved public directory.
- Why it matters: Browsable directory listings can expose unpublished files, create low-value crawl paths and allow documents to be enumerated outside an intentional content journey.
- Group: heuristic · Ticket: Warning / Medium · Unit: directories
- Needs: crawl, stored-html, probes, site-profile
- Evidence owners: new detector `directory-listing-exposure`
- Note: Planned: no dedicated answerer yet. Listing fingerprints are candidates for manual confirmation against approved directories. Only scoped directory responses are tested; disabling listings does not prove that sensitive files cannot be fetched directly. Public document discovery belongs to Q100.
- Original: Are public document, upload and asset directories protected against unintended directory listings (auto-index) and file enumeration?

### Q100 · Document discovery

**Does any document in the approved search inventory lack its designated crawlable HTML hub link or required sitemap entry?**

- Issue if: An approved inventory document has no crawlable link from its designated HTML hub, or is marked for sitemap inclusion but is absent from its designated XML sitemap.
- Why it matters: Unlinked documents can be discovered inconsistently, while documents without a curated hub give users and crawlers little context about their purpose or relationship.
- Group: crawl+profile · Ticket: Warning / Medium · Unit: documents
- Needs: crawl, sitemaps, site-profile
- Evidence owners: `nonhtml-search-assets`, `discovery-source-provenance`, new detector `document-discovery-inventory`
- Note: Planned: no dedicated answerer yet. Requires an approved document inventory naming each HTML hub, whether sitemap inclusion is required, and the designated sitemap. Incomplete HTML, document or sitemap coverage cannot establish a Healthy result.
- Original: Are documents intended to appear in search linked from crawlable HTML hubs and included in the relevant XML sitemap?

## Indexability

### Q8 · International

**Is any page's <html lang> missing, invalid, or different from the language of its own self-referencing hreflang?**

- Issue if: At least one page has no or an invalid html lang, or an html lang whose language differs from its self-hreflang code.
- Why it matters: Conflicting language signals make it unclear which locale a page targets. Google does not use html lang for targeting, but Bing and assistive tools do, and a mismatch almost always shows a template bug that also affects hreflang.
- Group: crawl · Ticket: Warning / Medium · Unit: pages
- Needs: crawl
- Evidence owners: `locale-html-lang`, `hreflang-html-http`
- Original: Do the page hreflang and html lang declarations make sense and agree?

### Q9 · International

**Does any hreflang annotation lack a return link, or point at a URL that is not 200, is noindex, or canonicalises elsewhere?**

- Issue if: At least one hreflang pair is not reciprocal, or its target is non-200, noindex or non-canonical.
- Why it matters: Google ignores hreflang pairs that do not point at each other or that target non-canonical or non-indexable URLs, so the wrong language version ranks in each market.
- Group: crawl · Ticket: Error / High · Unit: annotations
- Needs: crawl, sitemaps
- Evidence owners: `hreflang-html-http`, `hreflang-sitemap`, `hreflang-noindex`, `canonical-target-validation`
- Original: Do hreflang links reciprocate, and do the pages they point to return 200 and allow indexing?

### Q10 · On-page

**Does any page declare more than one title, meta description, canonical or meta robots tag?**

- Issue if: At least one page has more than one of any of these elements in the raw HTML.
- Why it matters: With several canonicals Google may ignore them all; with several robots tags it applies the most restrictive one; with several titles it chooses one unpredictably. Each usually means two systems (theme and plugin) are writing the same tag.
- Group: crawl · Ticket: Issue / High · Unit: pages
- Needs: crawl, stored-html
- Evidence owners: `metadata-basics`, `canonical-declarations`
- Note: Header-vs-HTML conflicts are Q94.
- Original: Do any pages declare the title, description, canonical or robots tag more than once?

### Q11 · On-page

**Do two or more indexable, self-canonical pages share the same title or the same H1?**

- Issue if: At least one title or H1 value is shared by two or more indexable, self-canonical pages.
- Why it matters: Duplicate titles make pages compete for the same queries and lower click-through. They usually come from a template default that was never overridden.
- Group: crawl · Ticket: Warning / Medium · Unit: clusters
- Needs: crawl
- Evidence owners: `metadata-duplicates-aliases`
- Original: Do multiple pages share the same title or H1?

### Q12 · On-page

**Does any page place a head-only element (title, meta robots, canonical, hreflang link) inside <body>?**

- Issue if: At least one page has a head-only element parsed inside <body> of the raw HTML.
- Why it matters: Google stops reading the head at the first element that does not belong there. A canonical, robots or hreflang tag that ends up in the body is ignored.
- Group: crawl · Ticket: Error / High · Unit: pages
- Needs: crawl, stored-html
- Evidence owners: new detector `head-elements-in-body`
- Original: Are any head elements (canonical etc.) placed in the body instead of the head?

### Q15 · On-page

**Does any indexable page have no H1, more than one H1, or skip a heading level (for example H2 to H4)?**

- Issue if: At least one indexable page has zero or multiple H1s or a skipped heading level.
- Why it matters: Headings give the page its outline. A missing H1 or broken hierarchy makes the main topic less clear to search engines and screen readers. The ranking effect is small; the fix is usually one template change.
- Group: crawl · Ticket: Warning / Low · Unit: pages
- Needs: crawl, stored-html
- Evidence owners: `metadata-basics`, new detector `heading-sequence`
- Original: Are headings out of sequence on any pages?

### Q16 · Structured data

**Does any page contain structured data that fails to parse, or duplicate entities with conflicting values?**

- Issue if: At least one page has a JSON-LD/microdata parse error or conflicting duplicate entities.
- Why it matters: Search engines ignore markup that does not parse, so the page loses the rich result or entity information the markup was added for.
- Group: crawl · Ticket: Error / Medium · Unit: pages
- Needs: crawl
- Runner: answered today (schema-parser-diagnostics rows)
- Evidence owners: `schema-parser-diagnostics`
- Original: Is any schema markup invalid?

### Q17 · Social

**Does any indexable page lack og:title, og:description, og:image or twitter:card, or reference an og:image that does not return 200?**

- Issue if: At least 20% of indexable pages miss one of these tags, or any og:image returns non-200.
- Why it matters: Social tags do not affect rankings. They control the preview when a page is shared in social apps, chat tools and some AI answers, which affects click-through from those channels.
- Group: best-practice · Ticket: Improvement / Low · Unit: pages
- Needs: crawl
- Evidence owners: new detector `social-tags`
- Original: Are Open Graph and Twitter card tags in place?

### Q20 · Indexability

**Is any noindex page on a template the site profile marks as indexable, listed in a sitemap, or linked from the main navigation?**

- Issue if: At least one noindex URL matches an indexable profile template, appears in a sitemap, or is a navigation target.
- Why it matters: An unintended noindex removes the page from search completely. Noindex pages in sitemaps or navigation send contradictory signals and waste crawl.
- Group: crawl+profile · Ticket: Error / High · Unit: pages
- Needs: crawl, sitemaps, site-profile
- Evidence owners: `indexability-segmentation`
- Site profile keys: `templates`
- Note: Without a profile the noindex inventory by template is still produced, and the status is Needs validation.
- Original: Which pages are noindex, by template, and is that intentional?

### Q21 · Content quality

**Are inventory pages (for example games) thin or near-duplicates of each other?**

- Issue if: At least 10% of inventory-template pages have fewer than 250 main-content words or belong to a near-duplicate cluster.
- Why it matters: Large sets of thin or templated pages lower Google's view of site quality overall and are commonly 'Crawled, currently not indexed'. They also compete with each other for the same queries.
- Group: crawl+profile · Ticket: Warning / Medium · Unit: pages
- Needs: crawl, site-profile
- Runner: answered today (near-duplicate-content rows on the inventory template)
- Evidence owners: `content-quality`, `near-duplicate-content`
- Site profile keys: `templates.inventory`
- Original: Are the 7,500 game pages thin or near-duplicate?

### Q26 · Scope

**Did the crawl end before its scope was covered, with more than 2% fetch failures, or with rate limiting?**

- Issue if: The run stopped at a page/time limit, over 2% of fetches failed, or any 429/503 responses were recorded.
- Why it matters: An incomplete crawl understates every count in the audit. This question never becomes a ticket; when it fails, every other crawl answer is reported as Needs validation.
- Group: run-gate · Ticket: no ticket · Unit: run
- Needs: crawl
- Runner: answered today (run_context completeness gate)
- Evidence owners: `audit-run-integrity`, `audit-collection-safeguards`
- Original: Was the crawl complete enough to trust the counts?

### Q30 · Search evidence

**For any important template and locale, do Search Console records show important URLs not indexed, a Google-selected canonical different from the declared one, or indexed pages with no impressions?**

- Issue if: Supplied Search Console data shows any of: important URLs excluded, Google canonical != declared canonical, or indexed URLs with zero impressions over 90 days.
- Why it matters: Only Search Console shows what Google actually did with the pages the crawl found: whether it indexed them, which canonical it chose and whether they earn impressions. Crawl findings are the likely causes; this is the result.
- Group: supplied-input · Ticket: Issue / High · Unit: URLs
- Needs: gsc
- Runner: answered today (supplied Search Console / URL Inspection records)
- Evidence owners: `supplied-search-evidence`
- Sheet said answerable: No (changed)
- Original: Indexation test: for each important template × locale, how many URLs did Google discover, crawl and index; why did it exclude the rest; which canonical did it select; and do indexed pages get impressions?

### Q32 · International

**Is the main content of a locale page in a different language from its URL locale and html lang, or nearly identical to the default-language version?**

- Issue if: At least one locale page's detected content language differs from its declared locale, or it is a near-duplicate of its default-language alternate.
- Why it matters: Untranslated locale pages are duplicates. Google may fold them into the original or treat them as low-quality, so the locale never ranks and the whole site looks thinner.
- Group: heuristic · Ticket: Issue / Medium · Unit: pages
- Needs: crawl
- Runner: answered today (locale-html-lang shared-signature rows)
- Evidence owners: `locale-html-lang`, `near-duplicate-content`
- Note: Language detection is statistical; confirm a sample before ticketing.
- Original: Are the language pages genuinely translated and worth indexing?

### Q36 · URL consolidation

**Are profile sub-tab URLs indexable and self-canonical instead of consolidated onto the main profile?**

- Issue if: At least one URL matching the profile sub-tab pattern is 200, indexable and self-canonical.
- Why it matters: Each tab multiplies the number of thin, near-identical URLs per profile, which splits signals and uses crawl budget on pages that should not rank on their own.
- Group: crawl+profile · Ticket: Warning / Medium · Unit: URLs
- Needs: crawl, site-profile
- Evidence owners: `parameter-and-faceted-controls`, `indexability-segmentation`, new detector `profile-subtab-indexability`
- Site profile keys: `templates.profile_subtab`
- Original: Do user profile tabs (e.g. updates, reviews, winners) generate unnecessary indexable sub-URLs instead of consolidating authority onto the primary profile?

### Q37 · Indexability & thin content

**Is any empty user profile indexable or listed in a sitemap?**

- Issue if: At least one profile-template page meeting the profile's empty rule is indexable or in a sitemap.
- Why it matters: Empty user profiles are thin pages in bulk, and they are a common target for spam sign-ups. Indexing them lowers perceived site quality.
- Group: crawl+profile · Ticket: Warning / Medium · Unit: pages
- Needs: crawl, sitemaps, site-profile
- Evidence owners: `indexability-segmentation`, `content-quality`, new detector `empty-profile-indexability`
- Site profile keys: `templates.profile`, `empty_profile_rule`
- Original: Are newly created, inactive, or empty user profiles noindexed until they publish substantive, active public content?

### Q41 · International & URL structure

**Does any localized page sit outside its locale folder, or does a locale folder serve content in another language?**

- Issue if: At least one page's declared language (html lang or self-hreflang) does not match its first path segment's locale.
- Why it matters: Mixed-language folders stop per-locale reporting in Search Console and make hreflang mapping and geotargeting error-prone.
- Group: crawl · Ticket: Warning / Medium · Unit: pages
- Needs: crawl
- Evidence owners: `locale-html-lang`, new detector `locale-path-consistency`
- Note: A root-level default language is valid if it is consistent; the site profile can declare it.
- Original: Do all localized pages reside in dedicated locale folders (e.g. /en/, /es/) rather than mixing languages under root directories?

### Q47 · Information architecture & taxonomy

**Does any content page lack a visible breadcrumb or BreadcrumbList markup, or does the markup disagree with the visible trail?**

- Issue if: At least 20% of content pages lack both, or any page's BreadcrumbList items differ from its visible breadcrumb links.
- Why it matters: Breadcrumbs link each page to its parent topic and appear in search results. Markup that differs from the visible trail is ignored.
- Group: best-practice · Ticket: Improvement / Low · Unit: pages
- Needs: crawl, stored-html
- Evidence owners: `structured-data-feature-rules`, new detector `breadcrumb-consistency`
- Note: Whether editors can set breadcrumbs independently of URLs is a CMS question for the client; only the published output is tested.
- Original: Can editorial teams configure custom hierarchical breadcrumbs to enforce intentional topic parent-child clusters independently of CMS URL paths?

### Q50 · Content quality & topical authority

**Do leading competitors cover subtopics and entities of the core queries that the site does not?**

- Issue if: An entity or SERP fan-out comparison finds subtopics covered by the top competitors and missing from the site.
- Why it matters: Search and AI answers expand a query into related sub-questions. Sites that cover only the head topic lose the long tail and are cited less.
- Group: external · Ticket: Improvement / Medium · Unit: topics
- Needs: external-api
- Evidence owners: outside crawler_cli
- Original: Does content coverage address full search journey entity relationships and subtopics (fan-out query expansion) compared to leading competitors?

### Q51 · Semantic HTML5

**Does any template's raw HTML lack a <main> element, or lack header and footer landmarks?**

- Issue if: At least one template (by URL pattern) has no <main>, or neither <header> nor <footer>, in its raw HTML.
- Why it matters: Landmarks help parsers separate the main content from navigation and boilerplate. The search effect is small; the main benefit is accessibility and cleaner extraction by AI crawlers.
- Group: best-practice · Ticket: Improvement / Low · Unit: templates
- Needs: stored-html
- Evidence owners: new detector `semantic-landmarks`
- Original: Does the page template leverage semantic landmark elements (<header>, <main>, <article>, <aside>, <footer>) to clearly define core vs boilerplate content?

### Q52 · Semantic HTML5

**Are comparison toplists or odds tables on the profile's comparison templates built from <div>s with no <table>?**

- Issue if: A page on a profile comparison template contains the toplist selector with no <table> element inside it.
- Why it matters: Table markup is read as rows and columns of data, which makes comparison content easier to extract for featured snippets and AI answers.
- Group: heuristic · Ticket: Improvement / Low · Unit: templates
- Needs: stored-html, site-profile
- Evidence owners: new detector `table-markup`
- Site profile keys: `templates.comparison`
- Original: Are comparison toplists, odds boards, and structured reviews built using semantic HTML <table> elements (<thead>, <tbody>, <th>, <td>) rather than nested <div>s?

### Q53 · Semantic HTML5

**Are FAQ answers missing from the raw HTML (loaded only when clicked)?**

- Issue if: At least one page has an FAQ answer (from FAQPage markup or accordion selectors) whose text is absent from its raw HTML.
- Why it matters: Content that loads only on click is not indexed. Hidden-but-present content (CSS-collapsed or <details>) is indexed normally.
- Group: crawl · Ticket: Warning / Medium · Unit: pages
- Needs: crawl, stored-html
- Evidence owners: `rendered-indexing-parity`, new detector `faq-answer-presence`
- Note: Using <details>/<summary> is good practice but not required; the defect is answers absent from the HTML.
- Original: Are collapsible FAQs and accordion sections marked up using <details> and <summary> elements to ensure clear machine-readability of hidden content?

### Q54 · Semantic HTML5 & images

**Are most content images inside the main content without a <figure> and <figcaption>?**

- Issue if: Over 50% of in-content images on content templates have no enclosing <figure> with a <figcaption>.
- Why it matters: Captions give image search extra context next to alt text. The effect is small and mostly on image search.
- Group: best-practice · Ticket: Improvement / Low · Unit: images
- Needs: stored-html
- Evidence owners: `image-markup`, new detector `figure-markup`
- Original: Are contextual images, infographics, and charts wrapped in <figure> and <figcaption> elements for enhanced accessibility and image search indexing?

### Q55 · Semantic HTML5

**Are repeated disclaimers and disclosures placed inside the main content rather than an <aside> or the footer?**

- Issue if: On at least 20% of content pages, a profile disclaimer phrase appears inside <main>/<article> and outside any <aside>.
- Why it matters: Repeated boilerplate inside the main content dilutes it and inflates near-duplicate similarity between pages. Marking it as an aside separates it from the page's real topic.
- Group: best-practice · Ticket: Improvement / Low · Unit: pages
- Needs: stored-html, site-profile
- Evidence owners: new detector `disclaimer-placement`
- Site profile keys: `disclaimer_phrases`
- Original: Are non-core contextual notices (e.g. responsible gambling disclaimers, affiliate disclosures) isolated in <aside> elements?

### Q56 · Semantic HTML5 & schema

**Do article pages show a date with no <time datetime>, or a date that disagrees with datePublished/dateModified in structured data?**

- Issue if: At least one article page's visible date differs from its schema date, or 20% of article pages have no <time datetime>.
- Why it matters: Google chooses the date shown in results from several signals. When the visible date and the markup disagree it may show the wrong date or none.
- Group: best-practice · Ticket: Warning / Low · Unit: pages
- Needs: stored-html
- Evidence owners: `structured-data-feature-rules`, new detector `date-consistency`
- Original: Are article timestamps, reading times, and publication dates marked up with semantic <time> tags and matching schema properties?

### Q57 · SERP presentation & freshness

**Does any commercial review or toplist title or H1 show a past year, or a month more than one month before the crawl?**

- Issue if: At least one page on a profile commercial template has a year earlier than the crawl year (or a stale month) in its title or H1.
- Why it matters: A past date in the title looks out of date in results and lowers click-through on queries where users expect current offers.
- Group: crawl+profile · Ticket: Improvement / Medium · Unit: pages
- Needs: crawl, site-profile
- Evidence owners: `metadata-basics`, new detector `stale-title-dates`
- Site profile keys: `templates.commercial`
- Note: Adding the current month without actually updating the content is a known pattern Google may ignore; the date should reflect a real review.
- Original: Do commercial review and toplist titles, H1s, and metadata dynamically display the current month and year to signal freshness in SERPs?

### Q58 · On-page & SERP features

**Does any long-form page lack a table of contents of in-page links to its H2 sections?**

- Issue if: At least 20% of pages with over 1,500 words and 4+ H2s have no set of #fragment links to their H2 ids.
- Why it matters: In-page jump links help users and can appear as 'Jump to' links in search results.
- Group: best-practice · Ticket: Improvement / Low · Unit: pages
- Needs: crawl, stored-html
- Evidence owners: new detector `toc-presence`
- Original: Do long-form guide and toplist pages include an anchor-linked Table of Contents (TOC) to generate rich SERP sitelinks and improve navigation?

### Q59 · E-E-A-T & author entities

**Does any review or affiliate article lack a visible author byline linked to an author page, or author markup?**

- Issue if: At least one page on a profile review template has no linked byline and no author property in its Article/Review markup.
- Why it matters: Gambling is a Your Money or Your Life topic. Google's quality guidelines look for who wrote and checked the content, and anonymous reviews rank poorly in these results.
- Group: crawl+profile · Ticket: Improvement / Medium · Unit: pages
- Needs: crawl, stored-html, site-profile
- Evidence owners: `structured-data-feature-rules`, new detector `author-bylines`
- Site profile keys: `templates.review`
- Original: Do review and affiliate articles display transparent author, fact-checker, and expert reviewer bylines with links to author entity profiles (E-E-A-T)?

### Q60 · E-E-A-T & content freshness

**Does any article page lack both a visible updated date and dateModified, or have dateModified earlier than datePublished?**

- Issue if: At least one article page has no updated date in copy or markup, or dateModified < datePublished.
- Why it matters: A clear last-updated date tells users and search engines the content is maintained, which matters for pages about offers and rules that change.
- Group: best-practice · Ticket: Warning / Low · Unit: pages
- Needs: stored-html
- Evidence owners: `structured-data-feature-rules`, new detector `date-consistency`
- Original: Does the template differentiate between original publication date and 'Last Updated' date in both visible copy and structured data?

### Q61 · Content formatting & E-E-A-T

**Are quotations shown as styled paragraphs instead of <blockquote> with an attribution?**

- Issue if: A sampled quotation on a content template is not inside <blockquote> or <q>, or has no cite or visible attribution.
- Why it matters: Marking quotations and their source makes attribution clear to users and to AI systems that cite content. The search effect is minor.
- Group: heuristic · Ticket: Improvement / Low · Unit: pages
- Needs: stored-html
- Evidence owners: new detector `quotation-markup`
- Note: Quotations cannot be found reliably without markup, so this stays a manual sample.
- Original: Are expert commentary and authoritative quotations marked up with semantic <blockquote> elements and proper citation attribution?

### Q62 · Anchor text optimization

**Do internal links to review or commercial pages use generic anchor text without the entity name?**

- Issue if: At least 20% of internal links to profile commercial templates use an anchor from the profile's generic phrase list.
- Why it matters: Anchor text tells Google what the target page is about. Generic labels such as 'Read review' waste that signal across thousands of links.
- Group: crawl+profile · Ticket: Improvement / Medium · Unit: links
- Needs: crawl, site-profile
- Evidence owners: `internal-authority`, new detector `generic-anchor-text`
- Site profile keys: `generic_anchor_phrases`, `templates.review`
- Original: Do internal commercial links use entity-specific, descriptive anchor text (e.g. 'Read [Brand] Review') rather than generic 'Read Review' labels?

### Q71 · Canonicalization

**Is any indexable 200 HTML page missing a canonical (HTML link or HTTP header)?**

- Issue if: At least one 200, indexable HTML page has neither a <link rel=canonical> nor a Link canonical header.
- Why it matters: Without a declared canonical, Google picks one itself among parameter, case and trailing-slash variants, and may choose the wrong URL.
- Group: crawl · Ticket: Warning / Medium · Unit: pages
- Needs: crawl
- Evidence owners: `canonical-declarations`
- Original: Does every public HTML page—including the homepage, category roots, and schedule pages—explicitly output a canonical link tag?

### Q73 · Canonicalization & error handling

**Does any non-homepage URL canonicalise to the homepage?**

- Issue if: At least one URL other than the homepage and its variants declares the homepage as its canonical.
- Why it matters: Google treats a canonical to the homepage from unrelated pages as a soft 404 and ignores it. Retired pages should return 404/410 or 301 to a relevant replacement.
- Group: crawl · Ticket: Error / High · Unit: URLs
- Needs: crawl
- Evidence owners: `canonical-target-validation`, `soft404-error-routes`
- Original: Are deleted, deprecated, or orphan URLs mistakenly canonicalised to the homepage (soft 404s) instead of returning a 404/410 status or a relevant 301 redirect?

### Q78 · Taxonomy & indexability

**Is any taxonomy archive that acts as a hub set to noindex?**

- Issue if: At least one noindex tag, category or author URL is a profile hub or is in the top 10% of pages by internal inlinks.
- Why it matters: Noindexing a hub removes its own chance to rank, and over time Google also crawls its links less, so the pages beneath it lose discovery.
- Group: crawl+profile · Ticket: Issue / Medium · Unit: pages
- Needs: crawl, site-profile
- Evidence owners: `indexability-segmentation`, `internal-authority`
- Site profile keys: `templates.taxonomy`
- Original: Does the indexing strategy for taxonomy archives (tags, categories, author pages) avoid applying noindex to pages that serve as key navigational hubs?

### Q80 · Canonicalization standards

**Does any canonical tag use a relative URL?**

- Issue if: At least one canonical declaration lacks a scheme and host.
- Why it matters: Relative canonicals resolve against whatever host served the page, so staging mirrors, http variants and proxies all declare themselves canonical.
- Group: crawl · Ticket: Warning / Low · Unit: pages
- Needs: crawl, stored-html
- Evidence owners: `canonical-declarations`
- Original: Are canonical URL link tags declared as fully-qualified absolute URLs (including protocol and domain) rather than relative paths?

### Q83 · Hreflang & sitemaps

**Do pages carry more than 20 hreflang alternates in the HTML head while no sitemap provides hreflang?**

- Issue if: At least one page has over 20 head hreflang links and the sitemaps contain no xhtml:link annotations.
- Why it matters: Large hreflang sets in the head add weight to every page and are hard to keep reciprocal. Sitemaps keep them in one place. Both methods are valid; this is only worth changing at scale.
- Group: best-practice · Ticket: Improvement / Low · Unit: pages
- Needs: crawl, sitemaps
- Evidence owners: `hreflang-html-http`, `hreflang-sitemap`
- Original: Are hreflang multi-regional annotations deployed via XML sitemaps to prevent HTML page-weight bloat on large multilingual sites?

### Q84 · Structured data & rich results

**Does any structured-data entity of a rich-result type miss a property Google requires?**

- Issue if: At least one entity of a supported rich-result type lacks a required property under the documented rule set.
- Why it matters: An entity missing a required property is not eligible for its rich result, so the markup has no effect in search.
- Group: crawl · Ticket: Issue / Medium · Unit: entities
- Needs: crawl
- Evidence owners: `structured-data-feature-rules`
- Original: Do schema entities satisfy all mandatory Google Search feature guidelines and required fields for target rich results (e.g. Product, FAQ, Article)?

### Q85 · JavaScript & rendering parity

**Does rendering change the canonical, title, meta robots or hreflang compared with the raw HTML?**

- Issue if: At least one page's rendered value differs from its raw-HTML value for any of these elements.
- Why it matters: Google may use either version. A canonical or robots tag changed by JavaScript is unreliable, and a noindex in the raw HTML stops Google from rendering the page at all.
- Group: crawl · Ticket: Error / High · Unit: pages
- Needs: crawl, render
- Evidence owners: `rendered-indexing-parity`
- Original: Does client-side JavaScript execution alter, inject, or contradict critical metadata (canonical, title, robots directives) compared to the raw server HTML?

### Q87 · Non-HTML search assets

**Is any non-HTML document indexable with neither a Link canonical header nor an X-Robots-Tag?**

- Issue if: At least one linked PDF/DOC/XLS returns 200 with no X-Robots-Tag and no Link rel=canonical header.
- Why it matters: Without these headers, documents that duplicate an HTML page can outrank it, and documents that should stay private can be indexed.
- Group: crawl · Ticket: Warning / Low · Unit: documents
- Needs: crawl
- Evidence owners: `nonhtml-search-assets`
- Original: Do indexable non-HTML documents (e.g. PDFs, Word docs, spreadsheets) deliver HTTP Link canonical headers and appropriate X-Robots-Tag indexation directives?

### Q94 · Header vs HTML parity

**Does any page's HTTP Link canonical or X-Robots-Tag disagree with its HTML canonical or meta robots?**

- Issue if: At least one page has a header canonical different from its HTML canonical, or header and meta robots with conflicting index/follow values.
- Why it matters: When the header and the HTML disagree, Google may ignore both canonicals and applies the most restrictive robots directive, which can deindex a page by accident.
- Group: crawl · Ticket: Error / High · Unit: pages
- Needs: crawl
- Runner: answered today (indexability-segmentation header/meta robots conflicts)
- Evidence owners: `canonical-declarations`, `indexability-segmentation`
- Original: Do HTTP response headers (Link: rel="canonical", X-Robots-Tag) agree with in-page HTML <link rel="canonical"> and <meta name="robots"> declarations without conflicting directives?

## Crawl Budget

### Q24 · Crawl waste

**Does any parameter URL family exceed its expected size, or grow between runs, while being crawlable and indexable?**

- Issue if: A family is over 10% of crawled URLs or over its profile maximum, or grows over 20% from the previous run, and its URLs are crawlable and indexable.
- Why it matters: Unbounded parameter families use crawl budget on duplicates and slow the crawling of real pages. A family that keeps growing means the problem gets worse with every crawl.
- Group: crawl+profile · Ticket: Issue / High · Unit: URL families
- Needs: crawl, site-profile
- Evidence owners: `crawl-waste-url-families`, `parameter-and-faceted-controls`
- Site profile keys: `parameter_families`
- Note: Without a profile, families are still sized and flagged at 10%; run-over-run growth needs a previous run ID.
- Original: Are the parameter URL families sized correctly, and does the betId family keep growing?

### Q34 · Index bloat & lifecycle

**Is any expired or ended lifecycle page 200 and indexable with no link to a live replacement, or still listed in a sitemap?**

- Issue if: At least one URL matching the profile's expired markers is 200 + indexable without a link to a live equivalent, or is in a sitemap.
- Why it matters: Expired pages pile up into a large set of dead-end, low-value URLs. The fix depends on whether the page has links and demand: keep and link onward, 301, or 410.
- Group: crawl+profile · Ticket: Warning / Medium · Unit: pages
- Needs: crawl, sitemaps, site-profile
- Evidence owners: `indexability-segmentation`, new detector `lifecycle-pages`
- Site profile keys: `lifecycle`
- Original: How are expired, ended, or out-of-stock lifecycle pages handled to prevent index bloat and preserve crawl equity?

### Q35 · Crawl efficiency

**Does rendering a page issue more than 50 API (XHR/fetch) requests, or any uncacheable one?**

- Issue if: A rendered page issues over 50 XHR/fetch requests, or an API response carries Cache-Control no-store/private.
- Why it matters: Google's renderer fetches these requests too, from the same crawl budget. High request counts slow rendering and can cause timeouts that leave content out of the index.
- Group: heuristic · Ticket: Warning / Low · Unit: templates
- Needs: render
- Evidence owners: `critical-resource-impact`, new detector `render-api-requests`
- Original: Do client-side scripts, SPA hydrations, or internal links trigger excessive, uncacheable API requests that waste server resources and crawler budget?

### Q70 · Robots.txt & crawl budget

**Are internal search result or feed URLs found in the crawl, and allowed by robots.txt?**

- Issue if: At least one discovered URL matching internal-search or feed patterns has allowed_by_robots = true.
- Why it matters: Internal search creates unlimited low-value URLs, and Google recommends blocking it. Feeds are duplicates of pages that are already crawled.
- Group: crawl · Ticket: Warning / Medium · Unit: URLs
- Needs: crawl, robots
- Evidence owners: `robots-controls`, `crawl-waste-url-families`
- Note: Search and feed URL patterns can be overridden in the site profile.
- Original: Does robots.txt explicitly disallow internal search parameters (?s=, /search/) and RSS/API feeds (/feed/, /api/feed/) to conserve crawl budget?

### Q81 · Crawl safety & rate limiting

**Did the audit crawl trigger 429/503 rate limiting or measurable slowing of the origin?**

- Issue if: The run recorded any 429/503, or response times rising over 50% during the run.
- Why it matters: This is about the audit crawler's own settings, not a site defect. Rate-limited responses do not show the site's normal behaviour, so affected rows are rechecked rather than ticketed.
- Group: run-gate · Ticket: no ticket · Unit: run
- Needs: crawl
- Evidence owners: `audit-collection-safeguards`
- Sheet said answerable: No (changed)
- Original: Are crawler request rates and concurrency configured safely to avoid triggering origin 429 rate limits or server degradation during deep audits?

### Q88 · Server response & crawl budget

**Does any template have p90 server response time above 600 ms or p99 above 1.5 s?**

- Issue if: At least one template with 20+ samples has p90 TTFB > 600 ms or p99 > 1,500 ms.
- Why it matters: Google lowers its crawl rate when the server is slow, so fewer pages get crawled. Slow TTFB also pushes LCP out of the 'good' range.
- Group: crawl · Ticket: Warning / Medium · Unit: templates
- Needs: crawl
- Evidence owners: `performance-distribution`
- Note: Measured from the crawler's location, not Google's.
- Original: What is the server response time (TTFB) distribution across page templates (mean, p90, p99), and do slow origin outliers constrain crawl capacity?

### Q89 · Conditional HTTP caching

**Does the server ignore conditional requests, returning 200 instead of 304 for unchanged pages?**

- Issue if: On a probe sample, pages that send ETag or Last-Modified return 200 to a matching conditional request, or send neither validator.
- Why it matters: A 304 lets Googlebot skip downloading unchanged pages, which saves crawl capacity for pages that have changed.
- Group: crawl · Ticket: Improvement / Low · Unit: templates
- Needs: probes
- Evidence owners: `conditional-cache-behaviour`
- Sheet said answerable: No (changed)
- Original: Does the web server support conditional HTTP requests (ETag / If-None-Match and Last-Modified / If-Modified-Since) returning 304 Not Modified to optimize search crawler efficiency?

### Q101 · Crawl traps

**Does any discovered navigation-state family exceed its approved finite URL, date-range or traversal-depth limit?**

- Issue if: A calendar, pagination, sort or filter family exceeds its documented URL-count, date-range or traversal-depth bound, or exposes a next-state link beyond that bound.
- Why it matters: Unbounded navigation states can create near-duplicate URL populations that consume crawl capacity without adding useful indexable content.
- Group: crawl+profile · Ticket: Warning / Medium · Unit: URL families
- Needs: crawl, site-profile
- Evidence owners: `crawl-waste-url-families`, `parameter-and-faceted-controls`, new detector `bounded-navigation-states`
- Note: Planned: no dedicated answerer yet. Requires approved finite limits for each family; a finite saved crawl cannot prove an infinite URL space. Report observed bound violations, qualify partial coverage and never traverse indefinitely.
- Original: Do calendars, pagination, sort orders, filters and other state combinations create uncontrolled crawl paths or infinite URL spaces?

## Maintenance (broken links etc.)

### Q2 · URL variants

**Does any http/https or www/non-www variant fail to 301 or 308 to the canonical host in one hop?**

- Issue if: At least one host or protocol variant returns 200, a non-permanent redirect, or a chain of more than one hop.
- Why it matters: Variants that do not redirect permanently split links and signals across duplicate copies of the site, and redirect chains slow crawling.
- Group: crawl · Ticket: Error / High · Unit: variants
- Needs: probes
- Evidence owners: `url-host-and-variants`
- Original: Do the www/non-www and http/https versions redirect to the canonical URL?

### Q5 · Security

**Does any HTTPS page load an http:// resource, or link internally to an http:// URL?**

- Issue if: At least one HTTPS page references an http:// image, script, stylesheet or iframe, or has an internal http:// link.
- Why it matters: Browsers block insecure scripts and flag insecure images, which breaks pages and removes the secure padlock. Internal http:// links add a redirect hop to every click and crawl.
- Group: crawl · Ticket: Issue / Medium · Unit: pages
- Needs: crawl, stored-html
- Evidence owners: `nonproduction-https`, new detector `mixed-content`
- Original: Does the site link to or embed non-SSL (http://) assets?

### Q6 · Error handling

**Does a made-up URL under any main section return a status other than 404 or 410?**

- Issue if: At least one synthetic non-existent URL returns 200 or redirects to a live page.
- Why it matters: If any URL returns 200, junk and mistyped URLs can be crawled and indexed indefinitely as soft 404s, and genuinely removed pages never drop out.
- Group: crawl · Ticket: Error / High · Unit: sections
- Needs: probes
- Evidence owners: `soft404-error-routes`
- Original: Do made-up URLs under the main sections return 404?

### Q7 · URL variants

**Does an uppercase or camelCase variant of a URL return 200 without redirecting or canonicalising to the lowercase URL?**

- Issue if: At least one case variant returns 200 with a self-referencing or missing canonical.
- Why it matters: URL paths are case-sensitive. Case variants that return 200 create duplicate URLs whenever someone links with the wrong case.
- Group: crawl · Ticket: Warning / Medium · Unit: URLs
- Needs: probes
- Evidence owners: `url-host-and-variants`
- Original: What happens when pages are requested in camelCase or uppercase?

### Q19 · Redirects

**Does any backlinked or legacy URL return an error, or redirect in a chain, instead of a single 301 to a relevant live page?**

- Issue if: At least one supplied backlinked or archived URL returns 4xx/5xx or needs more than one redirect hop.
- Why it matters: External links to dead URLs pass no value. Each one fixed with a single 301 recovers authority the site has already earned.
- Group: supplied-input · Ticket: Issue / High · Unit: URLs
- Needs: backlinks, probes
- Evidence owners: `response-status-and-redirect-history`
- Sheet said answerable: No (changed)
- Note: Needs a backlink export (Ahrefs/Semrush); archived URLs can come from the crawler's Wayback seeding.
- Original: Do the backlinked dead URLs and legacy URLs behave as the 25 Sep audit reported?

### Q22 · Internal linking

**Does any internal link point at a URL that returns 4xx/5xx, redirects, is noindex, or canonicalises elsewhere?**

- Issue if: At least one internal link target has one of these states.
- Why it matters: Broken links waste crawl and frustrate users. Links to redirects, noindex or non-canonical URLs pass weaker signals and make Google crawl two URLs to reach one page.
- Group: crawl · Ticket: Issue / Medium · Unit: links
- Needs: crawl
- Runner: answered today (internal-link-targets error targets)
- Evidence owners: `internal-link-targets`
- Note: Priority rises to High for 4xx/5xx targets linked from navigation.
- Original: Do internal links point at 404s, redirects, noindex or non-canonical URLs?

### Q25 · Redirects

**Does the site redirect or change content based on Accept-Language or the visitor's IP location?**

- Issue if: The same URL gives a different status, Location or primary content when Accept-Language or egress country changes.
- Why it matters: Googlebot crawls mostly from the US without an Accept-Language header. Automatic locale redirects can hide every other locale version from Google.
- Group: crawl · Ticket: Error / High · Unit: URLs
- Needs: probes
- Evidence owners: `locale-redirects`
- Sheet said answerable: No (changed)
- Note: Accept-Language needs no proxy; the IP part needs proxies for each tested country.
- Original: Does the site redirect by Accept-Language or IP?

### Q27 · Host hygiene

**Is any non-production or alternate host (staging, dev, preview, other brand hostnames) publicly reachable and indexable?**

- Issue if: A host from the profile list, found in links, or found in certificate transparency logs returns 200 HTML without noindex or auth.
- Why it matters: Open staging and duplicate hosts can be indexed as copies of the live site, competing with it and exposing unreleased content.
- Group: crawl+profile · Ticket: Error / High · Unit: hosts
- Needs: probes, site-profile
- Evidence owners: `nonproduction-https`
- Site profile keys: `nonproduction_hosts`
- Sheet said answerable: No (changed)
- Note: Host discovery beyond the profile list and linked hosts (DNS or certificate-log enumeration) is an external step.
- Original: Are non-production hosts and other rainbet hostnames exposed or indexable?

### Q28 · External links

**Does any outbound link return 4xx/5xx, or does a paid/affiliate outbound link lack rel=sponsored or nofollow?**

- Issue if: On an external recheck, at least one outbound link returns 4xx/5xx, or a profile affiliate link lacks the rel qualification.
- Why it matters: Broken outbound links reflect poor maintenance on review pages. Unqualified paid links break Google's link-scheme policy (see Q75).
- Group: crawl · Ticket: Warning / Medium · Unit: links
- Needs: crawl, probes
- Evidence owners: `external-link-integrity`
- Sheet said answerable: No (changed)
- Note: The external recheck runs at a slow, conservative rate.
- Original: Are outbound links broken, or missing sponsored/nofollow where needed?

### Q33 · Site security & spam

**Does the site host user-generated spam, injected content or spam profiles?**

- Issue if: At least one crawled page matches the spam pattern list (pharma, casino-spam, essay, crypto-scam terms or injected hidden links) outside the site's own topic.
- Why it matters: Hosted spam can trigger a manual action for user-generated spam or a site-reputation abuse action, and lowers trust in the whole domain.
- Group: heuristic · Ticket: Error / High · Unit: pages
- Needs: crawl, stored-html
- Evidence owners: new detector `ugc-spam-patterns`
- Note: A gambling site's own vocabulary overlaps spam lists; every match needs review.
- Original: Does the site host user-generated spam, exploit pages, or spam profiles that dilute domain quality and risk search penalties?

### Q39 · Internal linking

**Does any link inside an H2 or H3 point at a redirecting, error or non-canonical URL?**

- Issue if: At least one link whose xpath is within an h2/h3 has a non-200 or non-canonical target.
- Why it matters: Section-heading links usually point to the most important related pages. When they redirect or break, the link that matters most on the page passes the least.
- Group: crawl · Ticket: Warning / Low · Unit: links
- Needs: crawl
- Runner: answered today (internal-link-targets error targets linked from an H2/H3)
- Evidence owners: `internal-link-targets`
- Note: A subset of Q22 reported separately because it is usually a separate content fix.
- Original: Do content headings (H2/H3) or section titles link to outdated, redirecting, or mismatched slugs rather than direct canonical destinations?

### Q42 · Status codes & errors

**Does any page return 200 while showing an error or 'not found' message?**

- Issue if: At least one 200 page has an error-page title/body signature or matches the site's 404 template.
- Why it matters: Soft 404s are reported as errors in Search Console, waste crawl, and keep dead pages indexed.
- Group: crawl · Ticket: Error / High · Unit: pages
- Needs: crawl, probes
- Evidence owners: `soft404-error-routes`
- Original: Do error pages return proper HTTP status codes (404/410/500) at the server level rather than returning 200 OK with client-rendered error notices?

### Q43 · Link equity & architecture

**Do sitewide header or footer templates link to third-party or network sites outside the profile's allowed list, without nofollow?**

- Issue if: At least one followed external link appears on over 50% of pages and its domain is not in the profile's allowed list.
- Why it matters: Sitewide followed links between sister sites can look like a link network. They also add a link to every page that points visitors away from the site.
- Group: crawl+profile · Ticket: Improvement / Low · Unit: links
- Needs: crawl, site-profile
- Evidence owners: `external-link-integrity`, new detector `sitewide-external-links`
- Site profile keys: `allowed_external_domains`
- Original: Do sitewide footer or navigation templates leak internal PageRank by linking out to non-essential network websites or third-party properties?

### Q72 · Redirects & internal links

**Does any internal link use the non-canonical trailing-slash form and cause a redirect?**

- Issue if: At least one internal link differs from its final URL only by a trailing slash.
- Why it matters: Each such link costs an extra redirect for users and crawlers, and usually comes from one template or a menu setting.
- Group: crawl · Ticket: Warning / Low · Unit: links
- Needs: crawl
- Evidence owners: `internal-link-targets`, `url-host-and-variants`
- Original: Do all internal links strictly match the site's trailing-slash URL convention to eliminate unnecessary 301/308 redirect hops?

### Q74 · Asset accessibility

**Does any internally referenced image, video, script or stylesheet return 403 or another 4xx?**

- Issue if: At least one first-party asset referenced by a crawled page returns 4xx.
- Why it matters: Missing images and scripts break pages for visitors, and a render resource that returns an error leaves Google with an incomplete page.
- Group: crawl · Ticket: Issue / Medium · Unit: assets
- Needs: crawl, render
- Evidence owners: `image-resource-delivery`, `critical-resource-impact`
- Original: Do any internal media files, static uploads, or script assets in content directories return 403 Forbidden status codes to crawlers and visitors?

### Q76 · Subdomain & link hygiene

**Do internal links point to staging, admin, preview or other non-canonical subdomains, or to hosts that don't resolve?**

- Issue if: At least one link to a same-site subdomain other than the canonical host fails DNS or points at a non-production host.
- Why it matters: Links to staging or admin hosts leak those hosts to crawlers and users. Links to dead subdomains are broken links.
- Group: crawl · Ticket: Issue / Medium · Unit: links
- Needs: crawl
- Evidence owners: `internal-link-targets`, `nonproduction-https`
- Original: Do internal page links inadvertently point to non-resolving staging, admin, or obsolete subdomains (e.g. admin., cache., preview.)?

### Q77 · Subdomain & index hygiene

**Are cache, CDN, image-resizer or preview hosts serving indexable HTML copies of pages?**

- Issue if: At least one profile cache/preview host or path returns 200 HTML without noindex, a canonical to the main host, or a robots block.
- Why it matters: HTML copies on cache or preview hosts are duplicates of the site and can be indexed instead of it.
- Group: crawl+profile · Ticket: Warning / Medium · Unit: hosts
- Needs: probes, site-profile
- Evidence owners: `nonproduction-https`, `robots-controls`
- Site profile keys: `nonproduction_hosts`
- Note: Image-resizer paths that serve images (not HTML) should stay crawlable, or image search breaks; do not block /_next/image in robots.txt.
- Original: Are cache, CDN image-resizer, or preview subdomains (e.g. cache.domain.com, /_next/image/) blocked from search crawling and indexing?

### Q79 · Server errors & 5xx stability

**Does any URL return 5xx both in the crawl and on a live recheck?**

- Issue if: At least one URL returns 5xx in the run and again on recheck.
- Why it matters: Persistent 5xx errors make Google slow its crawl of the whole site and drop the affected pages from the index.
- Group: crawl · Ticket: Error / High · Unit: URLs
- Needs: crawl, probes
- Evidence owners: `response-status-and-redirect-history`
- Note: Qualification: recheck_required.
- Original: Do any crawlable or search-indexed URLs persistently return 500-level Internal Server Errors indicating unhandled application failures?

### Q91 · Internal link quality

**Does any internal link have empty anchor text, with no alt text on a linked image either?**

- Issue if: At least one internal <a> has empty or whitespace-only text and no image with non-empty alt.
- Why it matters: An empty link gives Google no anchor text and screen readers nothing to announce. It is usually an icon or logo link without a label.
- Group: crawl · Ticket: Warning / Low · Unit: links
- Needs: crawl
- Evidence owners: `image-markup`, new detector `empty-anchors`
- Original: Do internal hyperlinks contain empty anchor text, whitespace-only content, or missing alt attributes on linked images?

### Q92 · Security & forms

**Does any form submit to an http:// URL?**

- Issue if: At least one <form action> resolves to an http:// URL.
- Why it matters: Browsers warn users on insecure form submissions, and the data goes over an unencrypted connection. This is a security issue before it is an SEO one.
- Group: crawl · Ticket: Warning / Medium · Unit: forms
- Needs: stored-html
- Evidence owners: `nonproduction-https`, new detector `insecure-form-actions`
- Original: Do interactive HTML <form action="..."> attributes submit exclusively to secure https:// URLs to avoid browser mixed-content warnings?

### Q102 · Preview and draft exposure

**Does any preview, draft, admin or CMS utility URL violate its approved access or indexing policy?**

- Issue if: An unauthenticated request exposes protected content, or an intentionally public utility URL lacks its required noindex or crawl control; a public noindex directive is not readable because robots.txt blocks the URL.
- Why it matters: Public preview and utility URLs can expose unfinished content, create duplicate pages and introduce low-value or sensitive crawl paths.
- Group: crawl+profile · Ticket: Warning / High · Unit: URLs
- Needs: crawl, probes, robots, site-profile
- Evidence owners: `robots-controls`, `indexability-segmentation`, new detector `utility-path-access-policy`
- Note: Planned: no dedicated answerer yet. Needs approved protected/public path classes and scoped unauthenticated probes. A login page returning 200 is not by itself evidence of exposed protected content; crawl-only absence is not proof of protection.
- Original: Are preview, draft, admin and CMS utility paths protected from public access and governed correctly for crawling and indexing?

### Q103 · Redirect integrity

**Does any internal, sitemap or approved legacy URL violate its direct-destination or permanent-redirect policy?**

- Issue if: An internal or sitemap URL redirects; or an approved legacy redirect loops, takes more than one hop, uses a temporary response where a permanent move is required, or fails to reach its approved canonical destination.
- Why it matters: Redirect chains and loops waste crawl capacity, delay users and weaken consolidation signals to the intended canonical URL.
- Group: crawl+profile · Ticket: Warning / Medium · Unit: URLs
- Needs: crawl, sitemaps, probes, site-profile
- Evidence owners: `response-status-and-redirect-history`, `internal-link-targets`, new detector `redirect-policy-integrity`
- Note: Planned: no dedicated answerer yet. Needs full redirect histories, internal and sitemap membership, and approved legacy targets. Temporary redirects are not inherently defects; evaluate the approved intent. Missing history or incomplete populations remain Pending or qualified.
- Original: Do internal, sitemap and priority legacy URLs avoid redirect chains, loops and temporary redirects where a permanent destination is intended?

### Q104 · Search-result host hygiene

**Does Google Search show any unapproved alternate-host URL in the reviewed performance data or search results?**

- Issue if: A dated GSC domain-property export records impressions for an unapproved hostname during the agreed review period, or a documented SERP check finds an unapproved alternate-host URL.
- Why it matters: Alternate-host results can divide visibility, expose non-production content and send users to the wrong version of the site even when the production host is healthy.
- Group: external · Ticket: Warning / Medium · Unit: URLs
- Needs: gsc, external-api
- Evidence owners: outside crawler_cli
- Note: Manual review required: segment GSC page URLs by hostname and record the date range, permitted hosts, queries, location and review date for SERP checks. No impressions or site: matches does not prove universal absence from Google's index. Always Pending in the automatic runner; no automatic ticket.
- Original: Do Google search results rank staging, development, cache, preview or other alternate-host versions instead of the intended production URLs?

## Performance

### Q29 · Performance

**Do lab LCP, CLS or INP exceed Google's 'good' thresholds on a key template, or do in-content images lack width and height?**

- Issue if: A template's p75 lab LCP > 2.5 s, CLS > 0.1 or INP > 200 ms, or over 20% of its images lack dimensions.
- Why it matters: Core Web Vitals are part of page experience. Lab results show likely causes; field data (CrUX) decides whether it actually affects the site in search.
- Group: heuristic · Ticket: Warning / Medium · Unit: templates
- Needs: render
- Evidence owners: `performance-distribution`, `image-markup`, `image-resource-delivery`
- Note: Lab only; confirm with CrUX or Search Console Core Web Vitals before ticketing.
- Original: Do images and Core Web Vitals hold up?

### Q63 · Server performance & security

**Is the Strict-Transport-Security header missing or weak, the domain absent from the HSTS preload list, or OCSP stapling off?**

- Issue if: HSTS max-age < 31536000 or missing includeSubDomains/preload, the preload list status is not 'preloaded', or the TLS handshake has no stapled OCSP response.
- Why it matters: HSTS preload removes the first http-to-https redirect and prevents downgrade attacks; stapling shortens the TLS handshake. The search effect is small.
- Group: crawl · Ticket: Improvement / Low · Unit: hosts
- Needs: probes, external-api
- Evidence owners: new detector `hsts-ocsp`
- Sheet said answerable: No (changed)
- Original: Is the domain submitted to the HSTS preload list and configured with OCSP stapling to minimize initial SSL handshake latency and TTFB?

### Q64 · Resource hints & performance

**Does a page load render-critical fonts, CSS or its LCP image from a third-party origin without a preconnect hint?**

- Issue if: A key template requests a render-blocking or LCP resource from another origin with no matching <link rel=preconnect>.
- Why it matters: Each new origin costs DNS, TCP and TLS round trips before the first byte. Preconnecting to the origins that block rendering shortens LCP.
- Group: best-practice · Ticket: Improvement / Low · Unit: templates
- Needs: render, stored-html
- Evidence owners: `critical-resource-impact`, new detector `resource-hints`
- Original: Are critical third-party resource domains preconnected (<link rel="preconnect">) with crossorigin attributes to accelerate connection setup?

### Q65 · Resource loading & priority

**Does any page preload an analytics or tag-manager script?**

- Issue if: At least one <link rel=preload> points to a known analytics/tag-manager URL.
- Why it matters: Preloading a tracking script gives it the same priority as the hero image and CSS, which delays what the user sees first.
- Group: best-practice · Ticket: Improvement / Low · Unit: templates
- Needs: stored-html
- Evidence owners: new detector `tracking-preloads`
- Original: Are non-critical tracking scripts (e.g. Google Tag Manager, analytics) avoided in <link rel="preload"> to prevent bandwidth contention with Above-The-Fold assets?

### Q66 · Image performance

**Are content images served as JPEG or PNG instead of WebP or AVIF?**

- Issue if: Over 20% of fetched in-content raster images have a JPEG/PNG content type.
- Why it matters: WebP and AVIF are usually 25–50% smaller, which speeds up LCP on image-heavy templates.
- Group: best-practice · Ticket: Improvement / Low · Unit: images
- Needs: crawl, render
- Evidence owners: `image-resource-delivery`
- Note: Compression quality is not measured.
- Original: Are all raster images converted and served in modern next-gen formats (WebP and AVIF) with appropriate compression quality?

### Q67 · Font performance & CWV

**Does any @font-face rule lack font-display swap/optional, or does a page preload more than four font files?**

- Issue if: At least one first-party @font-face has no font-display (or 'block'), or a page has > 4 font preloads.
- Why it matters: Without font-display, text stays invisible until the font loads, which delays the first render and can make LCP late.
- Group: best-practice · Ticket: Improvement / Low · Unit: templates
- Needs: crawl, stored-html
- Evidence owners: new detector `font-loading`
- Original: Are web fonts configured with font-display: swap and restricted to strictly needed Above-The-Fold weights to prevent FOIT text render delays?

### Q68 · Core Web Vitals (LCP & CLS)

**Is the LCP image lazy-loaded, missing fetchpriority=high, or missing width and height?**

- Issue if: On a key template the rendered LCP element is an image with loading=lazy, no fetchpriority=high, or no dimensions.
- Why it matters: A lazy-loaded or low-priority hero image is the most common cause of slow LCP, and missing dimensions cause layout shift.
- Group: heuristic · Ticket: Warning / Medium · Unit: templates
- Needs: render
- Evidence owners: `critical-resource-impact`, `image-markup`, new detector `lcp-image-attributes`
- Note: Identifying the LCP element needs a render with performance tracing.
- Original: Are mobile-responsive hero images delivered with fetchpriority="high", explicit width/height or aspect-ratio to optimize LCP and prevent CLS?

### Q69 · Resource loading & LCP

**Is the LCP element on any key template a CSS background image?**

- Issue if: On a key template the rendered LCP element's image comes from a CSS background-image.
- Why it matters: Browsers find CSS background images late and cannot prioritise them, and they are not indexed as images.
- Group: heuristic · Ticket: Improvement / Low · Unit: templates
- Needs: render
- Evidence owners: `critical-resource-impact`, new detector `lcp-background-image`
- Original: Are critical Above-The-Fold visual assets delivered via responsive <img> or <picture> elements rather than CSS background-image:url() rules?

### Q86 · Critical rendering path

**Does the <head> contain more than three render-blocking stylesheets or any synchronous external script?**

- Issue if: A key template has > 3 blocking stylesheets or ≥ 1 external <script> in the head without async, defer or type=module.
- Why it matters: Everything that blocks rendering delays first paint for users and adds work for Google's renderer.
- Group: best-practice · Ticket: Improvement / Medium · Unit: templates
- Needs: stored-html
- Evidence owners: `critical-resource-impact`, new detector `render-blocking-head`
- Original: Do render-blocking CSS stylesheets or synchronous JavaScript bundles delay first paint and impede crawler rendering queues?

## AI

### Q96 · AI crawler governance

**Do the robots.txt rules for AI crawlers differ from the site's declared AI policy?**

- Issue if: For any of GPTBot, OAI-SearchBot, ClaudeBot, Claude-SearchBot, PerplexityBot, Google-Extended or CCBot, the effective robots.txt verdict differs from the profile's ai_crawler_policy.
- Why it matters: AI search assistants send traffic only to sites they can crawl. Blocking a search agent by accident removes the site from those answers; allowing a training agent the site meant to block cannot be undone later.
- Group: crawl+profile · Ticket: Warning / Medium · Unit: user agents
- Needs: robots, site-profile
- Evidence owners: `robots-controls`, new detector `ai-crawler-policy`
- Site profile keys: `ai_crawler_policy`
- Sheet said answerable: No (changed)
- Note: Without a declared policy the per-agent inventory is reported as Needs validation. /llms.txt presence is reported but is not a defect: no major search engine has confirmed using it.
- Original: Does the site define explicit crawl and training permissions for AI search crawlers (e.g. GPTBot, ClaudeBot, PerplexityBot) in robots.txt and provide an /llms.txt file?
