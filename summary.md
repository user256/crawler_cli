# crawler_cli summary

`crawler_cli` is an async, resumable, SEO-focused crawler with PostgreSQL persistence and a CLI for crawling, comparison, and enrichment workflows.

## Current Scope

- Bounded, resumable open crawling from seed URLs
- Fixed-list crawling from CLI URLs or CSV ingestion
- Robots-aware fetch behavior with crawl-delay support
- Multi-backend fetching via `aiohttp`, `curl_cffi`, and `playwright`
- Extraction of SEO-relevant signals (canonical, robots directives, hreflang, headings, metadata)
- Sitemap discovery and parsing (including index, gzipped, and text sitemap variants)
- Normalized PostgreSQL persistence for crawl state and extracted entities

## Implemented Expansion Features

Recent completed tickets expanded the core crawler into a broader technical audit platform:

- **Schema extraction**: JSON-LD, Microdata, and RDFa extraction with persistence
- **Advanced link analysis**: richer internal link graph coverage, including anchor and structural data
- **Path restrictions**: include and exclude path controls for targeted crawl segments
- **Vector embeddings**: embedding generation pipeline for crawl content
- **CSV + auth CLI support**: CSV URL ingestion plus HTTP authentication options
- **Deep crawl comparison**: multi-signal comparison between crawl snapshots
- **Persistence performance fixes**: race-condition mitigation and higher-throughput database writes
- **Session crawl logic fixes**: improved crawl limits and session-level behavior

## CLI Surface

Primary command families:

- `crawl`: run bounded/resumable crawls with optional JS rendering
- `generate-embeddings`: create vector embeddings for stored crawl content
- `compare`: compare crawl outputs for regressions and drift

The CLI defaults to `crawl` when a URL is passed directly.

## Architecture Notes

- `engine.py` orchestrates async crawl flow, queueing, and orchestration logic
- `backends.py` encapsulates transport/render backends and rate control
- `extract.py` and `models.py` define extraction logic and normalized data shapes
- `persistence.py` handles schema setup and idempotent upsert persistence
- `compare_renders.py` and `comparison.py` provide render and crawl diff analysis

## Test Coverage Areas

Current tests cover major expansion areas, including:

- CMS detection
- Deep comparison behavior
- CSV/auth workflows
- Embeddings logic
- Link analysis
- Path restriction behavior
- Schema extraction and handling

## Near-Term Proposed Enhancements

- Playwright memory bounding and context recycling (`ticket-034`)
- Redis-backed frontier queue for higher concurrency (`ticket-035`)
