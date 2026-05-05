from __future__ import annotations

from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .models import ExtractedContent, HreflangLink, RobotsDirectives


def _header_map(headers: dict[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


def _parse_directives(raw_values: Iterable[str]) -> RobotsDirectives:
    directives: list[str] = []
    for value in raw_values:
        if not value:
            continue
        for token in value.split(","):
            normalized = token.strip().lower()
            if normalized:
                directives.append(normalized)
    return RobotsDirectives(
        noindex="noindex" in directives,
        nofollow="nofollow" in directives,
        raw=directives,
    )


def _rel_tokens(value: object) -> list[str]:
    if isinstance(value, str):
        return [token.strip().lower() for token in value.split() if token.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(token).strip().lower() for token in value if str(token).strip()]
    return []


def _extract_header_hreflang(headers: dict[str, str], base_url: str) -> list[HreflangLink]:
    link_header = _header_map(headers).get("link")
    if not link_header:
        return []

    hreflangs: list[HreflangLink] = []
    for chunk in link_header.split(","):
        parts = [part.strip() for part in chunk.split(";") if part.strip()]
        if not parts or not parts[0].startswith("<") or not parts[0].endswith(">"):
            continue
        href = parts[0][1:-1]
        attrs: dict[str, str] = {}
        for part in parts[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                attrs[key.strip().lower()] = value.strip().strip('"')
        if attrs.get("rel", "").lower() != "alternate":
            continue
        hreflang = attrs.get("hreflang")
        if hreflang:
            hreflangs.append(
                HreflangLink(
                    hreflang=hreflang.lower(),
                    href=urljoin(base_url, href),
                    source="http_header",
                )
            )
    return hreflangs


def extract_page_data(html: str, base_url: str, headers: dict[str, str]) -> ExtractedContent:
    soup = BeautifulSoup(html, "html.parser")
    header_values = _header_map(headers)

    title = soup.title.string.strip() if soup.title and soup.title.string else None
    meta_description = None
    meta_description_tag = soup.find("meta", attrs={"name": lambda value: value and value.lower() == "description"})
    if meta_description_tag and meta_description_tag.get("content"):
        meta_description = meta_description_tag["content"].strip() or None

    meta_robots_values = [
        tag.get("content", "")
        for tag in soup.find_all(
            "meta",
            attrs={"name": lambda value: value and value.lower() in {"robots", "googlebot", "bingbot"}},
        )
    ]
    meta_robots = _parse_directives(meta_robots_values)
    x_robots_tag = _parse_directives([header_values.get("x-robots-tag", "")])

    canonical = None
    canonical_tag = soup.find("link", attrs={"rel": lambda value: "canonical" in _rel_tokens(value)})
    if canonical_tag and canonical_tag.get("href"):
        canonical = urljoin(base_url, canonical_tag["href"].strip())

    x_canonical = header_values.get("x-canonical")
    if x_canonical:
        x_canonical = urljoin(base_url, x_canonical.strip())

    hreflang_links = _extract_header_hreflang(headers, base_url)
    for link in soup.find_all("link", href=True):
        rel = _rel_tokens(link.get("rel"))
        if "alternate" not in rel:
            continue
        hreflang = link.get("hreflang")
        if hreflang:
            hreflang_links.append(
                HreflangLink(
                    hreflang=hreflang.lower(),
                    href=urljoin(base_url, link["href"].strip()),
                    source="html_head",
                )
            )

    headings = {
        "h1": [node.get_text(" ", strip=True) for node in soup.find_all("h1") if node.get_text(" ", strip=True)],
        "h2": [node.get_text(" ", strip=True) for node in soup.find_all("h2") if node.get_text(" ", strip=True)],
    }
    text = soup.get_text(" ", strip=True)
    words = [token for token in text.split() if token]

    return ExtractedContent(
        title=title,
        meta_description=meta_description,
        meta_robots=meta_robots,
        x_robots_tag=x_robots_tag,
        canonical=canonical,
        x_canonical=x_canonical,
        hreflang_links=hreflang_links,
        html_lang=soup.html.get("lang") if soup.html else None,
        headings=headings,
        text=text,
        word_count=len(words),
        metadata={
            "meta_names": sorted(
                {
                    tag.get("name", "").strip().lower()
                    for tag in soup.find_all("meta")
                    if tag.get("name")
                }
            ),
        },
    )


def extract_links(html: str, base_url: str, *, same_host_only: bool = True) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlparse(base_url).netloc.lower()
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, anchor["href"].strip())
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"}:
            continue
        normalized = parsed._replace(fragment="").geturl()
        if same_host_only and parsed.netloc.lower() != base_host:
            continue
        if normalized not in seen:
            seen.add(normalized)
            links.append(normalized)
    return links
