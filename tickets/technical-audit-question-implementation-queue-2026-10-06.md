# Technical-audit question implementation queue — 2026-10-06

## Purpose

One local implementation ticket exists for every Questions-tab row. Each ticket
uses the deterministic question registry as its source of truth: it preserves
the question's Yes = problem polarity, evidence contract, coverage rules and
required inputs. The ticket range refines the broad detector batches
[ticket 264](./ticket-264-question-detectors-stored-html.md),
[ticket 265](./ticket-265-question-detectors-site-profile.md) and
[ticket 266](./ticket-266-question-detectors-render-probe-external.md);
those tickets remain useful delivery waves, while this queue is the
question-level work register.

"Implemented locally" means an explicit runner answerer exists today. It does
not claim that every site has supplied the required input or that a client
finding has been validated. External questions remain evidence-import/manual
workflows and must not be presented as crawler-only checks.

Priority follows the registry: High = P1, Medium = P2, Low = P3. Run-gate
questions (Q26, Q81) have no registry priority and are P2. Statuses:

- **implemented locally; retain regression coverage** — answerer and tests exist.
- **implemented locally; regression tests missing** — answerer exists, but no
  test references the question ID (Q23, Q30, Q32).
- **implemented locally (partial); scope gaps remain** — the answerer's
  `scope_note` admits untested rule branches (Q21, Q22, Q39, Q94).
- **proposed** — no answerer yet. Q18, Q31 and Q50 must move from `external`
  to `supplied-input` first, because the runner returns Pending for external
  questions before it looks up an answerer.
- **proposed (manual workflow)** — Q104 stays Pending in the runner, per its
  registry note.

Detector `date-consistency` is built once by ticket 314 (Q56); ticket 318
(Q60) depends on it.

## Delivery streams

The queue is divided between three agents by implementation seam. See the
[stream plan](./technical-audit-question-streams-2026-10-06.md):

- [Stream A — crawl and HTTP evidence](./technical-audit-stream-a-crawl-http-2026-10-06.md): 38 tickets.
- [Stream B — page indexability](./technical-audit-stream-b-page-indexability-2026-10-06.md): 35 tickets.
- [Stream C — render, probes and supplied evidence](./technical-audit-stream-c-render-probe-evidence-2026-10-06.md): 31 tickets.

## Tickets

