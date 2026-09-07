# Ticket review brief: authorised adversarial-evidence lane (144–154)

**Prepared:** 2026-08-21

**Review scope:** tickets 144–154 plus interactions with 129, 132, 135, 137,
155, and the Portal connection-policy contract

**Requested decision:** approve the product boundary and dependency order;
approve individual tickets with the recorded conditions before implementation

## Executive recommendation

Approve the lane as an **authorised evidence and crawler-safety programme**, not
as an evasion-bot or penetration-scanner programme.

The proposed work is coherent if three foundations land before feature
detectors:

1. Ticket 144 fixes product claims and permanently records prohibited goals.
2. Ticket 148 supplies one exact authorization/scope manifest for every
   security-adjacent network command.
3. Tickets 149 and 153 supply destination-network safety and secret-safe
   evidence respectively.

Ticket 147 can proceed after 144 for ordinary-crawler safety, but its strict
security-mode integration needs 148. Tickets 145–146, 150–152, and 154 must not
land as independent scripts that bypass those foundations.

The review should explicitly reject automatic identity rotation until success,
CAPTCHA/WAF bypass, payload fuzzing, forced browsing, credential attacks, and
identifier mutation. Those are literal gaps against the two broad definitions,
but they are not product backlog for this repository.

## Why this lane exists

`crawler_cli` already has dual-use mechanics:

- custom/per-domain User-Agents and curl browser impersonation;
- Obscura stealth/browser rendering;
- rotating proxy lists and rotating gateways;
- cookies plus Basic/Bearer authentication;
- bot-challenge detection and one HTTP-to-browser escalation;
- an explicit robots override.

It also has strong evidence-crawler primitives: bounded/resumable crawling,
robots/crawl-delay enforcement by default, host/path scope, sitemaps, response
headers, redirects, content hashes, JS/no-JS comparison, run snapshots, and a
soft-404 utility.

It does **not** currently have:

- a portable operator authorization/scope record;
- a general default defense against private/special destination addresses and
  rebinding across all backends;
- a shared redacted security finding contract;
- passive security header/cookie/TLS/form/API/disclosure reports;
- fixed-set client or supplied-session differential commands;
- a complete session-mutating URL policy or confirmed robots override.

One earlier assumption was corrected during review: `extract_links()` already
accepts only HTTP(S) anchors, and the crawler does not submit forms. Ticket 147
now regression-locks those properties rather than presenting them as new work.

## Product boundary for approval

### This product is

- An authorised technical-SEO evidence crawler.
- A client that distrusts CMS claims and compares independent evidence sources.
- A passive/bounded exposure and configuration inventory tool.
- A safe differential measurement tool over exact operator-supplied inputs.
- A crawler that should protect both the target and its own execution host.

### This product is not

- A bot that changes identity/egress until a blocked request returns 200.
- A CAPTCHA solver or WAF-specific bypass toolkit.
- A scanner that injects SQL/XSS/SSTI/command/path/SSRF payloads.
- A forced-browsing, credential-stuffing, IDOR/BOLA mutation, or privilege-
  escalation tool.
- A system that treats a spoofed search-engine UA as evidence of the real
  search engine's treatment.

### Required language discipline

Use “observe,” “inventory,” “compare,” “candidate,” and “manual review.” Avoid
“bypass,” “beat,” “exploit,” “prove vulnerable,” or “Google is blocked” unless
the evidence genuinely supports that claim and the product boundary changes in
a separately reviewed decision.

## Dependency graph

```text
144 claim/scope language
├── 147 crawler self-safety
├── 148 authorization + exact technical scope
│   └── 149 destination/IP/rebinding safety
│       ├── 145 client-split measurement
│       ├── 146 exposure inventory
│       ├── 150 passive HTTP/TLS posture
│       └── 152 supplied-session differential
└── 153 evidence contract + redaction
    ├── 145 client-split measurement (also needs 148/149)
    ├── 146 exposure inventory (also needs 148/149)
    ├── 150 passive HTTP/TLS posture
    ├── 151 passive form/API inventory (also needs 148 and generic ticket 155)
    ├── 152 supplied-session differential (also needs 129/148/149)
    └── 154 disclosure detection (also needs 146)
```

Ticket number is not implementation order. In particular, 153 deliberately
lands before 150–152 and 154.

## Recommended delivery waves

### Wave 0 — product boundary

- **144** only.
- Documentation/help/contract assertion.
- No new fetch behavior.

Exit gate: maintainers approve the prohibited-capability list and the wording
for impersonation, stealth, proxies, custom UA, challenge escalation, and
robots override.

