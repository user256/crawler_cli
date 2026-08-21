from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import parse_qsl, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from .models import (
    JavaScriptLiteralKind,
    JavaScriptSourceKind,
    JavaScriptUrlCandidate,
    JavaScriptUrlClassification,
)

_JAVASCRIPT_TYPES = {
    "application/ecmascript",
    "application/javascript",
    "application/x-javascript",
    "module",
    "text/ecmascript",
    "text/javascript",
}
_NON_EXECUTABLE_SCRIPT_TYPES = {
    "application/json",
    "application/ld+json",
    "importmap",
    "speculationrules",
}
_ASSET_EXTENSIONS = {
    ".avif",
    ".css",
    ".eot",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".map",
    ".mjs",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".svg",
    ".ttf",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".xml",
    ".zip",
}
_ACTION_SEGMENTS = {
    "add-to-cart",
    "checkout",
    "delete",
    "destroy",
    "logout",
    "remove",
    "signout",
    "unsubscribe",
}
_API_SEGMENTS = {"ajax", "api", "graphql", "rest", "rpc"}
_ASSET_SEGMENTS = {"assets", "fonts", "images", "scripts", "static", "styles"}
_SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "client_secret",
    "password",
    "passwd",
    "secret",
    "session",
    "sessionid",
    "signature",
    "token",
}
_HEX = frozenset("0123456789abcdefABCDEF")
_BARE_RELATIVE_RE = re.compile(r"^[A-Za-z0-9._~-]+/(?:[^\s<>\"']+)$")
_ABSOLUTE_URL_RE = re.compile(
    r"(?:(?:https?):)?//[A-Za-z0-9._~%-]+(?::[0-9]{2,5})?"
    r"(?:/[A-Za-z0-9._~%!$&'()*+,;=:@/-]*)?"
    r"(?:\?[A-Za-z0-9._~%!$&'()*+,;=:@/?-]*)?",
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(r"\$\{|\{\{|%[sd]|<%|(?:^|/):[A-Za-z_]|\{[A-Za-z_][A-Za-z0-9_]*\}|__[^/]*__")
_MIME_LIKE_RE = re.compile(
    r"^(?:text|application|image|audio|video|font|multipart|message)/[a-z0-9.+-]+$",
    re.IGNORECASE,
)
_DATE_LIKE_RE = re.compile(r"^/?\d{1,4}/\d{1,2}(?:/\d{1,4})?/?$")
_VERSION_LIKE_RE = re.compile(r"^v?\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9.-]+)?$", re.IGNORECASE)
_REGEX_LIKE_RE = re.compile(r"(?:^\^|\$$|\\[dDsSwWbB]|\(\?:|\[\^)")
_BAD_SCHEMES = (
    "about:",
    "blob:",
    "chrome:",
    "data:",
    "javascript:",
    "mailto:",
    "tel:",
    "ws:",
    "wss:",
)


@dataclass(frozen=True, slots=True)
class InlineJavaScript:
    index: int
    source: str


@dataclass(frozen=True, slots=True)
class JavaScriptLiteral:
    value: str
    literal_kind: JavaScriptLiteralKind
    occurrence_count: int = 1


def _script_is_javascript(tag: Tag) -> bool:
    raw_type = str(tag.get("type", "")).strip().lower().split(";", 1)[0]
    if raw_type in _NON_EXECUTABLE_SCRIPT_TYPES:
        return False
    return not raw_type or raw_type in _JAVASCRIPT_TYPES


def extract_javascript_sources(
    soup: BeautifulSoup,
    base_url: str,
    *,
    max_external_scripts: int,
) -> tuple[list[InlineJavaScript], list[str]]:
    """Return executable inline bodies and bounded HTTP(S) ``script[src]`` URLs."""
    inline: list[InlineJavaScript] = []
    external: list[str] = []
    seen_external: set[str] = set()
    for index, node in enumerate(soup.find_all("script")):
        if not isinstance(node, Tag) or not _script_is_javascript(node):
            continue
        src = str(node.get("src", "")).strip()
        if src:
            if len(external) >= max_external_scripts:
                continue
            resolved = _normalise_http_url(urljoin(base_url, src))
            if resolved and resolved not in seen_external:
                seen_external.add(resolved)
                external.append(resolved)
            continue
        body = node.string if node.string is not None else node.get_text()
        if body and body.strip():
            inline.append(InlineJavaScript(index=index, source=str(body)))
    return inline, external


def _decode_escape(source: str, index: int) -> tuple[str, int]:
    if index >= len(source):
        return "", index
    char = source[index]
    simple = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}
    if char in simple:
        return simple[char], index + 1
    if char in "\r\n":
        if char == "\r" and index + 1 < len(source) and source[index + 1] == "\n":
            return "", index + 2
        return "", index + 1
    if char == "x" and index + 2 < len(source) and all(c in _HEX for c in source[index + 1 : index + 3]):
        return chr(int(source[index + 1 : index + 3], 16)), index + 3
    if char == "u" and index + 4 < len(source) and all(c in _HEX for c in source[index + 1 : index + 5]):
        return chr(int(source[index + 1 : index + 5], 16)), index + 5
    return char, index + 1


