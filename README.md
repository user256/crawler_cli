# crawler_cli

`crawler_cli` is a reusable async crawler module extracted from `PostgreSQLCrawler` and narrowed into a smaller package for resumable bounded crawling, extraction, sitemap parsing, robots-aware fetch control, and asyncpg persistence.

## What It Does

- Fetch pages with:
  - `aiohttp`
  - `curl_cffi`
  - `playwright`
- Crawl asynchronously with:
  - `asyncio`
  - `Semaphore`-based concurrency control
  - simple per-request rate limiting
  - bounded open crawl from one or more seed URLs
  - resumable PostgreSQL-backed frontier state
  - default robots.txt enforcement
- Extract:
  - HTML title, description, headings, lang, text, word count
  - canonical from HTML
  - `X-Canonical` from HTTP headers
  - robots directives from `<meta name="robots">`
  - `X-Robots-Tag` from HTTP headers
  - hreflang from `Link` headers
  - hreflang from HTML `<link rel="alternate">`
- Parse sitemaps:
  - `sitemap.xml`
  - sitemap indexes
  - `.gz` sitemap files
  - `sitemap.txt`
- Detect CMS platforms:
  - WordPress, Shopify, Drupal, Joomla, Squarespace, Wix
  - Pattern-based detection via headers, meta tags, and content
  - Configurable detection with confidence scoring
- Persist normalized crawl data into PostgreSQL with `asyncpg`

## Install

Base install:

```bash
pip install -e .
```

With Playwright support:

```bash
pip install -e ".[playwright]"
playwright install chromium
```

For tests:

```bash
pip install -e ".[test]"
```

## CLI Usage

```bash
python -m crawler_cli https://www.example.com \
  --max-workers 15 --concurrency 20 --js \
  --archive-org-check --custom-ua "...Googlebot..."
```

Or via the installed entry point:

```bash
crawler-cli https://www.example.com --max-pages 500 --skip-sitemaps
```

Connection can be configured via environment variables (`PostgreSQLCrawler_POSTGRES_*` or `CRAWLER_CLI_POSTGRES_*`) or CLI flags. CLI flags override env vars.

## Package Layout

```text
src/crawler_cli/
  __init__.py
  __main__.py
  archive.py
  backends.py
  compare_renders.py
  config.py
  engine.py
  extract.py
  hashing.py
  models.py
  persistence.py
  probes.py
  robots.py
  sitemap.py
  variants.py
```

## Default Behavior

- `robots.txt` is checked and honored by default
- host `Crawl-delay` is honored when present unless you disable it
- open crawl is intended to be bounded, with a default upper limit of `200` URLs
- open crawl is expected to use PostgreSQL-backed frontier state so it can resume
- this package is expected to be used by other scripts for:
  - crawling a fixed list of URLs
  - resumable bounded open crawl from a seed set
  - saving crawl output and returning structured results

To bypass robots explicitly:

```python
config = CrawlConfig(respect_robots_txt=False)
```

## Basic Crawl Example

```python
import asyncio

from crawler_cli import CrawlConfig, CrawlEngine


async def main() -> None:
    config = CrawlConfig(
        backend="aiohttp",
        max_concurrency=5,
        rate_limit_per_second=2.0,
        user_agent="crawler_cli/0.1",
    )
    engine = CrawlEngine(config)

    result = await engine.crawl("https://example.com")

    print(result.status)
    print(result.final_url)
    print(result.extracted.title if result.extracted else None)
    print(result.extracted.canonical if result.extracted else None)


asyncio.run(main())
```

## Crawl A Defined List

```python
import asyncio

from crawler_cli import AsyncpgStore, CrawlConfig, CrawlEngine


async def main() -> None:
    store = AsyncpgStore("postgresql://crawler_user:secret@localhost:5432/crawler_db")
    await store.initialize()

    engine = CrawlEngine(
        CrawlConfig(
            backend="curl_cffi",
            max_concurrency=10,
            rate_limit_per_second=5.0,
        ),
        store=store,
    )

    job = await engine.crawl_list(
        [
            "https://example.com",
            "https://example.com/about",
            "https://example.com/contact",
        ],
        save_to="output/list-crawl.json",
    )

    for result in job.results:
        print(result.requested_url, result.status)

    await store.close()


asyncio.run(main())
```

