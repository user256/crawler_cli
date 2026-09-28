# Ticket 259: TLS transport optimization: HSTS preload status and OCSP stapling verification

## Status and priority

Proposed — P2. Owner: unassigned. Extends passive security header checks (Ticket 150) and server performance checks (relates to question Q63).

## Goal

Validate that HTTPS origin hosts implement latency-minimizing TLS transport optimizations: verify whether `Strict-Transport-Security` meets HSTS preload eligibility requirements, query Chromium HSTS preload enrollment status, and check whether the TLS handshake includes an OCSP stapled response.

## Background

Search bot crawling efficiency and Core Web Vitals (TTFB) depend heavily on initial connection overhead. Two high-impact transport optimizations frequently audited in technical SEO:
1. **HSTS Preload:** Eliminates the initial insecure HTTP-to-HTTPS redirect round-trip for first-time visitors and bots by hardcoding HTTPS in browser/crawler preload lists. Requires `max-age >= 31536000`, `includeSubDomains`, and `preload` directives.
2. **OCSP Stapling:** Eliminates blocking external OCSP responder HTTP requests during the TLS certificate verification phase by having the origin server bundle a cached, signed OCSP response directly in the TLS handshake.

`crawler_cli` currently checks only the presence of `Strict-Transport-Security` as a raw response header. It does not evaluate preload directive compliance, query preload status, or inspect TLS handshake extensions for OCSP stapling.

## Tasks

### HSTS Header Analysis & Preload Eligibility
- Parse `Strict-Transport-Security` response headers on primary apex and subdomain hosts.
- Verify exact compliance with Chromium HSTS preload criteria:
  - `max-age` >= 31536000 (1 year)
  - `includeSubDomains` present
  - `preload` token present
- Flag missing tokens or substandard `max-age` values.

### TLS Handshake OCSP Stapling Verification
- In the connection/transport probe abstraction, inspect the TLS handshake using Python's `ssl` library (`SSLContext` configured with `CERT_REQUIRED` and `status_request` extension enabled).
- Record whether the server returns a valid stapled OCSP response (`OCSPResponseStatus.SUCCESSFUL`).
- Distinguish between:
  - `stapled`: Valid stapled OCSP response received in handshake.
  - `not_stapled`: Handshake completed successfully, but server did not provide a stapled OCSP payload.
  - `unsupported`: Origin does not support the TLS extension.

### Audit Reporting
- Surface HSTS preload compliance and OCSP stapling evidence in technical audit JSON and performance summaries.

## Definition of Done

- [ ] A synthetic origin with full HSTS preload directives passes eligibility checks; missing directives trigger specific actionable warnings.
- [ ] A test TLS connection to an OCSP-stapled server captures and verifies the stapled response status.
- [ ] A test connection to a non-stapled server records `not_stapled` without failing the connection.
- [ ] Evidence fields (`hsts_preload_eligible`, `ocsp_stapled`) are integrated into the technical audit evidence contract.
- [ ] Tests verify behavior against local mocked TLS fixtures without external network calls.
