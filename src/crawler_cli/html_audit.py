"""Deterministic raw-HTML checks used by the technical-audit reports.

The crawler's normal extraction deliberately keeps only the values needed by
the crawl.  These checks inspect the saved source as well, because duplicate
or misplaced head elements cannot be recovered from the normalised fields.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .schema import _PARSER


_LANG = re.compile(r"^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$")
_BODY = re.compile(r"<body\b[^>]*>(.*?)</body\s*>", re.IGNORECASE | re.DOTALL)
# A <title> or rel=alternate link is head-only only outside SVG/MathML (icons
# carry their own <title>) and, for alternates, only when it is an hreflang link
# (RSS and Atom feed alternates may appear in the body).
_HEAD_ONLY_IN_BODY = re.compile(
    r"<(?:title\b|meta\b[^>]*(?:name\s*=\s*['\"]?(?:robots|googlebot)|property\s*=\s*['\"]?robots)|"
    r"link\b[^>]*rel\s*=\s*['\"]?[^'\">]*\bcanonical\b|link\b[^>]*\bhreflang\s*=)",
    re.IGNORECASE,
)
_FOREIGN_CONTENT = re.compile(r"<(svg|math)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)


def _normalise_url(value: str) -> str:
    parsed = urlsplit(value)
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def _rel_tokens(value: object) -> set[str]:
    if isinstance(value, str):
        return {token.casefold() for token in value.split() if token}
    if isinstance(value, list):
        return {str(token).casefold() for token in value if str(token)}
    return set()


def canonical_targets(url: str, html: str) -> list[str]:
    """Return absolute canonical targets in document order from saved source."""
    soup = BeautifulSoup(html, _PARSER)
    return [
        urljoin(url, str(node.get("href", "")).strip())
        for node in soup.find_all("link")
        if "canonical" in _rel_tokens(node.get("rel")) and str(node.get("href", "")).strip()
    ]


def inspect_stored_html(url: str, html: str) -> list[dict[str, object]]:
    """Return reproducible finding rows for one saved HTML response.

    This intentionally reports only conditions that can be known from the
    response source.  Template intent, accessibility quality and live Google
    behaviour remain separate checks.
    """

    soup = BeautifulSoup(html, _PARSER)
    findings: list[dict[str, object]] = []

    def finding(kind: str, **evidence: object) -> None:
        findings.append({"url": url, "kind": kind, **evidence})

    html_node = soup.find("html")
    html_lang = str(html_node.get("lang", "")).strip() if html_node else ""
    if not html_lang:
        finding("missing-html-lang")
    elif not _LANG.fullmatch(html_lang):
        finding("invalid-html-lang", html_lang=html_lang)

    canonicals = [node for node in soup.find_all("link") if "canonical" in _rel_tokens(node.get("rel"))]
    if not canonicals:
        finding("missing-canonical")
    elif len(canonicals) > 1:
        finding("duplicate-canonical", count=len(canonicals))
    for node in canonicals:
        href = str(node.get("href", "")).strip()
        if href and urlsplit(href).scheme not in {"http", "https"}:
            finding("relative-canonical", canonical=href)

    titles = [node for node in soup.find_all("title") if node.find_parent(("svg", "math")) is None]
    if len(titles) > 1:
        finding("duplicate-title", count=len(titles))
    descriptions = [
        node for node in soup.find_all("meta") if str(node.get("name", "")).strip().casefold() == "description"
    ]
    if len(descriptions) > 1:
        finding("duplicate-meta-description", count=len(descriptions))
    robots = [
        node
        for node in soup.find_all("meta")
        if str(node.get("name", "")).strip().casefold() in {"robots", "googlebot"}
    ]
    if len(robots) > 1:
        finding("duplicate-meta-robots", count=len(robots))

    body_match = _BODY.search(html)
    if body_match and _HEAD_ONLY_IN_BODY.search(_FOREIGN_CONTENT.sub(" ", body_match.group(1))):
        finding("head-only-element-in-body")

    headings = [(int(node.name[1]), node.get_text(" ", strip=True)) for node in soup.find_all(re.compile(r"^h[1-6]$"))]
    h1_count = sum(1 for level, _text in headings if level == 1)
    if h1_count == 0:
        finding("missing-h1")
    elif h1_count > 1:
        finding("multiple-h1", count=h1_count)
    previous: int | None = None
    for level, text in headings:
        if previous is not None and level > previous + 1:
            finding("heading-level-skip", previous_level=previous, level=level, heading=text)
            break
        previous = level

    own_url = _normalise_url(url)
    self_hreflangs = []
    for node in soup.find_all("link"):
        if "alternate" not in _rel_tokens(node.get("rel")) or not node.has_attr("hreflang"):
            continue
        target = str(node.get("href", "")).strip()
        if target and _normalise_url(urljoin(url, target)) == own_url:
            self_hreflangs.append(str(node.get("hreflang", "")).strip())
    for hreflang in self_hreflangs:
        if html_lang and _LANG.fullmatch(html_lang) and hreflang and _LANG.fullmatch(hreflang):
            if html_lang.split("-", 1)[0].casefold() != hreflang.split("-", 1)[0].casefold():
                finding("html-lang-self-hreflang-mismatch", html_lang=html_lang, hreflang=hreflang)

    return findings