### Wave 1 — shared trust foundations

- **148** authorization/scope manifest.
- **153** security evidence/redaction contract.

These can be developed in parallel after 144, but both touch frozen artifacts,
run metadata, persistence, and public CLI behavior. Each needs its own reviewed
contract change.

Exit gate: one normalized scope predicate and one evidence serializer exist;
later commands are prohibited from bypassing them.

### Wave 2 — runtime safety

- **149** destination-network/SSRF safety.
- **147** session-mutation/robots-confirmation safety.

Exit gate: all URL sources use a shared admission sequence; backend capability
truth is serialized; no unsafe backend is allowed in strict mode.

### Wave 3 — bounded observation features

- **145** client-split measurement.
- **146** authorized exposure inventory.
- **150** passive HTTP/cookie/TLS/mixed-content posture.
- **151** passive forms/API/router/source-map inventory, reusing ticket 155's
  generic static JavaScript URL candidates.

Prefer independent commands/reports over adding four modes to the open crawl
loop simultaneously.

Exit gate: exact request ledgers prove bounded/no-extra traffic; all outputs use
scope and redaction foundations.

### Wave 4 — sensitive comparison and disclosure

- **152** supplied-session differential.
- **154** safe error/information-disclosure detection.

Ticket 152 is last because it combines credentials, personalized content,
multiple isolated clients, comparison uncertainty, and persistence. Ticket 154
is passive but should reuse both exposure provenance and the final evidence
contract.

## Ticket-by-ticket review

### 144 — Name and bound “adversarial”

**Recommendation:** approve as P1 and merge first.

**Why:** existing flags can be described or marketed as bypass features even
when the intended workflow is authorized measurement. Claim hygiene is a real
safety control for later contributors and agents.

**Reviewer checks:**

- README, SKILL, and CLI help say authorized measurement, not bypass.
- Prohibited features are explicit and test-asserted.
- Ticket 137 remains one alternate egress attempt within an already authorized
  pool, never an identity-success loop.

**Risk:** docs alone do not enforce authorization. That is why 148 is separate.

### 145 — Client-split measurement

**Recommendation:** approve with the controlled-measurement contract now in
the ticket.

**Required properties:** same URL, egress, cookies/auth, headers, limits, and
time window; only the declared client dimension changes. No challenge
escalation or proxy rotation inside the matrix. Spoofed bot output always
carries the non-proof field.

**Review concern:** normal backend retry behavior can blur the exact request
count. Require an attempt ledger and prohibit identity/egress changes on retry.

**Suggested size:** M; one command, pure classifier, JSON contract, fixture
server tests. Do not add PostgreSQL persistence in the first PR unless the
contract is stable.

### 146 — Authorized exposure inventory

**Recommendation:** approve after 148–149 and 153.

**Required properties:** candidate hostname derivation is finite and PSL-aware;
derived does not mean authorized; no DNS occurs for undeclared candidates;
soft-404 makes one bounded request and does not mutate the live engine config;
sitemap publication is evidence but not fetch permission.

**Review concern:** DNS enumeration can become brute-force reconnaissance by
dictionary growth. Keep a small versioned label set and require exact manifest
origins.

**Overlap decision:** directory-index/debug-content rules belong to 154, not
146. Ticket 146 owns host/sitemap/soft-404 exposure facts.

**Suggested size:** L, possibly two PRs: host/DNS inventory, then soft-404 and
sitemap correlation.

### 147 — Crawler self-safety

**Recommendation:** approve corrected P1 scope.

**Already implemented:** anchor HTTP(S)-only filtering and no form submission.

**Actual new work:** boundary-aware session-mutating URL policy across every
URL source and redirect, explicit robots confirmation, narrow overrides, typed
skip counts/provenance, and correct budget treatment.

**Review concern:** broad substring rules will create damaging false positives.
Rules must understand path/query boundaries and ship benign editorial fixtures.

**Overlap decision:** share a generic URL-admission interface with Magento
facet guard ticket 134, but do not merge the policies or dependencies.

### 148 — Authorization and scope manifest

**Recommendation:** approve as the central P1 foundation.

**Decisions encoded in the ticket:**

- Ordinary SEO crawl remains available without a manifest.
- Security-adjacent live commands require one.
- Version 1 uses exact origins; no wildcard subdomains.
- A validity window is mandatory and validated before network activity.
- Existing CLI flags may narrow but never widen scope.
- Scope digest changes cannot be waived by ordinary resume config mismatch.
- The manifest records operator attestation; it does not prove legal authority.

