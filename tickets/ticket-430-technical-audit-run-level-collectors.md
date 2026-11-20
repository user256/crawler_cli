# Ticket 430: technical-audit leaves four run-level checks unavailable on every run

## Problem

On a normal, complete open crawl (`uisge-audit-20261120c`, 4,490 URLs),
`technical-audit` reports these contract checks as `unavailable` with
"The deterministic collector for this control did not run":

- `audit-run-integrity` (needs only crawl/job metadata, which `run_context`
  already holds: run ID, status, timestamps, scope, frontier counts)
- `url-host-and-variants` (legacy `url-variants-and-soft-404`)
- `robots-controls`
- `sitemap-integrity` (legacy `current-robots-and-sitemaps`)

None of them is in `_IMPLEMENTED_CHECK_REPORTS`, so `_complete_contract_checks`
always fills them with `_unavailable_contract_check`. Before PR #118 (ticket
409), `technical-audit` had opt-in `--fetch-current-robots-sitemaps` (ticket
192) and `--probe-url-variants` (ticket 193) collectors that fed the legacy
IDs. PR #118 dropped both flags and `url_variant_audit.py`.
`current_site_files.py` is still there and is used only by `reconcile-sources
--fetch-current-sitemaps`. The `_collect_run_current_site_files` docstring
still names the removed flag.

The question runner answers the related questions (Q1–Q4, Q26, Q70, Q93, Q96…)
from observation bundles, but the `technical-audit` JSON and workbook show
these controls as never collected.

## Tasks

- [ ] Decide the intended home for each check: restore collectors in
      `technical-audit`, or mark them as answered by the question runner, with a
      pointer to the producing command instead of "collector did not run".
- [ ] Implement `audit-run-integrity` from `technical_audit_context()`. It
      needs no network.
- [ ] Re-attach current robots and sitemap collection (the
      `current_site_files` producer) so `robots-controls` and `sitemap-integrity`
      can be `complete` on an open crawl, and fix the stale docstring.
- [ ] Decide what to do about URL-variant/soft-404 probes (ticket 193's
      collector was removed).
- [ ] Tests on a saved fixture run with no network.

## Related: orphan-candidates on the same run

The audit at `runs/uisge-20261120/technical-audit.json` lists all 3,695
sitemap URLs (homepage included) as orphan candidates. That audit was produced
by the stale `feature/technical-audit-183` checkout that the main `.venv`
runs. That checkout is 136 commits behind `origin/master`, and its
`orphan_pages` is `frontier.parent_id IS NULL`, so every sitemap-seeded URL is
an orphan. Master's graph-based `orphan_pages` returns **0** candidates for
the same run. No code change is needed. Rerun the audit from master.
