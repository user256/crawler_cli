"""Deterministic HTML signals for technical-audit questions.

One stored raw-HTML page goes in; one JSON-serialisable record comes out. The
extractor never fetches anything and never consults the database, so the same
``(url, html, site_hosts)`` always yields the same record.

What the record does not claim:

* It reads the HTML as served. Nothing a script adds or removes at runtime is
  seen, and external stylesheets are not loaded, so ``font_face_rules`` only
  covers inline ``<style>`` blocks.
* ``head_blocking_stylesheets`` and ``head_sync_scripts`` are markup-level
  candidates, not measured render-blocking time.
* ``spam_matches`` and ``hidden_links`` are pattern hits for a human to review,
  not a verdict that the page is compromised.
* ``tracking_preloads`` only recognises the vendors in
  ``TRACKING_PRELOAD_PATTERNS``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from bs4.element import Comment, Declaration, Doctype, ProcessingInstruction, Tag

from .schema import _PARSER

HTML_SIGNALS_VERSION = "crawler-cli/html-signals/1"

# Entries containing "/" or ending in ".js" match anywhere in the URL; the rest
# are host suffixes.
TRACKING_PRELOAD_PATTERNS: tuple[str, ...] = (
    "googletagmanager.com",
    "google-analytics.com",
    "analytics.js",
    "gtag/js",
    "gtm.js",
    "connect.facebook.net",
    "static.hotjar.com",
    "clarity.ms",
    "cdn.segment.com",
    "plausible.io",
    "js.hs-analytics.net",
    "snap.licdn.com",
    "analytics.tiktok.com",
    "cdn.mxpnl.com",
)

SPAM_PATTERNS: dict[str, tuple[str, ...]] = {
    "pharma": (
        "viagra",
        "cialis",
        "levitra",
        "buy tramadol",
        "xanax without prescription",
        "cheap pills",
    ),
    "essay": (
        "essay writing service",
        "write my essay",
        "buy essay online",
        "paper writing service",
    ),
    "crypto_scam": (
        "double your bitcoin",
        "crypto giveaway",
        "send btc and receive",
        "guaranteed crypto returns",
    ),
    "casino_spam": (
        "slot gacor",
        "judi online",
        "situs slot",
        "agen togel",
        "bandar togel",
        "slot88",
    ),
}

_IGNORED_SCHEMES = frozenset({"javascript", "mailto", "tel", "data", "about", "blob", "sms"})
_WEB_SCHEMES = frozenset({"http", "https"})
_JS_TYPES = frozenset(
    {"", "text/javascript", "application/javascript", "module", "text/ecmascript", "application/ecmascript"}
)
_INVISIBLE_TEXT_TAGS = frozenset({"script", "style", "noscript", "template"})
_UNFOLLOWED_RELS = frozenset({"nofollow", "sponsored", "ugc"})
_MEDIA_SRC_TAGS = ("script", "iframe", "video", "audio", "source", "track", "embed")

_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_FONT_FACE = re.compile(r"@font-face\s*\{([^}]*)\}", re.IGNORECASE)
_FONT_FAMILY = re.compile(r"font-family\s*:\s*([^;]*)", re.IGNORECASE)
_FONT_DISPLAY = re.compile(r"font-display\s*:\s*([^;]*)", re.IGNORECASE)
_HIDING_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden"
    r"|font-size\s*:\s*0+(?:\.0+)?\s*(?:px|em|rem|pt|%)?\s*(?:!\s*important\s*)?(?:;|$)",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"\s+")


def page_html_signals(url: str, html: str, *, site_hosts: Iterable[str] = ()) -> dict[str, object]:
    """Extract audit signals from one page's raw HTML.

    ``site_hosts`` widens what counts as internal beyond the page's own host;
    hosts compare case-insensitively with a leading ``www.`` ignored. Every
    href/src/action is resolved against the page URL (or its ``<base href>``).
    """
    soup = BeautifulSoup(html or "", _PARSER)
    page_parts = _split(url)
    is_https = bool(page_parts) and page_parts.scheme.lower() == "https"
    hosts = {_host_key(page_parts.hostname if page_parts else None)}
    hosts.update(_host_key(_site_host(entry)) for entry in site_hosts)
    hosts.discard("")
    base = _base_url(soup, url)

    def resolve(raw: object) -> str | None:
        return _resolve(base, raw)

    def is_site(parts) -> bool:
        return _host_key(parts.hostname) in hosts

    anchors: list[tuple[Tag, str]] = []
    for tag in soup.find_all("a", href=True):
        resolved = resolve(tag.get("href"))
        if resolved:
            anchors.append((tag, resolved))

    insecure_internal: list[str] = []
    followed_external: list[str] = []
    hidden_links: list[str] = []
    hidden_cache: dict[int, bool] = {}
    for tag, resolved in anchors:
        parts = _split(resolved)
        if not parts or parts.scheme not in _WEB_SCHEMES or not parts.hostname:
            continue
        if is_site(parts):
            if is_https and parts.scheme == "http":
                insecure_internal.append(resolved)
            continue
        if not (_rel_tokens(tag) & _UNFOLLOWED_RELS):
            followed_external.append(resolved)
        if _is_hidden(tag, hidden_cache):
            hidden_links.append(resolved)

    footer_links: list[str] = []
    for container in soup.find_all(_is_footer_container):
        for tag in container.find_all("a", href=True):
            resolved = resolve(tag.get("href"))
            parts = _split(resolved) if resolved else None
            if parts and parts.scheme in _WEB_SCHEMES:
                footer_links.append(resolved)

    links = soup.find_all("link")
    tracking_preloads: list[str] = []
    preconnect_origins: list[str] = []
    hreflang_alternates: list[str] = []
    font_preloads = 0
    page_key = _compare_key(url)
    for tag in links:
        rel = _rel_tokens(tag)
        resolved = resolve(tag.get("href"))
        if rel & {"preload", "modulepreload"}:
            if "preload" in rel and _attr(tag, "as").lower() == "font":
                font_preloads += 1
            if resolved and _is_tracking(resolved):
                tracking_preloads.append(resolved)
        if "preconnect" in rel and resolved:
            origin = _origin(resolved)
            if origin:
                preconnect_origins.append(origin)
        if "alternate" in rel and tag.has_attr("hreflang") and resolved:
            if _compare_key(resolved) != page_key:
                hreflang_alternates.append(resolved)
    hreflang_alternates = _dedupe(hreflang_alternates)
    anchor_keys = {_compare_key(resolved) for _, resolved in anchors}
    linked_alternates = [href for href in hreflang_alternates if _compare_key(href) in anchor_keys]

    head = soup.head
    head_stylesheets: list[str] = []
    head_scripts: list[str] = []
    if head is not None:
        for tag in head.find_all("link"):
            if "stylesheet" not in _rel_tokens(tag) or tag.has_attr("disabled"):
                continue
            if _attr(tag, "media").lower() == "print":
                continue
            resolved = resolve(tag.get("href"))
            if resolved:
                head_stylesheets.append(resolved)
        for tag in head.find_all("script", src=True):
            if tag.has_attr("async") or tag.has_attr("defer"):
                continue
            script_type = _attr(tag, "type").lower()
            if script_type == "module" or script_type not in _JS_TYPES:
                continue
            resolved = resolve(tag.get("src"))
            if resolved:
                head_scripts.append(resolved)

    font_rules, fonts_without_swap = _font_faces(soup)

    return {
        "url": url,
        "is_https": is_https,
        "mixed_content": _mixed_content(soup, resolve) if is_https else [],
        "insecure_internal_links": _dedupe(insecure_internal),
        "forms": _forms(soup, url, resolve),
        "tracking_preloads": _dedupe(tracking_preloads),
        "font_face_rules": font_rules,
        "font_faces_without_swap": fonts_without_swap,
        "font_preloads": font_preloads,
        "head_blocking_stylesheets": _dedupe(head_stylesheets),
        "head_sync_scripts": _dedupe(head_scripts),
        "preconnect_origins": _dedupe(preconnect_origins),
        "spam_matches": _spam_matches(soup),
        "hidden_links": _dedupe(hidden_links),
        "hreflang_alternates": hreflang_alternates,
        "linked_alternates": linked_alternates,
        "followed_external_links": _dedupe(followed_external),
        "footer_links": _dedupe(footer_links),
    }


def _mixed_content(soup: BeautifulSoup, resolve) -> list[dict[str, str]]:
    found: list[tuple[str, str, str]] = []

    def check(tag_name: str, attribute: str, raw: object) -> None:
        resolved = resolve(raw)
        if resolved and resolved.startswith("http://"):
            found.append((tag_name, attribute, resolved))

    for tag in soup.find_all(["img", "source"]):
        if tag.has_attr("src"):
            check(tag.name, "src", tag.get("src"))
        if tag.has_attr("srcset"):
            for candidate in _srcset_urls(_attr(tag, "srcset")):
                check(tag.name, "srcset", candidate)
    for tag in soup.find_all(_MEDIA_SRC_TAGS):
        if tag.name != "source" and tag.has_attr("src"):
            check(tag.name, "src", tag.get("src"))
    for tag in soup.find_all("link", href=True):
        if _rel_tokens(tag) & {"stylesheet", "preload", "modulepreload"}:
            check("link", "href", tag.get("href"))
    for tag in soup.find_all("object", data=True):
        check("object", "data", tag.get("data"))
    return [{"tag": tag, "attribute": attribute, "url": href} for tag, attribute, href in _dedupe(found)]


def _forms(soup: BeautifulSoup, page_url: str, resolve) -> list[dict[str, object]]:
    forms: list[dict[str, object]] = []
    for tag in soup.find_all("form"):
        action = _attr(tag, "action")
        method = _attr(tag, "method").strip().lower() or "get"
        stripped = action.strip()
        if not stripped:
            resolved = _resolve(page_url, page_url) or ""
        elif _scheme_of(stripped) in {"javascript", "mailto"}:
            resolved = ""
        else:
            resolved = resolve(stripped) or ""
        forms.append(
            {
                "action": action,
                "resolved_action": resolved,
                "method": method,
                "insecure": resolved.startswith("http://"),
            }
        )
    return forms


def _font_faces(soup: BeautifulSoup) -> tuple[int, list[dict[str, object]]]:
    count = 0
    without_swap: list[dict[str, object]] = []
    for style in soup.find_all("style"):
        css = _CSS_COMMENT.sub("", style.get_text() or "")
        for block in _FONT_FACE.finditer(css):
            count += 1
            body = block.group(1)
            family_match = _FONT_FAMILY.search(body)
            family = _css_value(family_match.group(1)).strip("'\"").strip() if family_match else ""
            display_match = _FONT_DISPLAY.search(body)
            display = _css_value(display_match.group(1)).lower() if display_match else None
            if not display or display == "block":
                without_swap.append({"family": family, "font_display": display or None})
    return count, without_swap


def _spam_matches(soup: BeautifulSoup) -> list[dict[str, str]]:
    root = soup.body or soup
    pieces: list[str] = []
    for text in root.find_all(string=True):
        if isinstance(text, (Comment, Declaration, Doctype, ProcessingInstruction)):
            continue
        if text.parent is not None and text.find_parent(_INVISIBLE_TEXT_TAGS) is not None:
            continue
        pieces.append(text)
    visible = _WHITESPACE.sub(" ", " ".join(pieces)).casefold()
    if not visible.strip():
        return []
    matches: list[dict[str, str]] = []
    for category, terms in SPAM_PATTERNS.items():
        for term in terms:
            words = [re.escape(word) for word in term.casefold().split()]
            if words and re.search(r"(?<!\w)" + r"\s+".join(words) + r"(?!\w)", visible):
                matches.append({"category": category, "term": term})
    return matches


def _is_hidden(tag: Tag, cache: dict[int, bool]) -> bool:
    chain: list[Tag] = []
    node: Tag | None = tag
    result = False
    while isinstance(node, Tag) and node.name != "[document]":
        known = cache.get(id(node))
        if known is not None:
            result = known
            break
        chain.append(node)
        if node.has_attr("hidden") or _HIDING_STYLE.search(_attr(node, "style")):
            result = True
            break
        node = node.parent
    for visited in chain:
        cache[id(visited)] = result
    return result


def _is_footer_container(tag: Tag) -> bool:
    if tag.name == "footer":
        return True
    return _attr(tag, "role").strip().lower() == "contentinfo"


def _is_tracking(url: str) -> bool:
    lowered = url.lower()
    parts = _split(lowered)
    host = (parts.hostname or "") if parts else ""
    for pattern in TRACKING_PRELOAD_PATTERNS:
        if "/" in pattern or pattern.endswith(".js"):
            if pattern in lowered:
                return True
        elif host == pattern or host.endswith("." + pattern):
            return True
    return False


def _srcset_urls(srcset: str) -> list[str]:
    urls: list[str] = []
    for candidate in srcset.split(","):
        tokens = candidate.split()
        if tokens:
            urls.append(tokens[0])
    return urls


def _base_url(soup: BeautifulSoup, page_url: str) -> str:
    tag = soup.find("base", href=True)
    if tag is None:
        return page_url
    resolved = _resolve(page_url, tag.get("href"))
    parts = _split(resolved) if resolved else None
    return resolved if parts and parts.scheme in _WEB_SCHEMES else page_url


def _resolve(base: str, raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if _scheme_of(value) in _IGNORED_SCHEMES:
        return None
    try:
        joined = urljoin(base, value)
        parts = urlsplit(joined)
        parts.port  # noqa: B018 - raises ValueError for an unparsable port
    except ValueError:
        return None
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def _compare_key(url: str) -> str:
    parts = _split(url)
    if not parts:
        return url
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


def _origin(url: str) -> str | None:
    parts = _split(url)
    if not parts or parts.scheme not in _WEB_SCHEMES or not parts.hostname:
        return None
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    return f"{parts.scheme}://{host}" + (f":{parts.port}" if parts.port else "")


def _split(url: str | None):
    if not url:
        return None
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 - raises ValueError for an unparsable port
    except ValueError:
        return None
    return parts


def _scheme_of(value: str) -> str:
    head, sep, _ = value.partition(":")
    if not sep or not head or not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.\-]*", head):
        return ""
    return _WHITESPACE.sub("", head).lower()


def _site_host(entry: str) -> str | None:
    entry = (entry or "").strip()
    if "//" in entry:
        parts = _split(entry)
        return parts.hostname if parts else None
    return entry.split("/", 1)[0].split(":", 1)[0]


def _host_key(host: str | None) -> str:
    host = (host or "").strip().lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _rel_tokens(tag: Tag) -> set[str]:
    rel = tag.get("rel")
    tokens = rel.split() if isinstance(rel, str) else list(rel or ())
    return {token.lower() for token in tokens}


def _attr(tag: Tag, name: str) -> str:
    value = tag.get(name)
    if isinstance(value, list):
        return " ".join(value)
    return value if isinstance(value, str) else ""


def _css_value(value: str) -> str:
    return re.sub(r"!\s*important", "", value, flags=re.IGNORECASE).strip()


def _dedupe(items):
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
