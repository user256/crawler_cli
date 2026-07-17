# Ticket 123: Compare/compare-urls remediations from the ticket-122 review

## Goal
Close out the correctness and completeness findings from the 2026-07-17 review
of PR #47 (ticket 122) that were not fixed pre-merge. Two behavioural bugs and
a set of smaller hygiene items.

## Background — review findings (2026-07-17, PR #47)

Two headline bugs **were fixed on the PR branch before merge** (commit 67d8ebf):
root-URL trailing-slash normalization in `normalize_url_for_match`, and
source-side pair resolution matching by `final_url` (chained mappings
misattributed redirect verdicts). This ticket owns everything else the review
surfaced.

## Tasks

### A. P2 — flag-less `compare` behaviour change (hash recompute fallback)
`comparison._content_hashes` now recomputes sha256/simhash from `raw_html`
whenever stored hashes are absent — including on a flag-less `compare` of
artifacts crawled without `--content-hashing`, where master reported zero
`content_hash_mismatches`. This contradicts the 122 DoD line "existing compare
behaviour unchanged when no new flags are passed" and silently adds a
BeautifulSoup normalization pass per page — **twice** per mismatching row,
since `compare_deep` re-calls `_content_hashes` for both sides
(`comparison.py:244`) after `content_comparison` already computed them.
- Decide: gate the recompute behind `--replace`/`--simhash-threshold`, or keep
  it and document the change; either way compute once per row, not twice.

### B. P2 — `--replace` silently no-op for store-loaded compare sides
`fetch_pages_for_comparison` reconstructs rows with `raw_html=None, text=""`,
so `Remap.rehash` returns `(None, None)` and the compare falls back to the
**un-remapped stored hashes**: a store-backed side with `--replace` can never
verdict `identical` and its simhash distance is host noise — defeating the
"no host-derived false positives" DoD for exactly the store-backed workflow
the README advertises.
- Minimum: loud warning when a remap is active and a side fell back to stored
  hashes. Better: load `html_compressed` from the store so rehash is real.

### C. P3 — smaller items
- No test exercises `persist_comparison_session` with the new
  `content_verdict`/`simhash_distance` columns, nor `compare-urls --persist`.
- CSV `--output` omits the redirect hops (JSON has them; ticket 122 said the
  report must include them) and appends `"(N hop)"` into the
  `source_final_url` value — put hops in their own column, keep URLs clean.
- `--fail-on` trips return `EXIT_VALIDATION` (2), indistinguishable from bad
  CLI arguments — use a distinct exit code for CI gates.
- Identity mappings (source == target, no redirect expected) always verdict
  `no_redirect` and fail `--fail-on redirect_mismatch`; support them (e.g.
  verdict `no_redirect_expected`/`ok` when source == target).
- Missing `--source-artifact`/`--target-artifact` file raises an uncaught
  `FileNotFoundError` traceback (the pairs CSV is handled cleanly).
- `compare` given both a positional baseline JSON and `--baseline-store`
  silently ignores the JSON — error or document precedence.
- `hamming64` guards `None` with `assert` (stripped under `python -O`).
- Scope correction recorded: ticket 122 task B listed "hreflang diffs", but no
  hreflang comparison exists anywhere in the compare path (the ticket's
  background overstated current state); add one or strike it explicitly.

## Definition of Done
- Flag-less `compare` on hash-less artifacts matches pre-122 output, or the
  new recompute is documented + single-pass.
- Store-backed side with `--replace` either rehashes real HTML or warns loudly.
- Persisted-session shape test covers the new columns; `--persist` exercised.
- CSV output carries redirect hops without mangling `source_final_url`.
- ruff / mypy / tests green.

## Status
open (2026-07-17) — filed from the PR #47 review.
