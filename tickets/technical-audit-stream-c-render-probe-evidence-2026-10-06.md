# Stream C — Render, probes and supplied evidence

31 tickets. Owns rendered and mobile observations, active bounded probes,
supplied third-party/manual evidence, host exposure, performance measurements
and AI crawler policy.

## Tickets

[273](./ticket-273-technical-audit-q18-crawl-access.md), [275](./ticket-275-technical-audit-q31-crawl-access.md), [276](./ticket-276-technical-audit-q38-crawl-access-js.md), [279](./ticket-279-technical-audit-q45-international-internal-linking.md), [280](./ticket-280-technical-audit-q46-dom-completeness-rendering.md), [287](./ticket-287-technical-audit-q95-mobile-interstitial-compliance.md), [302](./ticket-302-technical-audit-q30-search-evidence.md), [308](./ticket-308-technical-audit-q50-content-quality-topical-authority.md), [327](./ticket-327-technical-audit-q85-javascript-rendering-parity.md), [332](./ticket-332-technical-audit-q35-crawl-efficiency.md), [339](./ticket-339-technical-audit-q5-security.md), [344](./ticket-344-technical-audit-q25-redirects.md), [345](./ticket-345-technical-audit-q27-host-hygiene.md), [346](./ticket-346-technical-audit-q28-external-links.md), [347](./ticket-347-technical-audit-q33-site-security-spam.md), [348](./ticket-348-technical-audit-q39-internal-linking.md), [350](./ticket-350-technical-audit-q43-link-equity-architecture.md), [354](./ticket-354-technical-audit-q77-subdomain-index-hygiene.md), [357](./ticket-357-technical-audit-q92-security-forms.md), [358](./ticket-358-technical-audit-q102-preview-and-draft-exposure.md), [360](./ticket-360-technical-audit-q104-search-result-host-hygiene.md), [361](./ticket-361-technical-audit-q29-performance.md), [362](./ticket-362-technical-audit-q63-server-performance-security.md), [363](./ticket-363-technical-audit-q64-resource-hints-performance.md), [364](./ticket-364-technical-audit-q65-resource-loading-priority.md), [365](./ticket-365-technical-audit-q66-image-performance.md), [366](./ticket-366-technical-audit-q67-font-performance-cwv.md), [367](./ticket-367-technical-audit-q68-core-web-vitals-lcp-cls.md), [368](./ticket-368-technical-audit-q69-resource-loading-lcp.md), [369](./ticket-369-technical-audit-q86-critical-rendering-path.md), [370](./ticket-370-technical-audit-q96-ai-crawler-governance.md)

## Constraints

- Reuse Stream A’s URL and run identity; do not create a parallel crawl or
  widen host scope.
- Move Q18, Q31 and Q50 to `supplied-input` before adding answerers. Tests
  must prove they remain Pending without an imported bundle.
- Q104 is a manual review record. The automatic runner must always leave it
  Pending and never create a client ticket.
- Heuristic checks remain at Needs validation and never raise automatic
  client tickets.

## Handoff

Publish imported, rendered and probe observations with their source, time,
scope and coverage qualification. These rows must be safe for the common
question runner to consume.

