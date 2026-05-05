---
name: crawler-cli
description: Use this skill when you need to run a bounded resumable robots-aware crawl from seed URLs or a fixed list, extract canonical or robots or hreflang signals, parse sitemap files, or persist crawl results into PostgreSQL using the reusable crawler_cli package in this repository.
---

# crawler-cli

Use this skill for tasks in this repo that need fetching, extraction, sitemap parsing, or asyncpg persistence.

## When To Use

Use this skill when the task involves any of the following:

- crawl one or more URLs asynchronously
- run a bounded resumable open crawl with a max URL cap
- switch between `aiohttp`, `curl_cffi`, or `playwright` backends
- honor `robots.txt` unless explicitly disabled
- extract canonical, `X-Canonical`, robots, `X-Robots-Tag`, or hreflang signals
- parse `sitemap.xml`, sitemap indexes, `.gz` sitemap files, or `sitemap.txt`
- write normalized crawl results into PostgreSQL with `asyncpg`
- extend the crawler module in `src/crawler_cli/`

## Repo Map

- `src/crawler_cli/backends.py`: fetch backend implementations and rate limiting
- `src/crawler_cli/config.py`: runtime crawler settings
- `src/crawler_cli/engine.py`: async crawl entry points
- `src/crawler_cli/extract.py`: HTML and header extraction logic
- `src/crawler_cli/models.py`: dataclasses for responses and results
- `src/crawler_cli/persistence.py`: asyncpg schema and persistence
- `src/crawler_cli/robots.py`: WIP-derived robots cache and parser
- `src/crawler_cli/sitemap.py`: sitemap path discovery and parsing
- `tests/test_engine.py`: bounded crawl and resume expectations
- `tests/test_extract.py`: extraction expectations
- `tests/test_sitemap.py`: sitemap expectations

## Working Rules

1. Prefer extending the existing dataclasses and modules instead of creating parallel implementations.
2. Keep backend behavior behind `build_backend()` and `CrawlEngine`; do not scatter transport-specific logic across the repo.
3. Open crawl should use the asyncpg store so frontier state survives process restarts.
4. Robots behavior is on by default. Only disable it when the calling task explicitly says to ignore robots.
5. Treat extraction as structured output:
   - HTML canonical comes from `<link rel="canonical">`
   - header canonical comes from `X-Canonical`
   - header robots comes from `X-Robots-Tag`
   - hreflang can come from HTTP `Link` headers, HTML head links, or sitemap alternates
6. Keep sitemap handling in `sitemap.py`; do not bury sitemap parsing inside fetch or engine code.
7. Keep PostgreSQL writes normalized and idempotent with `INSERT ... ON CONFLICT`.

## Typical Patterns

### Crawl a page

```python
from crawler_cli import CrawlConfig, CrawlEngine

engine = CrawlEngine(CrawlConfig(backend="aiohttp"))
result = await engine.crawl("https://example.com")
```

### Parse extracted signals

```python
if result.extracted:
    print(result.extracted.canonical)
    print(result.extracted.x_canonical)
    print(result.extracted.meta_robots.raw)
    print(result.extracted.x_robots_tag.raw)
    print([(item.hreflang, item.href, item.source) for item in result.extracted.hreflang_links])
```

### Persist to PostgreSQL

```python
from crawler_cli import AsyncpgStore, CrawlConfig, CrawlEngine

store = AsyncpgStore("postgresql://user:pass@localhost:5432/crawler_db")
await store.initialize()
engine = CrawlEngine(CrawlConfig(), store=store)
await engine.crawl("https://example.com")
await store.close()
```

### Parse a sitemap

```python
from crawler_cli import SitemapParser

parser = SitemapParser()
document = parser.parse(url, body_bytes, content_type)
```

### Run a bounded open crawl

```python
job = await engine.crawl_open(
    ["https://example.com/"],
    max_urls=200,
    save_to="output/open-crawl.json",
)
```

## Safe Extension Points

- Add new fetch behavior in `backends.py`
- Add new extracted fields in `models.py` and `extract.py`
- Add new sitemap variants in `sitemap.py`
- Add new normalized persistence tables or upserts in `persistence.py`

If you add fields that affect tests, update the relevant test file in `tests/`.

## Validation

Before closing work:

1. Run `python3 -m compileall src`
2. Run `python -m pytest -q` if `pytest` is available
3. If local `pytest` is missing, use the existing populated interpreter if one is available in a sibling repo, or state clearly that tests could not be executed

## Constraints

- Preserve the repo’s narrow modular scope.
- Do not reintroduce the full WIP crawler complexity unless explicitly requested.
- Lift logic from `PostgreSQLCrawlerWIP` wherever possible instead of inventing parallel implementations.
- Keep docs and examples aligned with the actual package API in `src/crawler_cli/`.
