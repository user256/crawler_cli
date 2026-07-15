# Ticket 089: Treat unresolved bot challenges as blocked, never as page content

## Goal
Complete ticket 074's Definition of Done: an unresolved challenge must not be
extracted, persisted, counted as crawled, or used for link discovery.

## Background
The engine detects a challenge and sets `CrawlResult.challenge`, but then still
runs HTML extraction, hashing, CMS/analytics/custom extraction, persistence, and
link enqueueing. Because `skip_reason` stays `None`, the same result increments
both `crawled_count` and `challenge_blocked_count`. The challenge marker is only
serialized to saved output and is not persisted to PostgreSQL, so SQL consumers
cannot distinguish interstitial HTML from genuine content.

This is a regression against ticket 074, whose stated DoD says challenge pages
are recorded as blocked and never stored as content.

## Tasks
- After escalation is exhausted, return a blocked result before any extraction,
  hashing, detector, custom-extraction, or link-discovery work.
- Give unresolved challenges an explicit skip/outcome reason and make job counts
  mutually coherent: blocked challenges are not crawled pages.
- Persist challenge outcome/vendor and fetch metadata without persisting the
  interstitial as the page's current content.
- Ensure a challenge does not overwrite a previously successful page snapshot.
- Include challenge counts in JSONL summaries and downstream reporting.
- Add regressions for extraction suppression, no discovered-link enqueue,
  persistence behavior, counts, and successful escalation.

## Definition of Done
- An unresolved challenge produces no stored content or links and is not counted
  as crawled.
- PostgreSQL and JSONL both retain enough outcome metadata to audit the block.
- Ticket 074's original blocked-content assertions are enforced end to end.

## Status
done (2026-07-15, PR #24) (Priority: **P0**) — unresolved challenges hard-stop before extraction; `skip_reason=bot_challenge`; PostgreSQL `page_metadata.challenge`/`skip_reason` audit without content overwrite; JSONL/job summaries include `challenge_blocked_count`.

