from __future__ import annotations

import os
from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .models import (
    DiscoveredLink,
    ExtractedContent,
    HreflangLink,
    ImageReference,
    RobotsDirectiveEvidence,
    RobotsDirectives,
)
from .schema import _PARSER, extract_schema_data


def parse_html(html: str) -> BeautifulSoup:
    """Parse *html* with the fastest available parser (lxml if installed).

    Call once per page and pass the result to ``extract_page_data`` and
    ``extract_links`` via their ``soup=`` parameter to avoid duplicate parses
    (ticket-060).
    """
    return BeautifulSoup(html, _PARSER)


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
        noindex="noindex" in directives or "none" in directives,
        nofollow="nofollow" in directives or "none" in directives,
        raw=directives,
    )


_HEADER_ROBOT_NAMES = {
    "baiduspider",
    "bingbot",
    "duckduckbot",
    "googlebot",
    "googlebot-image",
    "googlebot-news",
    "googlebot-video",
    "slurp",
    "yandex",
}


def _directive_tokens(value: str) -> list[str]:
    return [token.strip().lower() for token in value.split(",") if token.strip()]


def _robots_declaration_evidence(soup: BeautifulSoup, headers: dict[str, str]) -> list[RobotsDirectiveEvidence]:
    evidence: list[RobotsDirectiveEvidence] = []
    for tag in soup.find_all("meta", attrs={"name": True, "content": True}):
        name = str(tag.get("name", "")).strip().lower()
        raw = str(tag.get("content", ""))
        is_robot_name = name == "robots" or any(token in name for token in ("bot", "spider", "crawler", "slurp"))
        if is_robot_name and raw.strip():
            evidence.append(
                RobotsDirectiveEvidence("html_meta", "*" if name == "robots" else name, raw, _directive_tokens(raw))
            )
    header = headers.get("x-robots-tag", "")
    if header.strip():
        grouped: dict[str, list[str]] = {}
        active_agent = "*"
        for segment in header.split(","):
            prefix, separator, rest = segment.partition(":")
            if separator and prefix.strip().lower() in _HEADER_ROBOT_NAMES:
                active_agent = prefix.strip().lower()
                segment = rest.strip()
            if segment.strip():
                grouped.setdefault(active_agent, []).append(segment.strip())
        for agent, segments in grouped.items():
            raw = ", ".join(segments)
            evidence.append(RobotsDirectiveEvidence("http_header", agent, raw, _directive_tokens(raw)))
    return evidence


def _rel_tokens(value: object) -> list[str]:
    if isinstance(value, str):
        return [token.strip().lower() for token in value.split() if token.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(token).strip().lower() for token in value if str(token).strip()]
    return []


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _srcset_urls(value: object) -> list[str]:
    urls: list[str] = []
    for candidate in str(value or "").split(","):
        parts = candidate.strip().split(maxsplit=1)
        if not parts:
            continue
        url = parts[0]
        if url:
            urls.append(url)
    return urls


def extract_image_references(soup: BeautifulSoup, base_url: str) -> list[ImageReference]:
    """Extract deduplicated image candidates and accessibility/layout evidence."""
    references: list[ImageReference] = []
    seen: set[tuple[str, str, str]] = set()
    for image in soup.find_all("img"):
        alt_present = image.has_attr("alt")
        alt = str(image.get("alt", "")).strip() if alt_present else None
        common = {
            "alt": alt,
            "alt_present": alt_present,
            "width": _positive_int(image.get("width")),
            "height": _positive_int(image.get("height")),
            "loading": str(image.get("loading", "")).strip().lower() or None,
            "xpath": generate_xpath(image),
        }
        candidates = [("img_src", str(image.get("src", "")).strip())]
        candidates.extend(("img_srcset", url) for url in _srcset_urls(image.get("srcset")))
        for source, raw_url in candidates:
            if not raw_url:
                continue
            url = urljoin(base_url, raw_url)
            if urlparse(url).scheme not in {"http", "https"}:
                continue
            key = (source, url, common["xpath"])
            if key not in seen:
                seen.add(key)
                references.append(ImageReference(url=url, source=source, **common))

    for source_node in soup.find_all("source", srcset=True):
        if source_node.find_parent("picture") is None:
            continue
        fallback = source_node.find_parent("picture").find("img")
        alt_present = bool(fallback and fallback.has_attr("alt"))
        alt = str(fallback.get("alt", "")).strip() if alt_present and fallback else None
        for raw_url in _srcset_urls(source_node.get("srcset")):
            url = urljoin(base_url, raw_url)
            if urlparse(url).scheme not in {"http", "https"}:
                continue
            xpath = generate_xpath(source_node)
            key = ("picture_source", url, xpath)
            if key in seen:
                continue
            seen.add(key)
            references.append(
                ImageReference(
                    url=url,
                    source="picture_source",
                    alt=alt,
                    alt_present=alt_present,
                    width=_positive_int(fallback.get("width")) if fallback else None,
                    height=_positive_int(fallback.get("height")) if fallback else None,
                    loading=str(fallback.get("loading", "")).strip().lower() or None if fallback else None,
                    xpath=xpath,
                )
            )
    return references


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


