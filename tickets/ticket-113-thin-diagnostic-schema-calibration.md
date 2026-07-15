# Ticket 113: Thin-diagnostic schema + calibration leftovers

**Status:** proposed (2026-07-15 MERGE+REMEDIATE from ticket 109 / PR #21)
**Priority:** P3 reporting
**Depends on:** Ticket 109 (done)
**Related:** Ticket 106

## Goal

Finish the two non-blocking DoD items from ticket 109 now that
`pages.csv` exposes the diagnostic length fields.

## Background

PR #21 (ticket 109) carries stored `main_text` through analysis rows, preserves
empty-string signature/main-text evidence as measured zeros (distinct from
missing), and adds `main_text_words`, `main_text_chars`, and `signature_chars`
alongside `signature_words` in `pages.csv`. Thin risk / gating policy is
unchanged. Two ticket-109 tasks remain:

## Tasks

- Update the Ticket 106 `pages[]` schema contract to include
  `main_text_words`, `main_text_chars`, and `signature_chars` (and keep
  `signature_words` / `word_count` / `signal_confidence`) so the JSON export
  and interactive report consume the same diagnostic surface as `pages.csv`.
- Re-run (or re-read) the thompsons-scotland `/videos` calibration sample and
  document raw `word_count` versus `main_text_*` / `signature_*` diagnostic
  lengths in this ticket or the 109 notes, so operators have a worked example
  of boilerplate-heavy high word-count pages.

## Definition of Done

Ticket 106's documented page schema lists the new diagnostic fields;
calibration evidence for `/videos` is written down with the four length
columns; no analysis/policy code changes required unless the sample exposes a
real reporting bug.
