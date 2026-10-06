# Ticket 307: Implement technical-audit Q47 — Information architecture & taxonomy

## Goal

Make Q47 answerable from deterministic, run-scoped Python evidence.

## Question

Does any content page lack a visible breadcrumb or BreadcrumbList markup, or does the markup disagree with the visible trail?

## Rule

Issue if: At least 20% of content pages lack both, or any page's BreadcrumbList items differ from its visible breadcrumb links.

## Evidence and reuse

- Group: `best-practice` — answerable: Yes; ticket: on Issue, classification capped at Improvement or Warning, priority at most Medium.
- Registry classification and priority: Improvement / Low.
- Required inputs: `crawl`, `stored-html`.
- Threshold: `min_share = 0.2`.
- Existing contract checks: `structured-data-feature-rules`.
- New detector: `breadcrumb-consistency`.
- Why it matters: Breadcrumbs link each page to its parent topic and appear in search results. Markup that differs from the visible trail is ignored.
- Registry note: Whether editors can set breadcrumbs independently of URLs is a CMS question for the client; only the published output is tested.

## Tasks

- [ ] Implement detector `breadcrumb-consistency`, then register an explicit `Q47` answerer.
- [ ] Reuse contract evidence from `structured-data-feature-rules`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q47 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Tickets are capped at Improvement or Warning classification and at most Medium priority.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P3**).
