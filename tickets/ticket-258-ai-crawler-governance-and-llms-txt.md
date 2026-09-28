# Ticket 258: AI search crawler governance and /llms.txt audit check

## Status and priority

Proposed — P2. Owner: unassigned. Extends `crawler_cli` robots.txt parsing and technical audit contract (relates to question Q96).

## Goal

Deterministically audit origin AI crawler permissions in `robots.txt` and verify the availability and syntax of machine-readable AI context files (`/llms.txt` and `/llms-full.txt`), producing structured technical audit evidence without third-party dependencies.

## Background

Search engines and LLM answer engines increasingly rely on dedicated AI user-agents (e.g. `GPTBot`, `ClaudeBot`, `PerplexityBot`, `Google-Extended`, `Amazonbot`, `Bytespider`, `CCBot`, `Applebot-Extended`). Sites frequently misconfigure robots directives (e.g. accidentally blocking AI summary bots while attempting to block training scrapers, or vice versa) or fail to provide standard `/llms.txt` discovery manifests.

Currently, `crawler_cli` parses `robots.txt` only for crawl allowance against its own configured user-agent. It does not extract or report per-agent AI crawler policies, nor does it probe for the emerging `/llms.txt` standard.

## Tasks

### Robots.txt AI Agent Rules
- Extract and evaluate explicit directives for known AI user-agents:
  - `GPTBot` (OpenAI search/crawler)
  - `ChatGPT-User` (OpenAI browse actions)
  - `ClaudeBot` / `anthropic-ai` (Anthropic search/training)
  - `PerplexityBot` (Perplexity AI)
  - `Google-Extended` (Google Gemini training opt-out)
  - `Amazonbot` (Amazon search/AI)
  - `Bytespider` (ByteDance AI)
  - `CCBot` (Common Crawl)
  - `Applebot-Extended` (Apple Intelligence training opt-out)
- Classify each bot's origin access as `allowed`, `blocked`, `partially_blocked`, or `default_wildcard`.

### /llms.txt Probing
- Perform a bounded HTTP GET probe against:
  - `/.well-known/llms.txt` and `/llms.txt`
  - `/llms-full.txt`
- Capture HTTP status code, final redirected URL, `Content-Type` header, and byte size.
- Validate that successful responses serve valid Markdown (`text/markdown` or `text/plain`) rather than HTML soft-404 pages.

### Audit Reporting & Recipient Contract
- Add `ai_governance` check result to `technical-audit` runtime bundle and JSON export.
- Record exact findings: missing files, HTML soft-404 masquerades, and explicit bot allowance/blocking posture.

## Definition of Done

- [ ] A fixture `robots.txt` with mixed AI directives correctly outputs permission status for all 9 recognized AI bot families.
- [ ] A valid `/llms.txt` response records HTTP 200, markdown content type, length, and title.
- [ ] An HTML error page returned at `/llms.txt` with status 200 is flagged as an invalid soft-404.
- [ ] Technical audit JSON and report views surface AI governance findings under the `AI` theme.
- [ ] Automated unit and contract tests pass with 100% deterministic local fixtures.
