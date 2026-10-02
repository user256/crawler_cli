# Ticket 266: Render, probe and external detectors for the question runner

## Goal

Answer the questions that need a rendered or mobile crawl, an active probe
or a third-party service.

## Scope

| Question | Detector | Needs |
|---|---|---|
| Q29 | lab CWV per template (heuristic) | render |
| Q35 | `render-api-requests` (heuristic) | render |
| Q38 | `js-only-navigation-controls` (heuristic) | render |
| Q46 | `footer-link-parity` | render |
| Q63 | `hsts-ocsp` | probe + hstspreload.org |
| Q64 | `resource-hints` | render |
| Q66 | image format share | asset fetch |
| Q68 | `lcp-image-attributes` (heuristic) | render trace |
| Q69 | `lcp-background-image` (heuristic) | render trace |
| Q95 | `interstitial-coverage` (heuristic) | mobile render |
| Q33 | `ugc-spam-patterns` (heuristic) | stored HTML |
| Q61 | `quotation-markup` (manual sample) | stored HTML |

Q25 (locale redirects), Q28 (external links), Q82 (discovery provenance) and
Q89 (conditional requests) need only answerers once their contract
collectors produce evidence. Withdrawn working-tree tickets 258–262 covered
Q96, Q63, Q25, Q81 and Q82; this ticket and 265 take over Q63 and Q96.

## Definition of Done

- [ ] Heuristic answers never exceed Needs validation and never ticket
  automatically.
- [ ] Each question answers on a fixture run that has the required evidence,
  and stays Pending with the missing evidence named otherwise.
