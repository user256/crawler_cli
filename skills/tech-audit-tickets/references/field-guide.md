# Technical SEO audit field guide

How to turn audit findings into client-ready tickets in the
[Technical SEO Audit template](https://docs.google.com/spreadsheets/d/1JyYbeoXhBq3Y_heUsUXRaZHOmNPSTeNeUhRodWcZ53o/edit?gid=0#gid=0).
Every ticket should read as if one person wrote it: short, factual, and open to
only one reading.

Shared copy (for comments and edits by people):
https://claude.ai/code/artifact/3ff8c8a1-e25d-4b6f-abf5-50e1f86ea0f1

## The template

| Tab | What happens there |
|---|---|
| Questions | 96 audit questions (Q1–Q96) in themes: Crawlability, Indexability, Crawl Budget, Maintenance, Performance, AI. Each says whether crawler_cli answers it or it needs another source. |
| Tickets | Row 2 is the banner, row 3 is `Count of tickets: N`, row 4 is `Audit performed by: <name>`, and row 5 is the header. Column A holds the numbers `1.`, `2.` and so on; columns B–I hold the eight ticket fields. |
| Config | Dropdown values. Priority: High, Medium, Low. Ticket Classification: Error, Issue, Warning, Improvement. Question status: Healthy, Issue, Needs validation, Pending. |

## Source audits (the style is drawn from these)

| Audit | Tab | What to take from it |
|---|---|---|
| [Rainbet.com](https://docs.google.com/spreadsheets/d/1Y6aPPDfspo_lI_Fb3D35YGdhV1mzY1Ru1rIm215-BV4/edit?gid=1270270714) | Tickets + 17 evidence tabs | **The reference standard.** Counted descriptions, one replication path, a numbered evidence tab per ticket. |
| [Raffall.com](https://docs.google.com/spreadsheets/u/1/d/1kNHLvhKpqRNbb0CQe4S-FozzZ0hj7QrDUapQYA1UrGw/edit?gid=0) | Audit | Risk framing for spam, staging and lifecycle pages. Its criteria are bullet lists. |
| [Dotesports Improvements](https://docs.google.com/spreadsheets/d/1H0CwSQFvfZvKnbH8fBSvxSm9KQhkHez6pD7h2p97WKc/edit?gid=577726282) | Improvements | Wording for Improvement tickets: navigation, templates, HTML5, page speed. |
| [esports.gg](https://docs.google.com/spreadsheets/d/1wiY3X5HqE6O0fqfVMsvNBHO2eTXWmOlIpJzvjDmQXiQ/edit?gid=1657317114) | TasksIssues + 14 evidence tabs | Options-style solutions (redirect / 410 / reindex) and exact robots.txt rules. Its style is looser; rewrite it, don't copy it. |

When two sources disagree, follow Rainbet.

## Workflow

1. Copy the template and rename it `<Domain> – Technical SEO Audit`. Put the same
   title in the banner cell (row 2), replacing "This is a template…".
2. Set a status on every question: Healthy, Issue, Needs validation or Pending.
   A saved-crawl finding that hasn't been rechecked live is Needs validation.
   Questions marked External Tool or GSC stay Pending until that source is supplied.
3. Build one evidence tab per problem before writing its ticket.
4. Group questions that one fix resolves into one ticket. For example, Rainbet's
   "Blog noindex, sitemap and hreflang conflicts" covers Q3, Q9 and Q20. Split a
   finding into separate tickets when the parts need different teams or fixes.
5. Write one ticket per row, numbered in order. Sort by priority (High, then Medium,
   then Low), and within each priority by impact.
6. Set `Count of tickets: N` and `Audit performed by: <name>`.
7. Run the checklist at the end of this file.

## Columns

| Column | Answers | Length | Rule |
|---|---|---|---|
| Label | What is wrong? | 5–12 words | A plain statement of the problem, in sentence case. Not an instruction and not a topic. |
| Description | How big is it, and where? | 1–4 sentences | Counts, the largest page groups and one named example. Add a "why" sentence only when a developer wouldn't see the harm. |
| Suggested Solution | What should change? | 1–4 sentences | Starts with an imperative verb. Says what to keep as well as what to change. If a business decision is needed, give both routes. |
| Acceptance Criteria | How do we know it's done? | 1–3 sentences | An end state someone else can check. Present tense, no "should". |
| Ticket Classification | What kind of problem? | dropdown | Error / Issue / Warning / Improvement |
| Priority | How soon? | dropdown | High / Medium / Low |
| How to Replicate | Where can I see it? | 1–2 sentences | One concrete URL or file, and what to look at. |
| Notes / Documentation | Where is the full list? | short | `See <evidence tab>`, plus a Google documentation link if the fix depends on a lesser-known directive. |

### Label
- Good: "Casino hub is excluded from search", "Invalid sportsbook paths return a successful page",
  "www redirects send language URLs to English pages".
- Bad: "robots.txt Improvements" (names no fault), "Fix redirecting H2 hyperlinks"
  (an instruction, not a problem), "Tag noindexation" (a topic, not a finding).

### Description
Give the count first, then the largest groups, then one example. Count in the unit the fix works on:
links, pages, URLs, sitemaps or blocks.

> 1,262 links from 120 English articles point to 69 missing guide URLs. Examples include /casino/slots/rtp and /casino/slots/best-theme.

If a ticket covers a second, related fault, give it its own sentence starting with "Separately," or "A further".

> 3,895 of 8,071 indexable slot pages use the same generic Open Graph image instead of game artwork. A further 1,931 Open Graph image URLs contain unencoded spaces.

A "why" sentence states one fact: "Hreflang should only be emitted for pages intended to appear in search."
Don't threaten penalties or "silent" ranking loss unless there is evidence for it.

### Suggested Solution
Start with a verb: Remove, Replace, Return, Add, Localise, Choose, Preserve.

> Return 404 for invalid sportsbook routes while preserving legitimate sport, league and event pages.

If the fix depends on a business decision, write it as "If …, … If …, …" and let the client choose:

> If articles should attract organic traffic, remove noindex and publish only working, equivalent language alternates. If exclusion is intentional, remove the articles from sitemaps and remove their hreflang annotations.

If there are three or more routes, number them: 1) remove and redirect, 2) remove and return 410,
3) make self-canonical and reindex. Give exact code or rules wherever a developer would otherwise
have to guess, for example `Disallow: /*?s=`.

### Acceptance Criteria
> Invalid sportsbook URLs return 404. Valid routes remain functional and return the intended page.

If the solution offers routes, the criteria must accept any of them:

> Each article is either indexable with valid sitemap and language signals, or intentionally excluded and absent from those outputs.

Never write "Implement one of the suggested solutions". Don't use criteria that need Search Console data
that won't exist until after release, or vague outcomes such as "improved internal link metrics".
Never leave the cell empty.

### How to Replicate
Start with a verb: Open, Request, Compare or Inspect.

> Request https://www.rainbet.com/fr/casino/slots and inspect the destination. Compare it with the intended /fr/casino/slots page.

If the finding comes from a third-party export, name the tool and the report: "Check Ahrefs most linked pages".

### Notes / Documentation
Give the evidence tab's exact name: "See Missing guide links". Put release warnings here, for example
"Remove the staging block before pushing to production."

## House style

**Voice**
- Describe what the site does, not what "we" think: "/casino is noindex", not "we noticed /casino seems noindexed".
- Keep audit shorthand out: no "F&F audit", "SF crawl" or column names such as `live_status`.
- Name page groups in plain words: slot pages, blog articles, language pages, promotion pages.
- One idea per sentence; aim for under 20 words.
- Never write "should probably", "may want to" or "it is recommended that". Use the imperative in solutions
  and the present tense in criteria.

**Numbers**
- Write digits with thousands separators: 8,209.
- Count in the unit the fix works on.
- When the share matters, give the part and the whole: "3,895 of 8,071 indexable slot pages",
  "76,263 of 472,136 internal link instances (16.2%)".
- If a count may be incomplete, say so: "At least 1,326", "about 825". Never present a partial count as a site total.

**URLs and code**
- Use root-relative paths (/blog/3d-games) for the main host, and full URLs for www, http,
  subdomains and other sites.
- Write directives exactly as they appear: noindex, rel="sponsored", `<html lang="en-CA">`, `Disallow: /*/feed/`.
- Put at most two or three example URLs in a cell. The rest go in the evidence tab.

**Spelling and terms**
- Use UK English: localise, canonicalise, prioritise, organisation.
- Use these terms consistently: indexable, noindex, canonical, self-canonical, hreflang, XML sitemap,
  Open Graph, structured data, permanent redirect (or 301/308 when the code matters), 404/410.
- Write "excluded from search" or "noindex" rather than "deindexed", unless Google's index status was checked.
- Proofread. The older audits had slips such as "penalisastion", "liklihood" and "paramater".

## Classification and priority

Set these two independently: an Error can be Low priority, and an Improvement can be High.

| Classification | Use when | Examples |
|---|---|---|
| Error | The site does the opposite of what it plainly intends, on pages that matter. | Casino hub noindex despite being the sitewide casino link; language pages carry English titles |
| Issue | A technical defect with a measurable cost. Most tickets are Issues. | Links to missing guides; 404s in sitemaps; invalid paths return 200 |
| Warning | A risk not yet confirmed as a defect, or a finding still awaiting a live check or client confirmation. *(Assumed meaning: none of the source audits used Warning.)* | Staging host reachable but not yet seen in Google; saved-crawl 500s not rechecked |
| Improvement | The site works, but a change would help. | Provider filter landing pages; heading hierarchy; social previews; HTML5; preconnect |

| Priority | Default for | Raise when | Lower when |
|---|---|---|---|
| High | Spam or exploit pages; staging, cache or preview hosts in the index; crawlable affiliate links; wrong robots.txt blocks or exposure; key hubs missing from the nav | — | Confined to pages already excluded from search |
| Medium | Backlinked 404s; sitemap errors; hreflang conflicts; broken internal links; state-only URL variants; missing canonicals on key pages | ≥ 20% of the page group is affected; the homepage, main nav, sitemap URLs or backlinked pages are hit | All affected URLs are non-indexable or due for removal |
| Low | Metadata, headings, structured data, social previews, relative canonicals, HSTS, speed tweaks | A reusable template repeats the fault on every page it serves | — |

Don't raise a ticket above Medium on a partial crawl or an unconfirmed count alone.

## Evidence tabs

- Give each ticket one tab, named after the problem in plain words: "Backlinked 404s",
  "Missing guide links". Don't use export names such as `status308_outlinks`.
- Row 1: `Evidence NN: <title>`, numbered in ticket order. Row 2: a one-sentence summary with
  the count (preferred). Row 3: column headers. Row 4 onwards: one item per row, largest impact first.
- Use 3–6 readable columns, for example `Requested URL | Redirect | Destination`. For small findings,
  use `Item | Observed state | Required action`.
- For long lists, show the top rows and link the full export. Never paste a 60-column crawler export.
- If the data comes from a saved crawl, add a live-status column and the date checked. Keep rows that
  couldn't be rechecked, marked as unchecked, rather than dropping them.

## Checklist

- [ ] The banner shows the site name, and "This is a template" is gone.
- [ ] `Count of tickets` matches the number of rows, and `Audit performed by` is filled in (not John Doe).
- [ ] All eight columns are filled on every ticket, and Classification and Priority use the dropdown values.
- [ ] Each Label states a problem, not a fix or a topic.
- [ ] Each Description has a count, the page group and one example.
- [ ] Each Acceptance Criteria cell gives a checkable end state, never "implement one of the solutions".
- [ ] Each How to Replicate gives one URL or file that shows the problem today.
- [ ] Each Notes cell names an evidence tab that exists, spelt exactly.
- [ ] Saved-crawl findings have been rechecked live, or are classed as Warning.
- [ ] Tickets are ordered High → Medium → Low, then by impact.
- [ ] Every question has a status.
- [ ] Spelling is UK English and clean.