def _javascript_strings(source: str) -> Iterator[tuple[str, bool]]:
    """Lex static JS string/template tokens while skipping comments.

    This is deliberately a small lexer, not a JavaScript parser. It handles
    quotes, escapes and comments without executing source or interpreting
    regex literals. Dynamic template literals are returned as non-static.
    """
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char == "/" and index + 1 < length and source[index + 1] == "/":
            newline = source.find("\n", index + 2)
            index = length if newline < 0 else newline + 1
            continue
        if char == "/" and index + 1 < length and source[index + 1] == "*":
            end = source.find("*/", index + 2)
            index = length if end < 0 else end + 2
            continue
        if char not in {"'", '"', "`"}:
            index += 1
            continue
        quote = char
        index += 1
        value: list[str] = []
        dynamic = False
        while index < length:
            char = source[index]
            if char == quote:
                index += 1
                yield "".join(value), dynamic
                break
            if quote == "`" and char == "$" and index + 1 < length and source[index + 1] == "{":
                dynamic = True
            if char == "\\":
                decoded, index = _decode_escape(source, index + 1)
                value.append(decoded)
                continue
            value.append(char)
            index += 1
        else:
            break


def _literal_kind(value: str) -> JavaScriptLiteralKind | None:
    lowered = value.lower()
    if lowered.startswith(("https://", "http://")):
        return "absolute"
    if value.startswith("//"):
        return "protocol_relative"
    if value.startswith("/"):
        return "root_relative"
    if value.startswith(("./", "../")) or _BARE_RELATIVE_RE.fullmatch(value):
        return "path_relative"
    if value.startswith("?"):
        return "query_relative"
    return None


def url_like_junk_reason(value: str) -> str | None:
    """Return a stable rejection reason for common speculative false positives."""
    lowered = value.lower()
    if lowered.startswith(_BAD_SCHEMES):
        return "bad_scheme"
    if _PLACEHOLDER_RE.search(value):
        return "unresolved_placeholder"
    if _MIME_LIKE_RE.fullmatch(value):
        return "mime_type"
    if _DATE_LIKE_RE.fullmatch(value):
        return "date_like"
    if _VERSION_LIKE_RE.fullmatch(value):
        return "version_like"
    if _REGEX_LIKE_RE.search(value):
        return "regex_source"
    if lowered.startswith(("errors/", "i18n/", "labels/", "messages/", "translations/")):
        return "i18n_key"
    if value.startswith("@") or lowered.startswith(("node_modules/", "webpack/")):
        return "module_identifier"
    if len(value) > 2048:
        return "overlong"
    if any(ord(char) < 32 or char.isspace() for char in value):
        return "whitespace_or_control"
    return None


def _record_rejection(counts: dict[str, int] | None, reason: str) -> None:
    if counts is not None:
        counts[reason] = counts.get(reason, 0) + 1


def _confidence_for_kind(kind: JavaScriptLiteralKind) -> tuple[str, float]:
    if kind in {"absolute", "protocol_relative"}:
        return "high", 0.55
    if kind == "root_relative":
        return "medium", 0.4
    return "low", 0.15


