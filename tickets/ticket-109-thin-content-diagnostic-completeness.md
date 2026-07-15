# Ticket 109: Complete thin-content diagnostic evidence

**Status:** done (2026-07-15, PR #21). Schema/calibration leftovers → ticket 113.
**Priority:** P2 reporting
**Depends on:** Ticket 104

## Goal

Complete the diagnostic fields requested by Ticket 104 without changing its
reviewed thin-content labelling or gating policy.

## Done

Shipped in PR #21:

- Stored `main_text` flows through `fetch_analysis_rows` / analysis row load.
- Empty-string signature/main-text evidence is preserved (`is not None` on
  compress) and reported as measured zeros, distinct from missing.
- `pages.csv` adds `main_text_words`, `main_text_chars`, `signature_chars`
  alongside `signature_words` / `word_count` / `signal_confidence`.
- Unit + persistence-integration coverage for report shape and
  missing-vs-zero evidence.
- Thin risk / gating / `--fail-on duplicate` behaviour unchanged.

Leftovers filed as ticket 113: Ticket 106 JSON schema field list, and
`/videos` calibration documentation — completed in ticket 113 (hub/category
sample: `word_count` 820–1042 vs identical `main_text_words=52` /
`main_text_chars=360` / `signature_words=77` / `signature_chars=545`).
