# Ticket 260: Accept-Language and geo-redirect detection probe

## Status and priority

Proposed — P2. Owner: unassigned. Extends live probe framework (Tickets 193, 236, 257) and international SEO checks (relates to question Q25).

## Goal

Deterministically test whether an origin web server executes dynamic HTTP redirects or serves alternate content based on `Accept-Language` request headers or simulated client geo-IP endpoints, flagging redirect configurations that trap or misroute search engine crawlers.

## Background

Search engine crawlers (including Googlebot) generally crawl without localized `Accept-Language` headers or from default US IP addresses. If a site automatically redirects requests based on `Accept-Language` or geo-IP location (especially on the homepage or top-level category routes):
- Googlebot may never see localized regional pages or may get trapped in an endless redirect loop.
- Canonical declarations can conflict with automatic redirect targets.
- Users and bots sharing the same URL may receive completely different status codes and redirect chains.

`crawler_cli` currently issues crawl requests with static headers and does not systematically probe for language-based dynamic redirection.

## Tasks

### Accept-Language Variation Probe
- Against the canonical homepage, root apex, and key international template roots, issue a bounded set of synthetic HTTP GET probes varying the `Accept-Language` header:
  - Empty / None (default bot behavior)
  - `*` (wildcard)
  - `en-US,en;q=0.9`
  - `es-ES,es;q=0.9`
  - `de-DE,de;q=0.9`
  - `fr-FR,fr;q=0.9`
  - `ja-JP,ja;q=0.9`
  - `pt-BR,pt;q=0.9`
- Record the full HTTP response pair: status code, final URL, redirect chain, `Vary` header (verifying `Vary: Accept-Language`), and `Set-Cookie` headers.

### Evaluation & Verdict Logic
- Flag `forced_language_redirect`: Origin issues 301/302/307 redirects to language subpaths based solely on `Accept-Language`.
- Flag `missing_vary_header`: Origin serves different content or redirects based on language headers without emitting `Vary: Accept-Language`.
- Flag `bot_trap`: Empty/wildcard `Accept-Language` triggers a redirect loop or fails to reach the primary canonical host.

### Persistence & Technical Audit Contract
- Persist probe outcomes in the run-scoped custom probe store (Ticket 257).
- Surface findings in the international SEO section of the technical audit report.

## Definition of Done

- [ ] A fixture server returning 302 redirects to `/es/` when `Accept-Language: es` is sent is classified as `language_redirect_detected`.
- [ ] A server returning different content without `Vary: Accept-Language` triggers `missing_vary_header`.
- [ ] A neutral/empty header probe confirms whether search engines can access the default page cleanly.
- [ ] All probe outcomes are recorded with exact request headers, response codes, and final destinations.
- [ ] Deterministic unit tests cover all language variants and edge cases with zero external network access.