def extract_page_data(
    html: str,
    base_url: str,
    headers: dict[str, str],
    *,
    soup: BeautifulSoup | None = None,
) -> ExtractedContent:
    """Extract SEO metadata from *html*.

    Pass a pre-parsed *soup* to avoid a redundant parse (ticket-060).
    """
    if soup is None:
        soup = BeautifulSoup(html, _PARSER)
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
    declaration_evidence = _robots_declaration_evidence(soup, header_values)
    x_robots_tag = _parse_directives([item.raw_value for item in declaration_evidence if item.channel == "http_header"])
    # The user-agent-qualified header form is ``googlebot: noindex``; its
    # prefix is metadata, not a directive token.
    x_robots_tag.raw = [
        token for item in declaration_evidence if item.channel == "http_header" for token in item.directives
    ]

    canonical = None
    canonical_tag = soup.find("link", attrs={"rel": lambda value: "canonical" in _rel_tokens(value)})
    if canonical_tag and canonical_tag.get("href"):
        canonical = urljoin(base_url, canonical_tag["href"].strip())

    x_canonical = header_values.get("x-canonical")
    if x_canonical:
        x_canonical = urljoin(base_url, x_canonical.strip())

    # AMP variant edge (ticket 103): mirror the canonical extraction for
    # <link rel="amphtml" href=...>.  This is the authoritative page->AMP
    # pairing signal and was previously dropped at extraction time.
    amphtml = None
    amphtml_tag = soup.find("link", attrs={"rel": lambda value: "amphtml" in _rel_tokens(value)})
    if amphtml_tag and amphtml_tag.get("href"):
        amphtml = urljoin(base_url, amphtml_tag["href"].strip())

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
        amphtml=amphtml,
        hreflang_links=hreflang_links,
        html_lang=soup.html.get("lang") if soup.html else None,
        headings=headings,
        text=text,
        word_count=len(words),
        metadata={
            "meta_names": sorted(
                {tag.get("name", "").strip().lower() for tag in soup.find_all("meta") if tag.get("name")}
            ),
        },
        image_references=extract_image_references(soup, base_url),
        robots_directive_evidence=declaration_evidence,
        schema_data=extract_schema_data(html, base_url, soup=soup),
    )


def generate_xpath(element: Tag) -> str:
    path: list[str] = []
    current: Tag | None = element
    while current and current.name:
        tag = current.name
        if current.parent:
            siblings = [s for s in current.parent.find_all(tag, recursive=False) if s.name == tag]
            if len(siblings) > 1:
                tag = f"{tag}[{siblings.index(current) + 1}]"
        path.insert(0, tag)
        current = current.parent if isinstance(current.parent, Tag) else None
    return "/" + "/".join(path) if path else ""


def _anchor_text_for_link(anchor: Tag, href: str) -> str | None:
    anchor_text = anchor.get_text(strip=True)
    if not anchor_text:
        img = anchor.find("img")
        if img:
            alt_text = img.get("alt", "").strip()
            if alt_text:
                anchor_text = f"[IMG: {alt_text}]"
            else:
                src = img.get("src", "")
                if src:
                    filename = os.path.basename(src)
                    if filename:
                        anchor_text = f"[IMG: {filename}]"
    if not anchor_text and anchor.get("title"):
        anchor_text = f"[TITLE: {anchor.get('title', '').strip()}]"
    if not anchor_text and anchor.get("aria-label"):
        anchor_text = f"[ARIA: {anchor.get('aria-label', '').strip()}]"
    if not anchor_text and href.startswith("#"):
        anchor_text = f"[ANCHOR: {href[1:]}]"
    return anchor_text or None


def extract_links(
    html: str,
    base_url: str,
    *,
    same_host_only: bool = True,
    allowed_hosts: set[str] | None = None,
    soup: BeautifulSoup | None = None,
) -> list[DiscoveredLink]:
    """Return all http(s) links found in *html*.

    Pass a pre-parsed *soup* to avoid a redundant parse when the caller has
    already parsed the document (ticket-060).  Host filtering is kept minimal
    here so the engine remains the single scope authority (ticket-058).
    """
    if soup is None:
        soup = BeautifulSoup(html, _PARSER)
    base_host = urlparse(base_url).netloc.lower()
    # Build the effective host allowlist:
    # - same_host_only=False → no host filter at all (effective_allowed=None)
    # - same_host_only=True, no allowed_hosts → only the base host
    # - same_host_only=True, allowed_hosts given → base host + the extra set
    if not same_host_only:
        effective_allowed: set[str] | None = None
    elif allowed_hosts:
        effective_allowed = {base_host} | {h.lower() for h in allowed_hosts}
    else:
        effective_allowed = {base_host}
    links: list[DiscoveredLink] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        raw_href = anchor["href"].strip()
        original_href = urljoin(base_url, raw_href)
        parsed = urlparse(original_href)
        if parsed.scheme not in {"http", "https"}:
            continue
        link_host = parsed.netloc.lower()
        if effective_allowed is not None and link_host not in effective_allowed:
            continue
        normalized = parsed._replace(fragment="").geturl()
        if normalized in seen:
            continue
        seen.add(normalized)
        anchor_text = _anchor_text_for_link(anchor, raw_href)
        links.append(
            DiscoveredLink(
                href=normalized,
                anchor_text=anchor_text,
                xpath=generate_xpath(anchor),
                is_image=bool(anchor_text and anchor_text.startswith("[IMG:")),
                fragment=parsed.fragment or None,
                url_parameters=parsed.query or None,
                original_href=original_href,
            )
        )
    return links
