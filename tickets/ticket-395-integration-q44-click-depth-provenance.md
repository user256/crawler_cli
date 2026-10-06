# Ticket 395: Trust frontier depth for Q44 only when it is click depth from a homepage

## Goal

Fix a defect found in QA of the merged Stream A, B and C technical-audit work on 2026-10-06, before it reaches master.

## Problem

Stream A read `frontier.depth` as click depth. The engine enqueues every sitemap-discovered URL at depth 0 and frontier inserts are ON CONFLICT DO NOTHING, so depth is first-discovery depth. The answerer then declared every depth-0 row a root and `depths_from_roots=True`, so the crawl-depth module's root verification could never fire and a sitemap-seeded run answered Q44 Healthy.

## Evidence

Stream A QA review, blocker 1. Rainbet run: 11,999 frontier rows, sitemap-seeded.

## Tasks

- [x] Exclude speculative frontier rows from the report.
- [x] Treat depths as click depths only when the run recorded zero sitemap-sourced URLs and every depth-0 URL is a homepage; otherwise say why and keep Q44 below Healthy.
- [x] Read `max_depth` from the registry threshold.
- [x] Follow-up: compute a real homepage BFS over the run's link graph so sitemap-seeded crawls can be answered.

## Definition of Done

- [x] Sitemap-seeded or non-homepage-rooted runs answer Needs validation with the reason.
- [x] Link crawls from the homepage still answer Healthy/Issue.

## Status

implemented (local); BFS follow-up open (Priority: **P1**). Source: stream integration QA, 2026-10-06.
