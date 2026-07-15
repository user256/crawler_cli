# Ticket 113: Thin-diagnostic schema + calibration leftovers

**Status:** done (2026-07-15)
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

- [x] Update the Ticket 106 `pages[]` schema contract to include
  `main_text_words`, `main_text_chars`, and `signature_chars` (and keep
  `signature_words` / `word_count` / `signal_confidence`) so the JSON export
  and interactive report consume the same diagnostic surface as `pages.csv`.
- [x] Re-run (or re-read) the thompsons-scotland `/videos` calibration sample and
  document raw `word_count` versus `main_text_*` / `signature_*` diagnostic
  lengths in this ticket or the 109 notes, so operators have a worked example
  of boilerplate-heavy high word-count pages.

## Calibration evidence (thompsons-scotland store, 2026-07-15)

Source: live `thompsons_scotland_co_uk_crawler` Postgres signatures (same crawl
that produced `runs/thompsons-scotland-20260715/`). The on-disk `pages.csv`
from that run predates ticket 109 columns, so lengths below were recomputed
from stored `content.word_count`, `intent_signatures.main_text_compressed`,
and `intent_signatures.signature_model_input` with the same word/char helpers
`pages.csv` uses (`text.split()` / `len(text)`). No reporting bug found.

Hub + category pages share an **identical** signature and extracted main text
(title/h1/meta + site-wide footer disclaimer only — no video body copy). Raw
`word_count` still looks healthy because of chrome/player markup:

| URL path | `word_count` | `main_text_words` | `main_text_chars` | `signature_words` | `signature_chars` | `signal_confidence` |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `/videos` | 1038 | 52 | 360 | 77 | 545 | high |
| `/videos/client-testimonials` | 887 | 52 | 360 | 77 | 545 | high |
| `/videos/faqs` | 823 | 52 | 360 | 77 | 545 | high |
| `/videos/tv-adverts` | 861 | 52 | 360 | 77 | 545 | high |
| `/videos/personal-injury` | 1042 | 52 | 360 | 77 | 545 | high |
| `/videos/data-breach` | 831 | 52 | 360 | 77 | 545 | high |
| `/videos/employment-law` | 855 | 52 | 360 | 77 | 545 | high |
| `/videos/industrial-disease` | 833 | 52 | 360 | 77 | 545 | high |
| `/videos/private-client` | 820 | 52 | 360 | 77 | 545 | high |

Takeaway for operators: contrast `word_count` (820–1042) with
`signature_words` (77) / `main_text_words` (52). The default
`--thin-signature-words 88` threshold sits just above this shared 77-word
boilerplate signature; a naive 40–60 guess would miss the cluster. Prefer
recalibrating per site from these four length columns, not raw `word_count`
alone.

## Definition of Done

Ticket 106's documented page schema lists the new diagnostic fields;
calibration evidence for `/videos` is written down with the four length
columns; no analysis/policy code changes required unless the sample exposes a
real reporting bug.
