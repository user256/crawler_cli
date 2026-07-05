"""Ticket 030: XML sitemap generation."""

from xml.etree import ElementTree as ET

from crawler_cli.sitemap_generate import (
    render_sitemap_index,
    render_urlset,
    write_sitemap,
)

NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def test_render_urlset_valid_xml():
    xml = render_urlset(["https://example.com/", "https://example.com/about"])
    root = ET.fromstring(xml)
    assert root.tag == f"{NS}urlset"
    locs = [el.text for el in root.iter(f"{NS}loc")]
    assert locs == ["https://example.com/", "https://example.com/about"]


def test_render_urlset_escapes_ampersands():
    xml = render_urlset(["https://example.com/?a=1&b=2"])
    root = ET.fromstring(xml)  # would raise if & were unescaped
    assert root.find(f"{NS}url/{NS}loc").text == "https://example.com/?a=1&b=2"


def test_render_sitemap_index_valid_xml():
    xml = render_sitemap_index(["https://example.com/sitemap-1.xml"])
    root = ET.fromstring(xml)
    assert root.tag == f"{NS}sitemapindex"
    assert root.find(f"{NS}sitemap/{NS}loc").text == "https://example.com/sitemap-1.xml"


def test_write_single_file(tmp_path):
    out = tmp_path / "sitemap.xml"
    written = write_sitemap(["https://example.com/"], out)
    assert written == [out]
    root = ET.fromstring(out.read_text())
    assert root.tag == f"{NS}urlset"


def test_write_splits_into_index(tmp_path):
    out = tmp_path / "sitemap.xml"
    urls = [f"https://example.com/p{i}" for i in range(5)]
    written = write_sitemap(urls, out, base_url="https://example.com", max_urls_per_file=2)

    # index + 3 child files (2 + 2 + 1)
    assert len(written) == 4
    assert written[0] == out

    index_root = ET.fromstring(out.read_text())
    assert index_root.tag == f"{NS}sitemapindex"
    child_locs = [el.text for el in index_root.iter(f"{NS}loc")]
    assert child_locs == [
        "https://example.com/sitemap-1.xml",
        "https://example.com/sitemap-2.xml",
        "https://example.com/sitemap-3.xml",
    ]

    # all 5 URLs spread across the children, none lost
    all_urls: list[str] = []
    for child in written[1:]:
        croot = ET.fromstring(child.read_text())
        all_urls.extend(el.text for el in croot.iter(f"{NS}loc"))
    assert sorted(all_urls) == sorted(urls)


def test_write_index_loc_falls_back_to_filename(tmp_path):
    out = tmp_path / "sitemap.xml"
    urls = [f"https://example.com/p{i}" for i in range(3)]
    write_sitemap(urls, out, max_urls_per_file=2)
    index_root = ET.fromstring(out.read_text())
    child_locs = [el.text for el in index_root.iter(f"{NS}loc")]
    assert child_locs == ["sitemap-1.xml", "sitemap-2.xml"]
