# Ticket 398: Make Q88 match its registry entry and keep untemplated pages in scope

## Goal

Fix a defect found in QA of the merged Stream A, B and C technical-audit work on 2026-10-06, before it reaches master.

## Problem

The registry said Q88 needs only a crawl, but the answerer returned Pending without a site profile. Any timed page matching no profile template made the whole audit incomplete, so Q88 could never be Healthy on a real site. Thresholds in the registry were ignored.

## Evidence

Stream A QA review, finding 5.

## Tasks

- [x] Registry: group crawl+profile, requires site-profile, profile key `templates`, note explaining the 'other' group and the min-samples rule.
- [x] Pages matching no template are timed as one 'other' group.
- [x] p90/p99/min_samples come from the registry threshold.

## Definition of Done

- [x] Q88 answers Healthy or Issue on a profiled run; Pending without a profile as documented.

## Status

implemented (local) (Priority: **P2**). Source: stream integration QA, 2026-10-06.
