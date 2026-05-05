import gzip

from crawler_cli.sitemap import SitemapParser, discover_sitemap_paths, validate_sitemap_path


def test_validate_sitemap_path_rejects_parent_segments():
    assert validate_sitemap_path("/sitemap.xml") is True
    assert validate_sitemap_path("sitemap.xml") is False
    assert validate_sitemap_path("/nested/../sitemap.xml") is False


def test_discover_sitemap_paths_uses_default_candidates():
    paths = discover_sitemap_paths("https://example.com")
    assert paths == [
        "https://example.com/sitemap.xml",
        "https://example.com/sitemap_index.xml",
        "https://example.com/sitemap.txt",
    ]


def test_parse_xml_sitemap_with_hreflang_and_gzip():
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
            xmlns:xhtml="http://www.w3.org/1999/xhtml">
      <url>
        <loc>https://example.com/</loc>
        <lastmod>2026-05-05</lastmod>
        <xhtml:link rel="alternate" hreflang="fr-fr" href="https://example.com/fr/" />
      </url>
    </urlset>
    """
    parser = SitemapParser()
    document = parser.parse("https://example.com/sitemap.xml.gz", gzip.compress(xml), "application/x-gzip")

    assert document.kind == "sitemap"
    assert document.urls[0].loc == "https://example.com/"
    assert document.urls[0].lastmod == "2026-05-05"
    assert document.urls[0].hreflang_links[0].hreflang == "fr-fr"


def test_parse_sitemap_txt():
    parser = SitemapParser()
    document = parser.parse(
        "https://example.com/sitemap.txt",
        b"https://example.com/\nhttps://example.com/about\n",
        "text/plain",
    )

    assert document.kind == "text"
    assert [item.loc for item in document.urls] == [
        "https://example.com/",
        "https://example.com/about",
    ]
