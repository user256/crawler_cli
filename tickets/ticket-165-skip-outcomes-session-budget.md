# Ticket 165: Clarify and fix `--max-pages` vs skip outcomes

## Goal
Stop robots/challenge (and similar) skips from silently burning the session
`--max-pages` budget, or document and expose an explicit attempts budget if
that is the intended semantics.

## Background (2026-07-22 wiring audit)

In `crawl_open`, `_flush_completed` always does `session_crawled += 1` for
non-retry outcomes, including any `skip_reason` (`engine.py`). The loop stops
on `limit - session_crawled`. Ticket **062** excluded transient retries from
the budget; skips still count.

Claim-time path skips (`should_crawl_url` false) do **not** increment
`session_crawled` — so robots deny and path-exclude are inconsistent.

There is a second budget layer: `_remaining_frontier_budget` and discovered-link
enqueue subtract `queued + pending + done`. A terminal skip is marked `done`, so
it can still consume the run-global frontier cap even if it stops incrementing
`session_crawled`. Sitemap discovery also trims candidates to that frontier
budget before any page outcome is known. Changing only the session counter will
therefore not implement a content budget.

On heavily robots-blocked or challenged sites, a `--max-pages 200` crawl can
stop after ~200 skips with few (or zero) content pages, while the summary
still looks like a “completed” bounded crawl.

## Design decision (pick one, implement consistently)
1. **Content budget (preferred default):** only successful content fetches
   (no `skip_reason`, not challenge-blocked) count toward `--max-pages`. Pair
   this with a separately named/configurable terminal-attempt safety bound so a
   sitemap containing millions of denied URLs cannot create an unbounded crawl.
2. **Attempts budget:** every terminal frontier outcome counts; document
   clearly and surface separate “crawled content” vs “attempts” in the summary.

## Tasks
- Implement the chosen rule across both session scheduling and run-global
  frontier accounting (`_remaining_frontier_budget`, sitemap trim, and
  discovered-link enqueue), not only `session_crawled`.
- Under the content-budget choice, add a finite attempts/skips safety mechanism
  with explicit CLI/help semantics; do not turn `--max-pages 200` into an
  unbounded robots-denial scan.
- Handle crawl-time and claim-time skips consistently, including frontier
  terminal state and summary counters.
- Update CLI help + README so operators know what `--max-pages` means.
- Summary / job result counts distinguish attempts vs crawled content if both
  matter.
- Tests: N robots denies still allow N content pages under the content-budget
  rule (or the documented attempts behaviour).

## Definition of Done
- Budget semantics are explicit in CLI help and README.
- Claim-time and crawl-time skips follow the same rule.
- Automated coverage for robots-deny / challenge-skip vs `max_pages`.
- A sitemap/frontier regression proves skipped `done` rows do not prevent the
  requested number of content pages, while the attempts safety bound still
  terminates an all-skipped crawl.
- No change to unlimited (`--max-pages 0`) behaviour beyond the chosen rule.

## Status
proposed (Priority: **P1**) — crawl correctness; found in 2026-07-22 audit.
