# Model tickets by question

These findings recur across the source audits, written here in house style. Start from them,
then replace the counts, paths and examples with the site's own. Class · Priority is the
default; adjust it with the priority rules in `field-guide.md`.

| Questions | Label | Suggested Solution (short) | Acceptance Criteria (short) | Class · Priority |
|---|---|---|---|---|
| Q1, Q70 | robots.txt allows internal search and feed URLs | Disallow search and feed paths, e.g. `Disallow: /*?s=`, `Disallow: /*/search/`, `Disallow: /*/feed/`. | robots.txt blocks the listed search and feed patterns. Content pages remain crawlable. | Issue · High |
| Q3, Q93 | Sitemaps include missing and excluded pages | Remove failed and noindex URLs. Generate entries only for 200, canonical, indexable pages. | Sitemap URLs return 200, are canonical and are intended for indexing. | Issue · Medium |
| Q4 | Indexable language pages are absent from XML sitemaps | Add every canonical page intended for search to the relevant sitemap. | Each canonical, indexable page appears once in the relevant sitemap. | Issue · Medium |
| Q8 | Localised pages declare a generic html lang | Set html lang to the target locale, e.g. `en-CA`, matching hreflang. | html lang matches the hreflang locale on every localised page. | Issue · Medium |
| Q9, Q20 | Noindex pages publish hreflang alternates | Remove hreflang from pages excluded from search, or remove noindex where they should rank. | No hreflang cluster contains a noindex page. | Issue · Medium |
| Q2, Q7 | www redirects send language URLs to English pages | Preserve the full path, language prefix and required parameters when redirecting host variants. | Each tested variant reaches the same-language canonical page in one permanent redirect. | Issue · Low |
| Q6, Q42 | Invalid paths return a successful page | Return 404 for invalid routes while preserving legitimate pages. | Invalid URLs return 404. Valid routes return the intended page. | Issue · Low |
| Q22, Q39 | Articles link to missing pages | Update each link to the working equivalent, or remove it. Redirect genuinely moved pages. | Every listed link reaches relevant working content in one hop. | Issue · Medium |
| Q72 | Internal links omit the trailing slash and redirect | Update links to the trailing-slash canonical form. | A crawl finds no internal link to a redirecting non-slash URL. | Issue · Medium |
| Q19 | Backlinked URLs return 404 | Redirect each to an equivalent working page, restore content, or keep an intentional 404/410. | Each approved redirect is a single permanent hop to a relevant, indexable 200 page. | Issue · Medium |
| Q24, Q38 | Modal and demo controls create unnecessary URL variants | Replace state-only links with JavaScript event handlers on accessible buttons. | State-only controls no longer generate navigable URLs. Keyboard operation still works. | Issue · Medium |
| Q34 | Expired pages remain indexable | Add `unavailable_after` at publish time, or noindex on expiry. Consolidate expired items onto one archive page. | Expired pages carry noindex or `unavailable_after` and are absent from sitemaps. | Issue · High |
| Q33, Q37 | User profiles host spam and outbound spam links | Remove spam profiles and return 410. Noindex profiles until they publish content. Restrict or nofollow user links. | No spam profile returns 200. Empty profiles are noindex and absent from sitemaps. | Error · High |
| Q27, Q77 | Staging or cache host is crawlable and indexed | Require authentication on staging. Block or noindex cache and image-resizer hosts, and request removal in Search Console. | The host is not publicly reachable, or it returns noindex on every page. | Error · High |
| Q75 | Affiliate links are crawlable | Route affiliate links through a /go/ path that robots.txt disallows, and mark them rel="sponsored". | No raw affiliate URL appears in page source. /go/ is disallowed. | Issue · High |
| Q71, Q80 | Key pages have no canonical, or a relative one | Output an absolute self-referencing canonical on every public page. | Every public 200 page declares an absolute canonical URL. | Issue · Low |
| Q73 | Retired pages canonicalise to the homepage | Choose per group: redirect, return 410, or make self-canonical and reindex. Remove internal links to retired pages. | No page canonicalises to the homepage unless it duplicates it. | Issue · High |
| Q15 | Templates use an unclear heading hierarchy | Use one H1 for the primary subject and step down one level per section. | Affected templates expose one H1 and a logical heading sequence. | Improvement · Low |
| Q10, Q11 | Language pages reuse English metadata | Localise titles and descriptions, keeping proper names. Replace default fallback descriptions. | Titles and descriptions suit the page language and purpose. | Error · Low |
| Q16, Q84 | Pages contain conflicting structured data | Remove the duplicate output. Align URL, language and entity with the current canonical page. | Each page has one consistent entity using the canonical URL. | Issue · Low |
| Q17 | Social previews use generic artwork | Use page-specific images and URL-safe filenames. | Representative previews show the right image, title and description. | Improvement · Low |
| Q40, Q44 | Priority categories are missing from the main navigation | Add crawlable `<a href>` links to priority hubs in the header nav, and mirror them in the footer. | Every priority hub is linked from the main nav on all templates. | Improvement · High |
| Q43 | Sitewide footer links out to unrelated network sites | Remove footer links to properties that aren't relevant to users. | The footer links only to relevant internal and partner pages. | Improvement · High |
| Q51–Q56 | Templates lack semantic HTML5 elements | Use `<main>`, `<header>`, `<table>` for toplists, `<details>` for FAQs, `<aside>` for disclaimers and `<time>` for dates. | The named templates use the listed elements. | Improvement · Low |
| Q63–Q69 | Page speed: <specific fault> | Name the single change, e.g. add preconnect for third-party origins, or stop preloading analytics. | The change is live on the named templates. | Improvement · Low |