| Ticket | Question | Area | Priority | Status |
|---|---|---|---|---|
| [267](./ticket-267-technical-audit-q1-robots-txt.md) | Q1 | Crawlability / Robots.txt | P1 | proposed |
| [268](./ticket-268-technical-audit-q97-robots-txt.md) | Q97 | Crawlability / Robots.txt | P2 | proposed |
| [269](./ticket-269-technical-audit-q3-sitemaps.md) | Q3 | Crawlability / Sitemaps | P1 | proposed |
| [270](./ticket-270-technical-audit-q4-sitemaps.md) | Q4 | Crawlability / Sitemaps | P2 | proposed |
| [271](./ticket-271-technical-audit-q13-internal-linking.md) | Q13 | Crawlability / Internal linking | P1 | implemented locally; retain regression coverage |
| [272](./ticket-272-technical-audit-q14-internal-linking.md) | Q14 | Crawlability / Internal linking | P3 | implemented locally; retain regression coverage |
| [273](./ticket-273-technical-audit-q18-crawl-access.md) | Q18 | Crawlability / Crawl access | P1 | implemented locally; supplied input (google-render-inspection) |
| [274](./ticket-274-technical-audit-q23-internal-linking.md) | Q23 | Crawlability / Internal linking | P1 | implemented locally; regression tests missing |
| [275](./ticket-275-technical-audit-q31-crawl-access.md) | Q31 | Crawlability / Crawl access | P1 | implemented locally; supplied input (verified-google-fetch) |
| [276](./ticket-276-technical-audit-q38-crawl-access-js.md) | Q38 | Crawlability / Crawl access & JS | P2 | answerer implemented; collector missing |
| [277](./ticket-277-technical-audit-q40-information-architecture.md) | Q40 | Crawlability / Information architecture | P1 | proposed |
| [278](./ticket-278-technical-audit-q44-crawl-depth-discoverability.md) | Q44 | Crawlability / Crawl depth & discoverability | P2 | proposed |
| [279](./ticket-279-technical-audit-q45-international-internal-linking.md) | Q45 | Crawlability / International & internal linking | P3 | implemented locally; end-to-end from stored HTML |
| [280](./ticket-280-technical-audit-q46-dom-completeness-rendering.md) | Q46 | Crawlability / DOM completeness & rendering | P2 | answerer implemented; collector missing |
| [281](./ticket-281-technical-audit-q48-information-architecture.md) | Q48 | Crawlability / Information architecture | P2 | proposed |
| [282](./ticket-282-technical-audit-q49-internal-linking-clusters.md) | Q49 | Crawlability / Internal linking & clusters | P2 | proposed |
| [283](./ticket-283-technical-audit-q75-commercial-links-compliance.md) | Q75 | Crawlability / Commercial links & compliance | P1 | proposed |
| [284](./ticket-284-technical-audit-q82-crawl-discovery-provenance.md) | Q82 | Crawlability / Crawl discovery provenance | P2 | proposed |
| [285](./ticket-285-technical-audit-q90-access-log-bot-verification.md) | Q90 | Crawlability / Access-log bot verification | P2 | proposed |
| [286](./ticket-286-technical-audit-q93-xml-sitemap-architecture.md) | Q93 | Crawlability / XML sitemap architecture | P1 | proposed |
| [287](./ticket-287-technical-audit-q95-mobile-interstitial-compliance.md) | Q95 | Crawlability / Mobile & interstitial compliance | P2 | answerer implemented; collector missing |
| [288](./ticket-288-technical-audit-q98-robots-txt.md) | Q98 | Crawlability / Robots.txt | P2 | proposed |
| [289](./ticket-289-technical-audit-q99-directory-and-file-exposure.md) | Q99 | Crawlability / Directory and file exposure | P2 | proposed |
| [290](./ticket-290-technical-audit-q100-document-discovery.md) | Q100 | Crawlability / Document discovery | P2 | proposed |
| [291](./ticket-291-technical-audit-q8-international.md) | Q8 | Indexability / International | P2 | implemented locally (Stream B); QA-fixed, not merged |
| [292](./ticket-292-technical-audit-q9-international.md) | Q9 | Indexability / International | P1 | proposed |
| [293](./ticket-293-technical-audit-q10-on-page.md) | Q10 | Indexability / On-page | P1 | implemented locally (Stream B); QA-fixed, not merged |
| [294](./ticket-294-technical-audit-q11-on-page.md) | Q11 | Indexability / On-page | P2 | implemented locally (Stream B); QA-fixed, not merged |
| [295](./ticket-295-technical-audit-q12-on-page.md) | Q12 | Indexability / On-page | P1 | implemented locally (Stream B); QA-fixed, not merged |
| [296](./ticket-296-technical-audit-q15-on-page.md) | Q15 | Indexability / On-page | P3 | implemented locally (Stream B); QA-fixed, not merged |
| [297](./ticket-297-technical-audit-q16-structured-data.md) | Q16 | Indexability / Structured data | P2 | implemented locally; retain regression coverage |
| [298](./ticket-298-technical-audit-q17-social.md) | Q17 | Indexability / Social | P3 | proposed |
| [299](./ticket-299-technical-audit-q20-indexability.md) | Q20 | Indexability / Indexability | P1 | implemented locally (Stream B); QA-fixed, not merged |
| [300](./ticket-300-technical-audit-q21-content-quality.md) | Q21 | Indexability / Content quality | P2 | implemented locally (partial); scope gaps remain |
| [301](./ticket-301-technical-audit-q26-scope.md) | Q26 | Indexability / Scope | P2 | implemented locally; retain regression coverage |
| [302](./ticket-302-technical-audit-q30-search-evidence.md) | Q30 | Indexability / Search evidence | P1 | implemented locally; retain regression coverage |
| [303](./ticket-303-technical-audit-q32-international.md) | Q32 | Indexability / International | P2 | implemented locally; regression tests missing |
| [304](./ticket-304-technical-audit-q36-url-consolidation.md) | Q36 | Indexability / URL consolidation | P2 | implemented locally (Stream B); QA-fixed, not merged |
| [305](./ticket-305-technical-audit-q37-indexability-thin-content.md) | Q37 | Indexability / Indexability & thin content | P2 | implemented locally (Stream B); QA-fixed, not merged |
| [306](./ticket-306-technical-audit-q41-international-url-structure.md) | Q41 | Indexability / International & URL structure | P2 | implemented locally (Stream B); QA-fixed, not merged |
| [307](./ticket-307-technical-audit-q47-information-architecture-taxonomy.md) | Q47 | Indexability / Information architecture & taxonomy | P3 | proposed |
| [308](./ticket-308-technical-audit-q50-content-quality-topical-authority.md) | Q50 | Indexability / Content quality & topical authority | P2 | implemented locally; supplied input (competitor-topic-gap) |
| [309](./ticket-309-technical-audit-q51-semantic-html5.md) | Q51 | Indexability / Semantic HTML5 | P3 | implemented locally (Stream B); QA-fixed, not merged |
| [310](./ticket-310-technical-audit-q52-semantic-html5.md) | Q52 | Indexability / Semantic HTML5 | P3 | proposed |
| [311](./ticket-311-technical-audit-q53-semantic-html5.md) | Q53 | Indexability / Semantic HTML5 | P2 | proposed |
| [312](./ticket-312-technical-audit-q54-semantic-html5-images.md) | Q54 | Indexability / Semantic HTML5 & images | P3 | implemented locally (Stream B); QA-fixed, not merged |
| [313](./ticket-313-technical-audit-q55-semantic-html5.md) | Q55 | Indexability / Semantic HTML5 | P3 | proposed |
| [314](./ticket-314-technical-audit-q56-semantic-html5-schema.md) | Q56 | Indexability / Semantic HTML5 & schema | P3 | proposed |
| [315](./ticket-315-technical-audit-q57-serp-presentation-freshness.md) | Q57 | Indexability / SERP presentation & freshness | P2 | proposed |
| [316](./ticket-316-technical-audit-q58-on-page-serp-features.md) | Q58 | Indexability / On-page & SERP features | P3 | implemented locally (Stream B); QA-fixed, not merged |
| [317](./ticket-317-technical-audit-q59-e-e-a-t-author-entities.md) | Q59 | Indexability / E-E-A-T & author entities | P2 | proposed |
| [318](./ticket-318-technical-audit-q60-e-e-a-t-content-freshness.md) | Q60 | Indexability / E-E-A-T & content freshness | P3 | proposed |
| [319](./ticket-319-technical-audit-q61-content-formatting-e-e-a-t.md) | Q61 | Indexability / Content formatting & E-E-A-T | P3 | proposed |
| [320](./ticket-320-technical-audit-q62-anchor-text-optimization.md) | Q62 | Indexability / Anchor text optimization | P2 | proposed |
| [321](./ticket-321-technical-audit-q71-canonicalization.md) | Q71 | Indexability / Canonicalization | P2 | implemented locally (Stream B); QA-fixed, not merged |
| [322](./ticket-322-technical-audit-q73-canonicalization-error-handling.md) | Q73 | Indexability / Canonicalization & error handling | P1 | implemented locally (Stream B); QA-fixed, not merged |
| [323](./ticket-323-technical-audit-q78-taxonomy-indexability.md) | Q78 | Indexability / Taxonomy & indexability | P2 | implemented locally (Stream B); QA-fixed, not merged |
| [324](./ticket-324-technical-audit-q80-canonicalization-standards.md) | Q80 | Indexability / Canonicalization standards | P3 | implemented locally (Stream B); QA-fixed, not merged |
| [325](./ticket-325-technical-audit-q83-hreflang-sitemaps.md) | Q83 | Indexability / Hreflang & sitemaps | P3 | proposed |
| [326](./ticket-326-technical-audit-q84-structured-data-rich-results.md) | Q84 | Indexability / Structured data & rich results | P2 | proposed |
| [327](./ticket-327-technical-audit-q85-javascript-rendering-parity.md) | Q85 | Indexability / JavaScript & rendering parity | P1 | implemented locally; fed by compare-renders |
| [328](./ticket-328-technical-audit-q87-non-html-search-assets.md) | Q87 | Indexability / Non-HTML search assets | P3 | implemented locally (Stream B); QA-fixed, not merged |
| [329](./ticket-329-technical-audit-q94-header-vs-html-parity.md) | Q94 | Indexability / Header vs HTML parity | P1 | implemented locally (Stream B); QA-fixed, not merged |
| [330](./ticket-330-technical-audit-q24-crawl-waste.md) | Q24 | Crawl Budget / Crawl waste | P1 | proposed |
| [331](./ticket-331-technical-audit-q34-index-bloat-lifecycle.md) | Q34 | Crawl Budget / Index bloat & lifecycle | P2 | proposed |
| [332](./ticket-332-technical-audit-q35-crawl-efficiency.md) | Q35 | Crawl Budget / Crawl efficiency | P3 | answerer implemented; collector missing |
| [333](./ticket-333-technical-audit-q70-robots-txt-crawl-budget.md) | Q70 | Crawl Budget / Robots.txt & crawl budget | P2 | proposed |
| [334](./ticket-334-technical-audit-q81-crawl-safety-rate-limiting.md) | Q81 | Crawl Budget / Crawl safety & rate limiting | P2 | proposed |
| [335](./ticket-335-technical-audit-q88-server-response-crawl-budget.md) | Q88 | Crawl Budget / Server response & crawl budget | P2 | proposed |
| [336](./ticket-336-technical-audit-q89-conditional-http-caching.md) | Q89 | Crawl Budget / Conditional HTTP caching | P3 | proposed |
| [337](./ticket-337-technical-audit-q101-crawl-traps.md) | Q101 | Crawl Budget / Crawl traps | P2 | proposed |
| [338](./ticket-338-technical-audit-q2-url-variants.md) | Q2 | Maintenance (broken links etc.) / URL variants | P1 | proposed |
| [339](./ticket-339-technical-audit-q5-security.md) | Q5 | Maintenance (broken links etc.) / Security | P2 | implemented locally; end-to-end from stored HTML |
| [340](./ticket-340-technical-audit-q6-error-handling.md) | Q6 | Maintenance (broken links etc.) / Error handling | P1 | proposed |
| [341](./ticket-341-technical-audit-q7-url-variants.md) | Q7 | Maintenance (broken links etc.) / URL variants | P2 | proposed |
| [342](./ticket-342-technical-audit-q19-redirects.md) | Q19 | Maintenance (broken links etc.) / Redirects | P1 | proposed |
| [343](./ticket-343-technical-audit-q22-internal-linking.md) | Q22 | Maintenance (broken links etc.) / Internal linking | P2 | implemented locally (partial); scope gaps remain |
| [344](./ticket-344-technical-audit-q25-redirects.md) | Q25 | Maintenance (broken links etc.) / Redirects | P1 | answerer implemented; collector missing |
| [345](./ticket-345-technical-audit-q27-host-hygiene.md) | Q27 | Maintenance (broken links etc.) / Host hygiene | P1 | implemented locally; fed by exposure-inventory or host-probe records |
| [346](./ticket-346-technical-audit-q28-external-links.md) | Q28 | Maintenance (broken links etc.) / External links | P2 | answerer implemented; collector missing |
| [347](./ticket-347-technical-audit-q33-site-security-spam.md) | Q33 | Maintenance (broken links etc.) / Site security & spam | P1 | implemented locally; end-to-end from stored HTML (heuristic, Needs validation at most) |
| [348](./ticket-348-technical-audit-q39-internal-linking.md) | Q39 | Maintenance (broken links etc.) / Internal linking | P3 | implemented locally (partial); hand-off to Stream A |
| [349](./ticket-349-technical-audit-q42-status-codes-errors.md) | Q42 | Maintenance (broken links etc.) / Status codes & errors | P1 | proposed |
| [350](./ticket-350-technical-audit-q43-link-equity-architecture.md) | Q43 | Maintenance (broken links etc.) / Link equity & architecture | P3 | implemented locally; end-to-end from stored HTML |
| [351](./ticket-351-technical-audit-q72-redirects-internal-links.md) | Q72 | Maintenance (broken links etc.) / Redirects & internal links | P3 | proposed |
| [352](./ticket-352-technical-audit-q74-asset-accessibility.md) | Q74 | Maintenance (broken links etc.) / Asset accessibility | P2 | proposed |
| [353](./ticket-353-technical-audit-q76-subdomain-link-hygiene.md) | Q76 | Maintenance (broken links etc.) / Subdomain & link hygiene | P2 | proposed |
| [354](./ticket-354-technical-audit-q77-subdomain-index-hygiene.md) | Q77 | Maintenance (broken links etc.) / Subdomain & index hygiene | P2 | implemented locally; fed by exposure-inventory or host-probe records |
| [355](./ticket-355-technical-audit-q79-server-errors-5xx-stability.md) | Q79 | Maintenance (broken links etc.) / Server errors & 5xx stability | P1 | proposed |
| [356](./ticket-356-technical-audit-q91-internal-link-quality.md) | Q91 | Maintenance (broken links etc.) / Internal link quality | P3 | proposed |
| [357](./ticket-357-technical-audit-q92-security-forms.md) | Q92 | Maintenance (broken links etc.) / Security & forms | P2 | implemented locally; end-to-end from stored HTML |
| [358](./ticket-358-technical-audit-q102-preview-and-draft-exposure.md) | Q102 | Maintenance (broken links etc.) / Preview and draft exposure | P1 | answerer implemented; collector missing |
| [359](./ticket-359-technical-audit-q103-redirect-integrity.md) | Q103 | Maintenance (broken links etc.) / Redirect integrity | P2 | proposed |
| [360](./ticket-360-technical-audit-q104-search-result-host-hygiene.md) | Q104 | Maintenance (broken links etc.) / Search-result host hygiene | P2 | implemented locally (manual workflow); always Pending |
| [361](./ticket-361-technical-audit-q29-performance.md) | Q29 | Performance / Performance | P2 | answerer implemented; collector missing |
| [362](./ticket-362-technical-audit-q63-server-performance-security.md) | Q63 | Performance / Server performance & security | P3 | answerer implemented; collector missing |
| [363](./ticket-363-technical-audit-q64-resource-hints-performance.md) | Q64 | Performance / Resource hints & performance | P3 | answerer implemented; collector missing |
| [364](./ticket-364-technical-audit-q65-resource-loading-priority.md) | Q65 | Performance / Resource loading & priority | P3 | implemented locally; end-to-end from stored HTML |
| [365](./ticket-365-technical-audit-q66-image-performance.md) | Q66 | Performance / Image performance | P3 | answerer implemented; collector missing |
| [366](./ticket-366-technical-audit-q67-font-performance-cwv.md) | Q67 | Performance / Font performance & CWV | P3 | implemented locally (partial); inline @font-face only |
| [367](./ticket-367-technical-audit-q68-core-web-vitals-lcp-cls.md) | Q68 | Performance / Core Web Vitals (LCP & CLS) | P2 | answerer implemented; collector missing |
| [368](./ticket-368-technical-audit-q69-resource-loading-lcp.md) | Q69 | Performance / Resource loading & LCP | P3 | answerer implemented; collector missing |
| [369](./ticket-369-technical-audit-q86-critical-rendering-path.md) | Q86 | Performance / Critical rendering path | P2 | implemented locally; end-to-end from stored HTML |
| [370](./ticket-370-technical-audit-q96-ai-crawler-governance.md) | Q96 | AI / AI crawler governance | P2 | implemented locally; fed by saved robots.txt (`--robots-txt HOST=FILE`) |
