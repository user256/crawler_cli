from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .javascript_urls import _classify, _normalise_http_url, url_like_junk_reason
from .models import CssSourceKind, CssTokenKind, CssUrlCandidate

_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_CSS_IMPORT_RE = re.compile(
    r"@import\s+(?:url\(\s*)?(?P<quote>['\"]?)(?P<value>[^'\"\s);]+)(?P=quote)\s*\)?",
    re.IGNORECASE,
)
_CSS_URL_RE = re.compile(
    r"url\(\s*(?P<quote>['\"]?)(?P<value>(?:\\.|[^'\"\)])+?)(?P=quote)\s*\)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class InlineCss:
    index: int
    source: str
    source_kind: CssSourceKind = "inline_style"


@dataclass(frozen=True, slots=True)
class CssToken:
    value: str
    token_kind: CssTokenKind
    occurrence_count: int = 1


def extract_css_sources(
    soup: BeautifulSoup,
    base_url: str,
    *,
    max_external_stylesheets: int,
    include_style_attributes: bool,
) -> tuple[list[InlineCss], list[str]]:
    """Return bounded inline CSS and linked HTTP(S) stylesheet URLs."""
    inline: list[InlineCss] = []
    for index, node in enumerate(soup.find_all("style")):
        if not isinstance(node, Tag):
            continue
        body = node.string if node.string is not None else node.get_text()
        if body and body.strip():
            inline.append(InlineCss(index=index, source=str(body)))
    if include_style_attributes:
        offset = len(inline)
        for index, node in enumerate(soup.find_all(style=True), start=offset):
            if not isinstance(node, Tag):
                continue
            value = str(node.get("style", "")).strip()
            if value:
                inline.append(InlineCss(index=index, source=value, source_kind="style_attribute"))

    external: list[str] = []
    seen: set[str] = set()
    for node in soup.find_all("link"):
        if not isinstance(node, Tag):
            continue
        rel = node.get("rel")
        if rel is None:
            continue
        rel_values = {str(item).lower() for item in (rel if isinstance(rel, list) else str(rel).split())}
        if "stylesheet" not in rel_values:
            continue
        href = str(node.get("href", "")).strip()
        if not href:
            continue
        resolved = _normalise_http_url(urljoin(base_url, href))
        if resolved is None or resolved in seen:
            continue
        if len(external) >= max_external_stylesheets:
            break
        seen.add(resolved)
        external.append(resolved)
    return inline, external


def _decode_css_escapes(value: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "\\" or index + 1 >= len(value):
            out.append(value[index])
            index += 1
            continue
        index += 1
        start = index
        while index < len(value) and index - start < 6 and value[index] in "0123456789abcdefABCDEF":
            index += 1
        if index > start:
            with_value = int(value[start:index], 16)
            if with_value:
                out.append(chr(with_value))
            if index < len(value) and value[index].isspace():
                index += 1
            continue
        out.append(value[index])
        index += 1
    return "".join(out)


def scan_css_tokens(
    source: str,
    *,
    max_tokens: int | None = None,
    rejection_counts: dict[str, int] | None = None,
) -> list[CssToken]:
    """Extract bounded, deduplicated CSS ``url()`` and ``@import`` tokens."""
    clean = _CSS_COMMENT_RE.sub("", source)
    aggregated: dict[tuple[str, CssTokenKind], int] = {}
    import_spans: list[tuple[int, int]] = []

    def add(raw_value: str, kind: CssTokenKind) -> bool:
        value = _decode_css_escapes(raw_value.strip())
        if not value:
            return False
        reason = url_like_junk_reason(value)
        if reason is not None:
            if rejection_counts is not None:
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            return False
        key = (value, kind)
        aggregated[key] = aggregated.get(key, 0) + 1
        return max_tokens is not None and len(aggregated) >= max_tokens

    for match in _CSS_IMPORT_RE.finditer(clean):
        import_spans.append(match.span())
        if add(match.group("value"), "import"):
            break
    if max_tokens is None or len(aggregated) < max_tokens:
        for match in _CSS_URL_RE.finditer(clean):
            if any(start <= match.start() < end for start, end in import_spans):
                continue
            if add(match.group("value"), "url"):
                break
    return [
        CssToken(value=value, token_kind=kind, occurrence_count=count) for (value, kind), count in aggregated.items()
    ]


def resolve_css_tokens(
    tokens: list[CssToken],
    base_url: str,
    *,
    source_kind: CssSourceKind,
    stylesheet_source: str,
    style_index: int | None,
) -> list[CssUrlCandidate]:
    candidates: list[CssUrlCandidate] = []
    resolution_base = "document" if source_kind in {"inline_style", "style_attribute"} else "asset"
    for token in tokens:
        resolved = _normalise_http_url(urljoin(base_url, token.value))
        if resolved is None:
            continue
        classification = _classify(resolved)
        candidates.append(
            CssUrlCandidate(
                url=resolved,
                source_kind=source_kind,
                stylesheet_source=stylesheet_source,
                style_index=style_index,
                token_kind=token.token_kind,
                classification=classification,
                follow_eligible=classification == "page",
                occurrence_count=token.occurrence_count,
                resolution_base=resolution_base,  # type: ignore[arg-type]
            )
        )
    return candidates


def css_content_type_supported(content_type: str | None, url: str) -> bool:
    if content_type:
        return content_type.lower().split(";", 1)[0].strip() == "text/css"
    from urllib.parse import urlparse

    return urlparse(url).path.lower().endswith(".css")
