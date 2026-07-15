# Ticket 109: Complete thin-content diagnostic evidence

**Status:** in progress (claimed 2026-07-15 on `agent/ticket-109-thin-diagnostics`)
**Priority:** P2 reporting
**Depends on:** Ticket 104

## Goal

Complete the diagnostic fields requested by Ticket 104 without changing its
reviewed thin-content labelling or gating policy.

## Review finding

Ticket 104 delivers the core behaviour: configurable signature-word thinness,
thin/asymmetric pair classification, thin page and cluster findings, manifest
counts, and exclusion from duplicate gating. `pages.csv` exposes
`signature_words` and the existing `signal_confidence`, but the task also asked
for signature character length and extracted main-text length so operators can
understand why a high raw `word_count` page was classified as boilerplate-heavy.

## Tasks

- Persist or derive `signature_chars` from `signature_model_input`.
- Expose extracted main-text character and word lengths from crawler-owned data;
  do not decompress full HTML or add an external input surface.
- Add these fields to `pages.csv` and the future Ticket 106 JSON schema.
- Distinguish missing evidence from a measured zero-length signature/main text.
- Include report-shape, boundary, missing-data, and persistence integration tests.
- Re-run the `/videos` calibration sample and document raw word count versus
  signature/main-text diagnostic lengths.

## Definition of Done

Every analysed page can report raw word count, signature words/chars, main-text
words/chars when available, and signal confidence. Existing Ticket 104 risk,
thin-precedence, and `--fail-on duplicate` behaviour remains unchanged; ruff,
formatting, mypy, unit, and PostgreSQL integration tests pass.