def _normalise_http_url(url: str) -> str | None:
    if len(url) > 4096:
        return None
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if any(key.lower() in _SENSITIVE_QUERY_KEYS for key, _value in parse_qsl(parsed.query, keep_blank_values=True)):
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if port is not None and not (
        (parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"
    return urlunparse((parsed.scheme.lower(), netloc, parsed.path or "/", "", parsed.query, ""))


def _classify(url: str) -> JavaScriptUrlClassification:
    parsed = urlparse(url)
    path = parsed.path.lower()
    suffix = "." + path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    if suffix in _ASSET_EXTENSIONS:
        return "asset"
    segments = {segment for segment in path.split("/") if segment}
    if segments & _ASSET_SEGMENTS:
        return "asset"
    if any(
        segment == action or segment.startswith((f"{action}-", f"{action}_"))
        for segment in segments
        for action in _ACTION_SEGMENTS
    ):
        return "action"
    hostname = parsed.hostname or ""
    if segments & _API_SEGMENTS or hostname.startswith(("api.", "graphql.")):
        return "api"
    return "page"


def scan_javascript_literals(
    source: str,
    *,
    max_literals: int | None = None,
    rejection_counts: dict[str, int] | None = None,
) -> list[JavaScriptLiteral]:
    """Extract and deduplicate static URL-shaped string literals from JS."""
    aggregated: dict[tuple[str, JavaScriptLiteralKind], int] = {}
    for raw_value, dynamic in _javascript_strings(source):
        value = raw_value.strip()
        if not value:
            continue
        kind = _literal_kind(value)
        if dynamic:
            if kind is not None or _PLACEHOLDER_RE.search(value):
                _record_rejection(rejection_counts, "unresolved_placeholder")
            continue
        if kind is None:
            if value.lower().startswith(_BAD_SCHEMES):
                _record_rejection(rejection_counts, "bad_scheme")
            continue
        reason = url_like_junk_reason(value)
        if reason is not None:
            _record_rejection(rejection_counts, reason)
            continue
        # Classification is finalized after resolution. Keep this raw-stage
        # value so one cached external bundle can resolve relative literals
        # against each document that references it.
        key = (value, kind)
        aggregated[key] = aggregated.get(key, 0) + 1
        if max_literals is not None and len(aggregated) >= max_literals:
            break
    # Heritrix-style raw absolute scan. Quoted occurrences intentionally merge
    # with lexer output; this also finds URL-shaped text in syntactically odd
    # bundles without evaluating it.
    if max_literals is None or len(aggregated) < max_literals:
        for match in _ABSOLUTE_URL_RE.finditer(source):
            value = match.group(0).rstrip('.,;:!?)]}"')
            kind = _literal_kind(value)
            if kind is None:
                continue
            reason = url_like_junk_reason(value)
            if reason is not None:
                _record_rejection(rejection_counts, reason)
                continue
            key = (value, kind)
            aggregated[key] = aggregated.get(key, 0) + 1
            if max_literals is not None and len(aggregated) >= max_literals:
                break
    return [
        JavaScriptLiteral(
            value=value,
            literal_kind=kind,
            occurrence_count=count,
        )
        for (value, kind), count in aggregated.items()
    ]


def resolve_javascript_literals(
    literals: list[JavaScriptLiteral],
    document_url: str,
    *,
    source_kind: JavaScriptSourceKind,
    script_source: str,
    script_index: int | None,
    asset_url: str | None = None,
    relative_base_mode: str = "document",
) -> list[JavaScriptUrlCandidate]:
    """Resolve raw literals against the owning document and classify them."""
    candidates: list[JavaScriptUrlCandidate] = []
    for literal in literals:
        value = literal.value
        bases: list[tuple[str, str]] = [(document_url, "document")]
        if (
            relative_base_mode == "document-and-asset"
            and asset_url
            and literal.literal_kind not in {"absolute", "protocol_relative", "root_relative"}
            and asset_url != document_url
        ):
            bases.append((asset_url, "asset"))
        confidence, confidence_weight = _confidence_for_kind(literal.literal_kind)
        seen: set[str] = set()
        for base, resolution_base in bases:
            if literal.literal_kind == "protocol_relative":
                resolved_value = f"{urlparse(document_url).scheme}:{value}"
            else:
                resolved_value = urljoin(base, value)
            resolved = _normalise_http_url(resolved_value)
            if resolved is None or resolved in seen:
                continue
            seen.add(resolved)
            classification = _classify(resolved)
            candidates.append(
                JavaScriptUrlCandidate(
                    url=resolved,
                    source_kind=source_kind,
                    script_source=script_source,
                    script_index=script_index,
                    literal_kind=literal.literal_kind,
                    classification=classification,
                    follow_eligible=classification == "page",
                    occurrence_count=literal.occurrence_count,
                    confidence=confidence,  # type: ignore[arg-type]
                    confidence_weight=confidence_weight,
                    resolution_base=resolution_base,  # type: ignore[arg-type]
                )
            )
    return candidates


def javascript_content_type_supported(content_type: str | None, url: str) -> bool:
    """Return whether a fetched linked resource is plausibly JavaScript."""
    if content_type:
        media_type = content_type.lower().split(";", 1)[0].strip()
        if media_type in _JAVASCRIPT_TYPES or media_type.endswith("+javascript"):
            return True
        return False
    return urlparse(url).path.lower().endswith((".js", ".mjs"))