## Use Playwright

Use this for pages that need JS rendering.

```python
from crawler_cli import CrawlConfig, CrawlEngine

config = CrawlConfig(
    backend="playwright",
    timeout_seconds=45,
    max_concurrency=2,
    rate_limit_per_second=1.0,
)
engine = CrawlEngine(config)
```

## Extracted Data Shape

Each crawl returns a `CrawlResult` dataclass. The main fields are:

- `requested_url`
- `final_url`
- `status`
- `headers`
- `content_type`
- `fetch_backend`
- `raw_html`
- `extracted`

`extracted` contains:

- `title`
- `meta_description`
- `meta_robots`
- `x_robots_tag`
- `canonical`
- `x_canonical`
- `hreflang_links`
- `html_lang`
- `headings`
- `text`
- `word_count`
- `metadata`

## Sitemap Example

```python
from crawler_cli import SitemapParser, discover_sitemap_paths

paths = discover_sitemap_paths("https://example.com")
print(paths)

parser = SitemapParser()
document = parser.parse(
    "https://example.com/sitemap.txt",
    b"https://example.com/\nhttps://example.com/about\n",
    "text/plain",
)

print(document.kind)
print([item.loc for item in document.urls])
```

## PostgreSQL Persistence Example

```python
import asyncio

from crawler_cli import AsyncpgStore, CrawlConfig, CrawlEngine


async def main() -> None:
    store = AsyncpgStore("postgresql://crawler_user:secret@localhost:5432/crawler_db")
    await store.initialize()

    engine = CrawlEngine(
        CrawlConfig(backend="aiohttp"),
        store=store,
    )

    await engine.crawl("https://example.com")
    await store.close()


asyncio.run(main())
```

The store initializes and writes the main normalized tables used by the extracted module:

- `urls`
- `pages`
- `content`
- `robots_directives`
- `canonical_urls`
- `hreflang_http_header`
- `hreflang_html_head`
- `hreflang_sitemap`
- `page_metadata`
- `indexability`
- `frontier`
- `crawl_metadata`

## Open Crawl With Upper Limit

```python
import asyncio

from crawler_cli import AsyncpgStore, CrawlConfig, CrawlEngine


async def main() -> None:
    store = AsyncpgStore("postgresql://crawler_user:secret@localhost:5432/crawler_db")
    await store.initialize()

    engine = CrawlEngine(
        CrawlConfig(
            backend="aiohttp",
            max_concurrency=5,
            default_open_crawl_limit=200,
            same_host_only=True,
        ),
        store=store,
    )

    job = await engine.crawl_open(
        ["https://example.com/"],
        max_urls=200,
        save_to="output/open-crawl.json",
    )

    print(job.crawled_count)
    print(job.blocked_count)

    await store.close()


asyncio.run(main())
```

## URL Variant Probes

Test canonicalisation of trailing-slash, suffix, and case variants:

```python
from crawler_cli import generate_variants, probe_variant

variants = generate_variants("https://example.com/about")
for v in variants:
    result = await probe_variant(engine, "https://example.com/about", v)
    print(v.kind, result.verdict)
```

## Render Parity (JS vs No-JS)

```python
from crawler_cli import compare_renders, CrawlConfig

result = await compare_renders(
    "https://example.com/",
    nojs_config=CrawlConfig(backend="aiohttp"),
    js_config=CrawlConfig(backend="playwright"),
)
print(result.verdict)  # ok, nav_js_injected, content_js_only, meta_drift
```

## Soft-404 Detection

```python
from crawler_cli import soft_404_fingerprint

fp = await soft_404_fingerprint(engine, "https://example.com")
print(fp.status, fp.simhash)
```

## Robots.txt Introspection

```python
from crawler_cli import RobotsPolicyCache, CrawlConfig

cache = RobotsPolicyCache(CrawlConfig())
decision = await cache.check("https://example.com/wp-admin/")
print(decision.allowed, decision.matched_rule, decision.matched_user_agent)
```

## Archive.org Audit

```python
from crawler_cli import audit_archive_urls, CrawlConfig

result = await audit_archive_urls("example.com", store, CrawlConfig())
print(len(result.missing_urls), len(result.legacy_issues))
```

## Run Tests

```bash
python -m pytest -q
```
