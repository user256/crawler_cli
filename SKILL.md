---
name: crawler-cli
description: Use this skill when you need to run a bounded resumable robots-aware crawl from seed URLs or a fixed list, extract canonical or robots or hreflang signals, parse sitemap files, or persist crawl results into PostgreSQL using the reusable crawler_cli package in this repository.
---

# crawler-cli

Use this skill for tasks in this repo that need fetching, extraction, sitemap parsing, or asyncpg persistence.

## What This Is / What This Is Not

"Adversarial crawler" is used for three different things, and only the third
describes this repository.

1. **An evasion crawler** rotates identities to defeat bot management and keeps
   scraping against the site's rules. This is not that.
2. **A security-testing or pentest scanner** injects payloads, forces its way to
   hidden endpoints, or manipulates identifiers to reach other users' data. This
   is not that either.
3. **An evidence crawler for technical SEO** — what `crawler_cli` is. It does
   not trust the CMS. It observes what a site actually serves and compares
   independent sources of evidence: HTML against HTTP headers, both against the
   sitemaps, one client against a second client, and the raw response against a
   rendered one. Disagreements are recorded as candidates for manual review. It
   honours `robots.txt` and crawl-delay by default and is meant to be run on
   sites the operator is authorised to fetch.

### This product is

- An authorised technical-SEO evidence crawler.
- A client that distrusts CMS claims and compares independent evidence sources.
- A passive and bounded exposure and configuration inventory tool.
- A safe differential measurement tool over exact operator-supplied inputs.
- A crawler that is expected to protect both the target site and its own
  execution host.

### This product is not

- A bot that changes identity or egress until a blocked request returns 200.
- A CAPTCHA solver or a WAF-specific bypass toolkit.
- A scanner that injects SQL, XSS, SSTI, command, path-traversal, or SSRF
  payloads.
- A forced-browsing, credential-stuffing, IDOR/BOLA mutation, or
  privilege-escalation tool.
- A system that treats a spoofed search-engine User-Agent as evidence of how
  the real search engine treats the site.

### Out of scope

Never build, and never document as a feature:

- Rotating user agents or IP addresses *in order to*
  evade rate limits or bot management.
- WAF or CAPTCHA solving as a goal.
- Crawling in spite of `Disallow` as the happy path.
- Injection, XSS, IDOR, credential stuffing, or hidden-admin fuzzing.

The dual-use flags (`--impersonate`, `--obscura-stealth`, `--custom-ua`,
`--ignore-robots`, the proxy flags, and challenge escalation) exist for
authorised measurement of how a CDN or origin treats a browser-like client. They
are not a bypass kit, and a spoofed search-engine User-Agent is not evidence of
how that search engine actually treats the site. Challenge escalation may make
one alternate-egress attempt from a proxy pool the authorised crawl had already
selected; it is never a loop that keeps trying identities until a 200.

Use "observe", "inventory", "compare", "candidate", and "manual review" in code
comments, docs, and reports. Avoid "bypass", "beat", "exploit", and "prove
vulnerable".

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
