"""XML sitemap generation from a completed crawl (ticket 030).

Queries the database for indexable, self-canonical, 200-OK HTML URLs and renders
standard ``sitemap.xml`` output, automatically splitting into a sitemap index
when the URL count exceeds the per-file limit (50,000 per the sitemaps.org spec).
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
MAX_URLS_PER_FILE = 50_000


# Indexable, self-canonical (or no canonical), final status 200, HTML URLs.
# A URL is excluded when it canonicalises to a *different* URL.
INDEXABLE_URLS_QUERY = """
    SELECT u.url
    FROM urls u
    JOIN page_metadata pm ON pm.url_id = u.id
    LEFT JOIN indexability i ON i.url_id = u.id
    WHERE u.kind = 'html'
      AND pm.final_status_code = 200
      AND (i.overall_indexable IS NULL OR i.overall_indexable = TRUE)
      AND NOT EXISTS (
          SELECT 1 FROM canonical_urls c
          WHERE c.url_id = u.id AND c.canonical_url_id <> u.id
      )
    ORDER BY u.url
"""


async def fetch_indexable_urls(store) -> list[str]:
    """Return the sorted list of sitemap-eligible URLs from the store."""
    assert store.pool is not None
    async with store.pool.acquire() as conn:
        rows = await conn.fetch(INDEXABLE_URLS_QUERY)
    return [row["url"] for row in rows]


def render_urlset(urls: list[str]) -> str:
    """Render a single ``<urlset>`` sitemap document."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', f'<urlset xmlns="{SITEMAP_NS}">']
    for url in urls:
        lines.append(f"  <url><loc>{escape(url)}</loc></url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def render_sitemap_index(sitemap_urls: list[str]) -> str:
    """Render a ``<sitemapindex>`` referencing child sitemap files."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', f'<sitemapindex xmlns="{SITEMAP_NS}">']
    for url in sitemap_urls:
        lines.append(f"  <sitemap><loc>{escape(url)}</loc></sitemap>")
    lines.append("</sitemapindex>")
    return "\n".join(lines) + "\n"


def _chunk(urls: list[str], size: int) -> list[list[str]]:
    return [urls[i : i + size] for i in range(0, len(urls), size)] or [[]]


def write_sitemap(
    urls: list[str],
    output_path: str | Path,
    *,
    base_url: str | None = None,
    max_urls_per_file: int = MAX_URLS_PER_FILE,
) -> list[Path]:
    """Write sitemap file(s) to ``output_path``.

    When ``urls`` fits in one file a single ``<urlset>`` is written to
    ``output_path``. Otherwise the URLs are split into ``output_path``-derived
    child files (``<stem>-1.xml``, ``<stem>-2.xml``, ...) and ``output_path``
    becomes a ``<sitemapindex>`` referencing them. ``base_url`` is used to build
    the absolute ``<loc>`` for child sitemaps in the index (falls back to the
    bare filename when not provided).

    Returns the list of files written (index first when applicable).
    """
    output_path = Path(output_path)
    written: list[Path] = []

    if len(urls) <= max_urls_per_file:
        output_path.write_text(render_urlset(urls), encoding="utf-8")
        return [output_path]

    chunks = _chunk(urls, max_urls_per_file)
    child_locs: list[str] = []
    stem = output_path.stem
    suffix = output_path.suffix or ".xml"
    for idx, chunk in enumerate(chunks, start=1):
        child_name = f"{stem}-{idx}{suffix}"
        child_path = output_path.with_name(child_name)
        child_path.write_text(render_urlset(chunk), encoding="utf-8")
        written.append(child_path)
        loc = f"{base_url.rstrip('/')}/{child_name}" if base_url else child_name
        child_locs.append(loc)

    output_path.write_text(render_sitemap_index(child_locs), encoding="utf-8")
    return [output_path, *written]
