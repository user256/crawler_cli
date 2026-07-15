# Ticket 104: Distinguish thin/boilerplate-dominated pages from true duplicates

## Goal
Pages with little or no *distinguishing* content embed to near-identical
vectors and get labelled `duplicate — decanonicalisation likely`, prescribing
canonical/merge remediation when the actual fix is "add distinguishing
content". Detect signature-thin pages and label their overlap distinctly.

## Background (evidence: thompsons-scotland.co.uk run, 2026-07-15)
- The `/videos` section: hub + category pages + individual video pages all
  pair at **similarity 1.0** despite healthy raw word counts (820–1040) —
  the text is shared template/boilerplate; the video pages have no
  transcript/unique copy. These are not duplicates in intent; they are thin.
  Merging or canonicalising them (what the current label suggests) would be
  wrong.
- The signal already exists but isn't used for labelling:
  `intent_signatures.signal_confidence` is `low` for many of these pages
  (`resolve_signal_confidence`, intent_signature.py:210), pairs carry a
  `low_confidence` flag (17 of 736), and `signature_model_input` /
  `main_text_compressed` lengths directly measure distinguishing content.
  None of this changes the risk label today (intent_overlap.py:430 assigns
  purely by similarity threshold).

## Tasks
- Per-page thinness metrics from stored data: signature text length (chars
  and words of `signature_model_input`), extracted main-text length, and
  `signal_confidence`. Thresholds configurable (suggest
  `--thin-signature-words`, default ~40–60 signature words; calibrate
  against this run where /videos pages should classify thin).
- Label logic: when BOTH sides of a high-similarity pair are thin, the pair
  is `thin` (new column or reuse/replace `low_confidence`); a page whose
  duplicate risk comes only from thin pairs gets risk
  `thin content — add distinguishing content` instead of
  `duplicate — decanonicalisation likely`. Mixed pairs (one thin, one rich)
  keep duplicate risk on the thin side's cluster but note the asymmetry.
- pages.csv gains `signature_words` (and keeps `word_count` for contrast —
  the /videos rows showing wc≈900 but signature_words≈0 is exactly the
  diagnostic story); clusters driven by thin pages carry the thin label in
  clusters.csv.
- `--fail-on duplicate` excludes thin-only pairs from the duplicate count by
  default (they are a content-quality finding, not a decanonicalisation
  emergency) — summary line reports them separately so nothing is hidden.
- Manifest summary: thin page count, thin pair count.
- Tests: thinness classification boundaries, label precedence
  (thin vs duplicate vs overlap), fail-on gating, report shape.

## Definition of Done
- Re-run on the thompsons-scotland store: the /videos cluster reports as
  thin content (not decanonicalisation risk); genuinely duplicate rich pages
  (e.g. the news pair in ticket 105's evidence) keep their duplicate label;
  ruff/mypy/tests green; README threshold-calibration section gains a short
  thin-content note.

## Constraint
100% crawler-powered — thinness is computed from the crawler's own stored
signatures/text. No external input.

## Status
done (2026-07-15, PR #17; remediation 109) — merged in the dependency-ordered review batch. Signature-word thinness, thin/asymmetric pair flags, thin page/cluster labels, configurable calibration, and duplicate-gate exclusion are live. Thin content explicitly wins over time-sequenced policy in the combined implementation. Ticket 109 owns the remaining diagnostic-only fields requested by this ticket (signature characters and extracted main-text length).