**Reviewer decision still needed:** whether `operator` is mandatory or whether
`authorization_reference` alone is sufficient for service-run jobs. Recommend
requiring both but allowing a stable service identity.

**Architecture requirement:** compile one predicate and call it at shared
admission/redirect boundaries. Reject implementations that sprinkle checks
only through the new commands.

**Suggested size:** L/XL, delivered as schema/model/CLI first, then engine and
persistence integration under the same ticket.

### 149 — Destination-network and SSRF safety

**Recommendation:** approve as P1/security, with staged backend delivery and an
honest strict-mode capability gate.

**Decisions encoded in the ticket:** deny any non-global or mixed DNS result by
default; recheck redirects; pin addresses where protection is claimed; private
access needs manifest permission plus explicit CLI intent; remote-DNS proxies
cannot pretend to be locally verified.

**Highest technical risk:** Playwright/Obscura DNS rebinding protection. URL
routing can block obvious private URLs but may not pin DNS for the browser
connection. Strict mode must reject that path until a real guarantee exists.

**Rollout concern:** default private-address denial changes behavior for local
development and internal-site crawls. Ship explicit migration notes and a
double-confirmed allow mechanism. Tests should use the explicit private-network
allow path rather than weakening the production default.

**Suggested PR slices:**

1. Address normalization/policy and aiohttp pinning.
2. curl_cffi parity/capability truth.
3. browser/proxy capabilities and strict-mode startup gate.

Ticket stays open until every claimed path has tests or is truthfully rejected.

### 150 — Passive security posture

**Recommendation:** approve after 149 and 153.

**Key design issue:** current response headers are flattened into a dictionary,
which can lose duplicate `Set-Cookie` lines. Fixing the transport-neutral
header representation is prerequisite work, not detector polish.

**Required non-claims:** ordinary response CORS headers do not prove reflection
or exploitability; CSP weakness patterns do not prove XSS; unavailable TLS
facts are unknown, not pass; HSTS token presence does not prove preload status.

**Suggested PR slices:** header/TLS fact model, pure detectors, persistence and
reports, then run comparison.

**Size:** XL. Review detector policy separately from transport correctness.

### 151 — Passive form/API inventory

**Recommendation:** approve after 148, 153, and generic extractor ticket 155.

**Core safety rule:** form, API, action, router-semantic, and source-map
inventory never auto-enqueues. Ticket 155's separate explicit follow flag may
admit only its strict page-like candidates and is not widened here.

**Review concerns:**

- Populated hidden/password/PII form values must be discarded at extraction,
  not merely redacted at final serialization.
- “CSRF token not observed” is a low/medium-confidence observation, never a
  confirmed vulnerability.
- Router/source-map rules layered on ticket 155 need strict performance and
  false-positive budgets; do not create a second generic string lexer.
- OpenAPI parsing is allowed only for already-fetched explicit documents;
  conventional path guessing and GraphQL introspection remain excluded.

**Size:** XL. Prefer forms/controls first, then API descriptions, then bounded
router/source-map semantics over ticket 155 evidence.

### 152 — Supplied-session differential

**Recommendation:** approve conceptually, implement last, require a fresh
security review before merge.

**Required constraints:** fixed URL list, small profile/URL caps, secret sources
via env/file only, isolated HTTP/browser storage per profile, no persistent
browser profile, no credential retry on denial, and no parameter/role mutation.

**Evidence semantics:** equality/difference is triage. Same-profile repeat
instability must reduce confidence. One missing/blocked profile makes the pair
inconclusive rather than equal.

**Highest data risk:** personalized content and session material. Ticket 153's
recursive secret-absence tests and retention controls are a hard dependency,
not documentation.

**Size:** XL/high risk. Start HTTP-only; add Playwright only after session
isolation and destination-capability proofs exist.

### 153 — Security evidence contract and secret hygiene

**Recommendation:** approve as P1/security and implement in Wave 1 despite its
number.

**Why it blocks detectors:** response `Set-Cookie`, sensitive query strings,
form values, stack traces, DSNs, and proxy credentials can otherwise spread
into every new artifact/table/UI.

**Required architecture:** distinguish internal raw URL identity from exported
redacted URL projection. Never redact frontier keys in place. Use a keyed
digest for correlation of low-entropy sensitive values, not plain SHA-256.

**Review concerns:**

- Redaction must cover exceptions and structured logs, not only JSON output.
- CSV formula injection is part of the threat model.
- Raw sensitive file evidence and database retention require separate explicit
  choices if supported.
