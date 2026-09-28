# Ticket 222: Qualify orphan claims by crawl coverage

## Goal

Stop the audit from stating that a page has no internal links when the crawl
did not fetch every page that could link to it.

## Background

The rainbet run hit its 12,000-URL cap. It fetched about 170 of roughly 7,700
URLs per locale and left link-discovered URLs unfetched. The audit still stated
that 7,104 slot pages had "no internal link", which is only true of the pages
that were crawled. Ticket 178 defines orphans from same-run inlinks but does not
qualify them by coverage.

## Tasks

- Record in the orphan output whether the frontier ended with discovered but
  unfetched URLs, and how many, per template/locale.
- When unfetched sources exist, label orphans `no inlinks from crawled pages`
  and state the unfetched count; reserve `orphan` for complete coverage.
- Surface the qualification in the recipient projection (ticket 197).

- Master already withholds the check on the capped rainbet run
  (`orphan-candidates`: unavailable, `coverage_required`, 2026-09-28). That
  avoids the false claim but also hides a real, qualified finding. Emit the
  qualified inventory instead of nothing.

## Definition of Done

- A capped fixture crawl yields qualified orphan labels with counts.
- A complete fixture crawl yields plain orphan labels.
- The rainbet run reports its orphans as qualified.
