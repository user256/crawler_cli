from __future__ import annotations

import gzip
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse

from defusedxml import ElementTree as ET

from .models import HreflangLink, SitemapDocument, SitemapUrl


SITEMAP_XML_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
SITEMAP_XHTML_NS = {"xhtml": "http://www.w3.org/1999/xhtml"}
DEFAULT_SITEMAP_PATHS = (
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap.txt",
)


def validate_sitemap_path(path: str) -> bool:
    parsed = urlparse(path)
    target = parsed.path if parsed.scheme else path
    if not target.startswith("/"):
        return False
    normalized = PurePosixPath(target)
    return ".." not in normalized.parts


def discover_sitemap_paths(base_url: str) -> list[str]:
    discovered: list[str] = []
    for path in DEFAULT_SITEMAP_PATHS:
        if validate_sitemap_path(path):
            discovered.append(urljoin(base_url, path))
    return discovered


def _inflate_if_gzip(body: bytes, url: str, content_type: str | None) -> bytes:
    if url.lower().endswith(".gz") or (content_type and "gzip" in content_type.lower()):
        return gzip.decompress(body)
    return body


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


@dataclass(slots=True)
class SitemapParser:
    def parse(self, url: str, body: bytes, content_type: str | None = None) -> SitemapDocument:
        inflated = _inflate_if_gzip(body, url, content_type)
        if url.lower().endswith(".txt") or (content_type and content_type.lower().startswith("text/plain")):
            return self._parse_text(url, inflated.decode("utf-8", errors="replace"))
        return self._parse_xml(url, inflated.decode("utf-8", errors="replace"))

    def _parse_text(self, url: str, text: str) -> SitemapDocument:
        urls = [
            SitemapUrl(loc=line.strip())
            for line in text.splitlines()
            if line.strip() and line.strip().startswith(("http://", "https://"))
        ]
        return SitemapDocument(url=url, kind="text", urls=urls)

    def _parse_xml(self, url: str, xml_text: str) -> SitemapDocument:
        root = ET.fromstring(xml_text.encode("utf-8"))
        root_name = _strip_namespace(root.tag).lower()
        if root_name == "sitemapindex":
            children = []
            for node in root.findall(".//sm:sitemap/sm:loc", SITEMAP_XML_NS):
                if node.text:
                    children.append(node.text.strip())
            return SitemapDocument(url=url, kind="sitemap_index", children=children)

        urls: list[SitemapUrl] = []
        for url_node in root.findall(".//sm:url", SITEMAP_XML_NS):
            loc_node = url_node.find("sm:loc", SITEMAP_XML_NS)
            if loc_node is None or not loc_node.text:
                continue
            hreflangs = []
            for alt in url_node.findall("xhtml:link", SITEMAP_XHTML_NS):
                if alt.get("rel") != "alternate":
                    continue
                hreflang = alt.get("hreflang")
                href = alt.get("href")
                if hreflang and href:
                    hreflangs.append(HreflangLink(hreflang=hreflang.lower(), href=href, source="sitemap"))
            lastmod_node = url_node.find("sm:lastmod", SITEMAP_XML_NS)
            urls.append(
                SitemapUrl(
                    loc=loc_node.text.strip(),
                    lastmod=lastmod_node.text.strip() if lastmod_node is not None and lastmod_node.text else None,
                    hreflang_links=hreflangs,
                )
            )
        return SitemapDocument(url=url, kind="sitemap", urls=urls)