- Existing compact/delete commands must include new security tables by exact
  run id.

**Size:** XL/cross-cutting. Require golden contract and recursive known-secret
absence tests before consumers merge.

### 154 — Safe error/disclosure detection

**Recommendation:** approve after 146 and 153.

**Required properties:** already-fetched content only, no guessed paths or
malformed requests, multi-signal classifiers, bounded redacted structural
evidence, explicit false-positive fixtures, and regex runtime budgets.

**Overlap decision:** ticket 146 supplies published-test/soft-404/sitemap
provenance; 154 classifies diagnostic content. Ticket 151 records source-map
references but does not download/analyse them.

**Review concern:** full stack traces and internal values are precisely the
data this detector must not copy into portable evidence. Retain marker ids,
counts, types, and keyed correlation hashes instead.

**Size:** L after the 153 framework exists.

## Shared architecture recommended by review

### One URL admission pipeline

Every initial, discovered, auxiliary, probe, and redirect URL should pass the
same ordered concepts:

1. Parse/normalize; permit HTTP(S); reject malformed/userinfo URLs.
2. Apply ticket-148 origin/path/time/method scope when a manifest is active.
3. Apply ticket-147 session-mutation policy.
4. Apply ticket-149 destination resolution/address policy at connection time.
5. Apply robots/crawl-delay policy; its own robots request also uses step 4.
6. Admit against request/byte/page budgets, rate limits, and circuit breakers.
7. Fetch; repeat the relevant checks for each redirect connection.

Recommended shared result shape:

```text
UrlAdmissionDecision
  allowed
  stage
  reason
  source
  normalized_url / redacted_url
  scope_manifest_digest
  backend_capabilities
```

Do not overload HTTP status or generic `skip_reason` strings until distinct
scope/safety/policy/error categories become indistinguishable.

### One capability declaration

Extend the existing Portal policy capability approach rather than claiming all
backends are equal. Record protection for:

- initial navigation;
- redirects;
- robots and sitemaps;
- probes/live comparison;
- browser top-level navigation;
- browser workers/popups/subresources;
- DNS/address pinning;
- local vs remote proxy resolution.

Strict modes fail closed on missing required capability.

### One evidence pipeline

Detectors emit structured facts. A central policy turns facts into findings.
One serializer applies redaction, evidence budgets, schema versions, and CSV
hygiene. Persistence keeps run identity and detector version. Comparison reads
normalized facts/findings rather than reparsing raw HTML when possible.

This separation lets policy/severity change without recrawling and prevents
each detector from inventing a leaking evidence format.

## Existing-ticket interactions

- **129 (done):** origin-scoped Playwright auth is a prerequisite for 152; do
  not regress its redirect security proofs.
- **132 (proposed):** final successful-content/page budget semantics affect
  policy rejections in 147 and probe requests in 146. Coordinate counts; do not
  let rejected URLs exhaust the useful-page budget silently.
- **134 (proposed):** Magento facet guard and 147 both need URL admission
  policy, but have different rules and product purposes.
- **135 (proposed):** browser per-host proxy correctness must be resolved or
  explicitly rejected before proxy-sensitive client/session measurements.
- **137 (proposed):** alternate proxy on one authorized escalation stays
  outside 145's controlled client matrix and cannot become retry-until-success.
- **041/042 (done):** crawl delete/compact behavior is the precedent for 153
  security-evidence retention.
- **086/095 (done):** run isolation/snapshots apply to every new persistence
  table and report.
- **087 (done):** sitemap scope/budget/politeness is a URL-admission precedent;
  148/149 must include all the auxiliary paths it covered.
- **122/123 (done):** comparison contracts and distinct findings exit codes
  are precedents, but security findings need their own schema/non-claims.
- **Portal URL policy:** remains an optional external authorization/pinning
  integration. Ticket 148 does not replace it; ticket 149 may reuse its safe
  connection machinery while retaining truthful capability boundaries.

## Cross-cutting acceptance gates

Every network-active ticket in this lane must prove:

- Validation and out-of-scope inputs make zero network calls.
- A fixture ledger matches the exact allowed method, URL, redirect, retry, and
  attempt count.
- 401/403/429/challenges are observations, not identity-rotation triggers.
- Every auxiliary URL class uses the same scope and destination decisions.
- Truncated, challenged, failed, denied, untested, unknown, and clean states
  remain distinct.
- New rows/reports are run-scoped and resume fingerprints cover behaviorally
  material settings.
