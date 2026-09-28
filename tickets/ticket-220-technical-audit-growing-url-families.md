# Ticket 220: Detect growing internal URL families from repeated observations

## Goal

Identify unbounded internal URL spaces by route and parameter family, and only
claim growth when repeated, timestamped observations show it.

## Background

rainbet.com links to live-bet results with a unique `betId` (74,625 unique
URLs, 16% of internal links), plus auth and search modals and demo links. The
tracking-parameter report covers only analytics parameters. The audit claimed
the bet-ID family "grows with every bet" without measuring it, which the skill
forbids.

## Tasks

- Group internal link targets by path template and parameter-key set,
  normalising high-cardinality values (UUIDs, long integers, hashes).
- For each family report unique targets, link instances, source pages, share
  of internal links, and target status/canonical/indexability.
- Add a bounded re-observation step: refetch a fixed sample of source pages
  after a configured interval and record new and vanished identifiers with
  timestamps.
- Only label a family `growing` when the re-observation shows new identifiers;
  otherwise `high-cardinality, growth unmeasured`.

## Definition of Done

- Fixtures cover UUID, integer and hash identifiers.
- Growth labels appear only with two timestamped observations.
- The rainbet run groups the betId, modal, search and play families correctly.
