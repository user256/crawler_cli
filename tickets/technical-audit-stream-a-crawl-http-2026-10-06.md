# Stream A — Crawl and HTTP evidence

38 tickets. Owns the run-validity gate, robots and sitemap evidence, crawl
graph, URL families, and HTTP/redirect/status checks.

## Tickets

[267](./ticket-267-technical-audit-q1-robots-txt.md), [268](./ticket-268-technical-audit-q97-robots-txt.md), [269](./ticket-269-technical-audit-q3-sitemaps.md), [270](./ticket-270-technical-audit-q4-sitemaps.md), [271](./ticket-271-technical-audit-q13-internal-linking.md), [272](./ticket-272-technical-audit-q14-internal-linking.md), [274](./ticket-274-technical-audit-q23-internal-linking.md), [277](./ticket-277-technical-audit-q40-information-architecture.md), [278](./ticket-278-technical-audit-q44-crawl-depth-discoverability.md), [281](./ticket-281-technical-audit-q48-information-architecture.md), [282](./ticket-282-technical-audit-q49-internal-linking-clusters.md), [283](./ticket-283-technical-audit-q75-commercial-links-compliance.md), [284](./ticket-284-technical-audit-q82-crawl-discovery-provenance.md), [285](./ticket-285-technical-audit-q90-access-log-bot-verification.md), [286](./ticket-286-technical-audit-q93-xml-sitemap-architecture.md), [288](./ticket-288-technical-audit-q98-robots-txt.md), [289](./ticket-289-technical-audit-q99-directory-and-file-exposure.md), [290](./ticket-290-technical-audit-q100-document-discovery.md), [301](./ticket-301-technical-audit-q26-scope.md), [330](./ticket-330-technical-audit-q24-crawl-waste.md), [331](./ticket-331-technical-audit-q34-index-bloat-lifecycle.md), [333](./ticket-333-technical-audit-q70-robots-txt-crawl-budget.md), [334](./ticket-334-technical-audit-q81-crawl-safety-rate-limiting.md), [335](./ticket-335-technical-audit-q88-server-response-crawl-budget.md), [336](./ticket-336-technical-audit-q89-conditional-http-caching.md), [337](./ticket-337-technical-audit-q101-crawl-traps.md), [338](./ticket-338-technical-audit-q2-url-variants.md), [340](./ticket-340-technical-audit-q6-error-handling.md), [341](./ticket-341-technical-audit-q7-url-variants.md), [342](./ticket-342-technical-audit-q19-redirects.md), [343](./ticket-343-technical-audit-q22-internal-linking.md), [349](./ticket-349-technical-audit-q42-status-codes-errors.md), [351](./ticket-351-technical-audit-q72-redirects-internal-links.md), [352](./ticket-352-technical-audit-q74-asset-accessibility.md), [353](./ticket-353-technical-audit-q76-subdomain-link-hygiene.md), [355](./ticket-355-technical-audit-q79-server-errors-5xx-stability.md), [356](./ticket-356-technical-audit-q91-internal-link-quality.md), [359](./ticket-359-technical-audit-q103-redirect-integrity.md)

## Constraints

- Q26 and Q81 share the run-gate mechanism; implement and test their combined
  downgrade behaviour before handing the contract to other streams.
- Keep raw collection separate from page-level interpretation. Emit evidence
  with the originating URL, response history, collection timestamp and
  coverage state.
- Do not build rendered-browser or third-party integrations here. Record the
  required URL identity and let Stream C add that evidence.

## Handoff

Publish the gate result and stable evidence rows used by the other streams.