- Known test secrets are recursively absent from stdout, logs, exceptions,
  JSON/JSONL/CSV/HTML, PostgreSQL projections, and GUI/API responses.
- Output schemas have explicit versions and golden contract fixtures.
- Detectors have false-positive and pathological-input performance fixtures.
- Documentation states authorization requirements and passive/non-exploit
  limitations.

## Principal risks and mitigations

### False sense of legal authorization

**Risk:** a manifest may be mistaken for proof of permission.

**Mitigation:** call it operator attestation; store an opaque reference; state
the non-proof in CLI/help/artifacts.

### Default private-network policy breaks internal crawling

**Risk:** localhost/intranet users and tests fail after 149.

**Mitigation:** explicit double-confirmed private-network mode, exact CIDRs,
release notes, and test fixtures that opt in rather than weakening defaults.

### Browser capability overclaim

**Risk:** URL interception is presented as DNS pinning.

**Mitigation:** per-path capability object; strict-mode startup rejection until
the guarantee exists.

### Redaction corrupts crawl identity

**Risk:** token-redacted URLs collapse distinct frontier/canonical records.

**Mitigation:** preserve raw internal identity and create separate redacted
projections/digests.

### Evidence storage grows or leaks

**Risk:** duplicate facts, raw headers, and excerpts bloat PostgreSQL and expose
secrets.

**Mitigation:** normalized facts, bounded evidence, values-off-by-default,
exact-run retention, compact/delete integration.

### Passive findings overclaim vulnerabilities

**Risk:** missing CSP, unobserved CSRF field, content similarity, or version
banner is treated as confirmed exploitation.

**Mitigation:** fact/finding separation, confidence, non-claims, unknown states,
manual verification language, no fabricated CWE/CVSS.

### Feature drift into active scanning

**Risk:** candidate inventory begins auto-fetching conventional paths or mutating
inputs.

**Mitigation:** exact request-ledger tests, fixed input caps, candidate export
separate from crawl, and prohibited-capability contract assertions.

## Explicitly rejected backlog

Do not allocate ticket numbers for these under the current product decision:

- rotate UA/proxy/fingerprint after a block until success;
- CAPTCHA solving or WAF token generation;
- disregard robots as the normal operating mode;
- distributed rate-limit avoidance;
- SQLi, XSS, command/SSTI/path traversal/SSRF payload generation;
- forced browsing of guessed admin/debug/backup paths;
- credential guessing, spraying, or stuffing;
- IDOR/BOLA identifier mutation, role forging, token tampering;
- CSRF execution or state-changing form submission;
- source-map downloading/deobfuscation or CVE exploitation.

Any future proposal for one of these is a product-boundary change requiring a
new threat model and explicit maintainer approval, not an extension of 144–154.

## Review decision checklist

Reviewers should record yes/no for each item:

- [ ] Approve “authorized evidence crawler, not evasion bot/pentest scanner.”
- [ ] Approve the explicit rejected-backlog list.
- [ ] Keep ordinary SEO crawling manifest-optional.
- [ ] Require ticket-148 manifest for every security-adjacent live command.
- [ ] Use exact origins and mandatory validity windows in manifest v1.
- [ ] Require both manifest permission and CLI intent for private-network or
      robots overrides.
- [ ] Default-deny non-global/mixed DNS destinations after ticket 149.
- [ ] Fail strict mode closed when a browser/proxy path cannot prove its safety
      capability.
- [ ] Keep raw sensitive evidence off by default and separate file/database
      override decisions.
- [ ] Preserve raw internal URL identity; redact only projections/evidence.
- [ ] Keep ticket-151 endpoint/form/router/source-map inventory out of the
      frontier; do not widen ticket 155's page-only follow eligibility.
- [ ] Keep client/session comparisons fixed-list, bounded, and non-mutating.
- [ ] Require passive findings to carry confidence and non-claims.
- [ ] Approve implementation order 144 → 148+153 → 149+147 → feature tickets.

## Final review disposition proposed

- **Approve now:** 144, corrected 147, 148, 149, and 153 as foundation/safety
  tickets, subject to the explicit reviewer decisions above.
- **Approve dependent scope:** 145, 146, 150, 151, and 154 once their recorded
  foundations exist.
- **Approve concept only / re-review before merge:** 152 because it handles
  supplied credentials and personalized content across multiple identities.
- **Reject from backlog:** all evasion-loop and active exploit functionality
  listed above.

Ticket **155** was assigned after this lane; next unreserved is **156**. Ticket
**110** remains
intentionally unused/rejected and must not be reused.
