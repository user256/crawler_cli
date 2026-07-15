# Repository Delivery State

**Recorded:** 2026-07-15
**Branch:** `master`

## Pull-request triage

- Reviewed and merged PRs #14–#18 in dependency order: #16 (101), #15 (102),
  #18 (103), #17 (104), then #14 (105).
- PR #110 was explicitly excluded and no action was taken on it.
- No actionable PR from the reviewed set was rejected as unsalvageable.
- Tickets 108 and 109 record the two bounded review remediations.

## Combined validation

| Check | Result |
|---|---|
| `ruff check src tests` | Pass |
| `ruff format --check src tests` | Pass |
| `mypy src` | Pass — 38 source files |
| Non-integration pytest suite | Pass — 493 tests, 21 deselected |
| Real Playwright smoke | Pass — 2 tests |
| Local PostgreSQL integration selection | 19 skipped because `CRAWLER_CLI_TEST_DSN` was not configured |
| PR PostgreSQL integration jobs | Pass on each reviewed PR |

The individual PR lint jobs were red only because of a pre-existing format
drift in `obscura_install.py`; PRs #15 and #18 also had formatting-only test
drift. The combined merge formats those files and the final format check passes.

## Review integration decisions

- AMP variants take precedence over the general parameterised-URL class, so
  `?amp=1` pages are not double-counted in parameterised summaries.
- Thin-content risk takes precedence over the time-sequenced editorial policy.
- A normal cross-section overlap remains visible even when the same page has a
  closer time-sequenced match.
- Parent-child duplicate findings remain counted by `--fail-on duplicate` unless
  a higher-priority thin/time-sequenced policy explicitly excludes that pair.

## Remaining known work

- [108](./ticket-108-amp-classification-evidence-hardening.md): replace
  base-exists-only AMP confirmation with authoritative edge/canonical/signature
  evidence and clear stale classifications.
- [109](./ticket-109-thin-content-diagnostic-completeness.md): expose the
  remaining signature-character and extracted-main-text diagnostic lengths.
- The broader active queue and dependency order are in [ROADMAP.md](./ROADMAP.md).

## Local workspace state

- Existing user changes in `uv.lock`, `interface/`, and the two `runs/`
  directories were preserved and were not staged or committed.
- Review worktrees are disposable and are removed after the merge; production
  deployments and external crawl stores were not mutated during this review.
