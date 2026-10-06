# Ticket 221: Flag locale pages that reuse default-locale metadata

## Goal

Report locale alternates whose title or meta description is identical to the
default-locale page, separately from body-content similarity.

## Background

On rainbet.com 498 crawled locale pages reused the English title and meta
description, concentrated on hubs, promotions and static pages, while body
copy was largely translated (only about 3% near-identical by SimHash). The
metadata inventory in ticket 190 does not compare alternates.

## Tasks

- Pair each locale page with its default-locale alternate using hreflang
  clusters, falling back to locale-prefix path mapping.
- Report identical title, identical description, and body-similarity distance
  as separate fields, grouped by template and locale.
- Exclude brand-only titles and legitimately shared strings through a
  configurable allowlist.
- Qualify results by locale crawl coverage.

## Definition of Done

- Fixtures separate metadata reuse from body duplication.
- Output includes per-locale coverage denominators.
- The rainbet run reproduces the hub/static concentration.