## Full Rainbet examples (the reference standard)

**Casino hub is excluded from search** · Error · Medium
- Description: /casino is noindex despite being a self-canonical page with distinct primary content, title and H1 from the homepage. It receives 8,209 internal links through sitewide navigation.
- Solution: Make /casino indexable if it is intended to be the organic casino hub. If it is intentionally excluded, update sitewide navigation to the intended indexable casino destination.
- Criteria: The selected primary casino hub is indexable, self-canonical and suitable for search. Sitewide navigation points to that page.
- Replicate: Open /casino and compare its robots directive, canonical URL, title and H1 with the homepage.
- Notes: See Search-excluded pages

**Blog articles link to missing slot guides** · Issue · Medium
- Description: 1,262 links from 120 English articles point to 69 missing guide URLs. Examples include /casino/slots/rtp and /casino/slots/best-theme.
- Solution: Update each article link to the relevant working guide, or remove the link where no replacement exists. Add permanent redirects for genuinely equivalent moved guides.
- Criteria: Every listed article link reaches relevant working content. Any redirect has one hop and a valid destination.
- Replicate: Open /blog/3d-games and follow its link to /casino/slots/best-theme. Use the inventory for exact article, anchor and location.
- Notes: See Missing guide links

**Invalid sportsbook paths return a successful page** · Issue · Low
- Description: Nonexistent sportsbook paths, including /sportsbook/zzqx-made-up-9731, return HTTP 200 with the sportsbook hub as canonical.
- Solution: Return 404 for invalid sportsbook routes while preserving legitimate sport, league and event pages.
- Criteria: Invalid sportsbook URLs return 404. Valid routes remain functional and return the intended page.
- Replicate: Open the listed invalid sportsbook URL and inspect its HTTP status and canonical.
- Notes: See Sportsbook routes

## Cleaning up an older-style ticket

Before (esports.gg):

| Label | Description | Acceptance Criteria |
|---|---|---|
| Links without trailing slashes 308 | A number of links are being pointed to non-trailing slash URL versions (see status308_outlinks) | No links to these versions are discovereable via crawl |

After:

| Column | Text |
|---|---|
| Label | Internal links omit the trailing slash and redirect |
| Description | 5,576 internal links point to URLs without a trailing slash, which return a 308 redirect. Examples include author links on /staff/. |
| Suggested Solution | Update internal links to the trailing-slash canonical URL. Fix the templates that generate author links first. |
| Acceptance Criteria | A crawl finds no internal link to a redirecting non-slash URL. |
| Ticket Classification | Issue |
| Priority | Medium |
| How to Replicate | Open /staff/ and inspect the author links. Request one and confirm the 308. |
| Notes / Documentation | See Trailing-slash redirects |

What changed:
- The label names the fault.
- "A number of" became a count and a place.
- The criteria can now be checked.
- The evidence tab has a plain-English name, and the typo is gone.
