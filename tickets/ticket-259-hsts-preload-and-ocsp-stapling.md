# Ticket 259: TLS transport optimization: HSTS preload status and OCSP stapling verification

## Status and priority

Core implemented (2026-09-28, branch `feature/ticket-259-hsts-ocsp`); preload-list lookup and live OCSP inspection deferred — P2. Extends passive security header checks (Ticket 150) and server performance checks (relates to question Q63).

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

## Implementation notes (2026-09-28)

### Built

- `src/crawler_cli/transport_security.py` holds the **single reusable
  `Strict-Transport-Security` parser** (`parse_strict_transport_security`).
  Ticket 150's HSTS parsing did not exist on master; 150 should reuse this
  parser for its `posture.hsts.*` facts instead of writing a second one.
  RFC 6797 rules: case-insensitive directive names, quoted values, duplicate
  or missing/non-numeric `max-age` makes the header invalid, unknown
  directives ignored, first of comma-folded instances used.
- `hsts_preload_assessment` applies the observable hstspreload.org criteria:
  `max-age >= 31536000`, `includeSubDomains`, `preload`, header on the HTTPS
  apex, and `http://apex/` redirecting to `https://` on the **same host**.
  Each miss is a specific warning (`max_age_below_31536000`,
  `include_subdomains_missing`, `preload_token_missing`,
  `hsts_header_missing`, `hsts_header_invalid:*`,
  `http_not_redirected_to_https`,
  `http_redirect_must_reach_https_on_same_host_first`). Subdomains are
  `not_applicable_not_registrable_domain` (only a missing/invalid header is
  flagged). No HTTP-scheme probe means `undetermined`, never eligible.
- HSTS is read only from HTTPS responses (RFC 6797 section 8.1), attributed to
  the final response host (`final_url` was added to the performance-inventory
  report query). HTTP-to-HTTPS evidence comes only from existing `scheme`
  URL-variant probes, so this check sends no new requests and needs no new
  destination-guard handling.
- The technical audit gains check `transport-security` (registry state
  `implemented_candidate`, analyst-only), `transport_security_coverage`,
  `transport_security_report` (per-host `hsts_preload_eligible`,
  `ocsp_stapled`, `ocsp_stapling_state`, warnings) and Overview rows. It is
  exempt from the publication gate: it is an informational optimization.

### OCSP stapling: not determinable with the available TLS stack

- Stdlib `ssl` cannot send `status_request` or expose a stapled response
  (no API on `SSLContext`/`SSLSocket` as of Python 3.12 / OpenSSL 3.5).
- The bundled curl_cffi (BoringSSL) rejects `CURLOPT_SSL_VERIFYSTATUS` with
  `CURLE_NOT_BUILT_IN`; even where supported, that option fails the handshake
  rather than reporting stapled versus not stapled.
- pyOpenSSL (`request_ocsp` / `set_ocsp_client_callback`) would work but adds
  `pyOpenSSL` + `cryptography`; not added.
- So every host records `ocsp_stapling_state: not_determinable`,
  `ocsp_stapled: null`, never a false pass/fail. `classify_ocsp_stapling`
  already maps an `OcspHandshakeObservation` to
  `stapled` / `not_stapled` / `unsupported` / `not_determinable`, so a future
  inspector only has to produce observations. OCSP stapling is labelled
  informational, low SEO impact, not a TTFB defect claim.

### Deferred

- Chromium preload-list membership lookup (`hsts_preload_list_membership`
  is `not_queried`): needs an authoritative external source (hstspreload.org
  API or a pinned Chromium list snapshot) and a destination-guard decision.
- Live OCSP inspection and the DoD items "test TLS connection to an
  OCSP-stapled / non-stapled server": blocked on a TLS stack that exposes the
  staple (for example an optional pyOpenSSL extra) and TLS test fixtures.
- HSTS on redirect hops (hstspreload.org requires it on an HTTPS redirect from
  the apex), valid certificate chain and "all subdomains over HTTPS" are not
  observable from stored snapshots and are listed in coverage as
  `hsts_preload_criteria_not_observable`.

