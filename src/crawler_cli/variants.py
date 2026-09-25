from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


VariantKind = Literal[
    "trailing_slash",
    "suffix_php",
    "suffix_html",
    "suffix_aspx",
    "case",
    "scheme",
    "www_host",
    "query_order",
]


@dataclass(slots=True, frozen=True)
class UrlVariant:
    url: str
    kind: VariantKind


@dataclass(slots=True)
class VariantProbeResult:
    verdict: Literal["ok", "duplicate", "investigate", "absent"]
    status: int
    redirect_location: str | None
    html_canonical: str | None


_DEFAULT_KINDS: set[VariantKind] = {
    "trailing_slash",
    "suffix_php",
    "suffix_html",
    "suffix_aspx",
    "case",
    "scheme",
    "www_host",
    "query_order",
}


_SUFFIX_MAP: dict[VariantKind, str] = {
    "suffix_php": ".php",
    "suffix_html": ".html",
    "suffix_aspx": ".aspx",
}


def generate_variants(url: str, *, kinds: set[VariantKind] | None = None) -> list[UrlVariant]:
    """Generate URL variants for canonicalisation testing."""
    kinds = _DEFAULT_KINDS if kinds is None else kinds
    parsed = urlsplit(url)
    path = parsed.path or "/"
    variants: list[UrlVariant] = []

    for kind in (
        "trailing_slash",
        "suffix_php",
        "suffix_html",
        "suffix_aspx",
        "case",
        "scheme",
        "www_host",
        "query_order",
    ):
        if kind not in kinds:
            continue
        if kind == "trailing_slash":
            if path != "/":
                new_path = path.rstrip("/") if path.endswith("/") else path + "/"
                variant = urlunsplit((parsed.scheme, parsed.netloc, new_path, parsed.query, parsed.fragment))
                variants.append(UrlVariant(variant, kind))
        elif kind in _SUFFIX_MAP:
            suffix = _SUFFIX_MAP[kind]
            if not path.lower().endswith(suffix):
                new_path = path + suffix
                variant = urlunsplit((parsed.scheme, parsed.netloc, new_path, parsed.query, parsed.fragment))
                variants.append(UrlVariant(variant, kind))
        elif kind == "case":
            # Flip case of last path segment
            segments = path.rstrip("/").split("/")
            if segments and segments[-1]:
                last = segments[-1]
                flipped = last.swapcase()
                if flipped != last:
                    segments[-1] = flipped
                    new_path = "/".join(segments)
                    if path.endswith("/"):
                        new_path += "/"
                    variant = urlunsplit((parsed.scheme, parsed.netloc, new_path, parsed.query, parsed.fragment))
                    variants.append(UrlVariant(variant, kind))
        elif kind == "scheme":
            if parsed.scheme.lower() in {"http", "https"}:
                scheme = "http" if parsed.scheme.lower() == "https" else "https"
                variants.append(UrlVariant(urlunsplit((scheme, parsed.netloc, path, parsed.query, parsed.fragment)), kind))
        elif kind == "www_host":
            host = parsed.hostname or ""
            if "." in host and not host.replace(".", "").isdigit() and "@" not in parsed.netloc:
                new_host = host[4:] if host.lower().startswith("www.") else f"www.{host}"
                port = f":{parsed.port}" if parsed.port else ""
                variants.append(
                    UrlVariant(urlunsplit((parsed.scheme, new_host + port, path, parsed.query, parsed.fragment)), kind)
                )
        elif kind == "query_order":
            pairs = parse_qsl(parsed.query, keep_blank_values=True)
            reordered = sorted(pairs, key=lambda pair: (pair[0], pair[1]))
            query = urlencode(reordered, doseq=True)
            if len(pairs) > 1 and query != parsed.query:
                variants.append(UrlVariant(urlunsplit((parsed.scheme, parsed.netloc, path, query, parsed.fragment)), kind))

    return variants


async def probe_variant(engine, canonical_url: str, variant: UrlVariant) -> VariantProbeResult:
    """Probe a variant URL and classify the result."""
    # Request with redirects disabled
    original_follow = engine.config.follow_redirects
    engine.config.follow_redirects = False
    try:
        result = await engine.crawl(variant.url)
    finally:
        engine.config.follow_redirects = original_follow

    status = result.status
    redirect_location = None
    html_canonical = None

    if 300 <= status < 400:
        redirect_location = result.headers.get("Location") or result.headers.get("location")
        # If it redirects to canonical, it's a duplicate
        if redirect_location == canonical_url:
            return VariantProbeResult(
                verdict="duplicate",
                status=status,
                redirect_location=redirect_location,
                html_canonical=None,
            )
        return VariantProbeResult(
            verdict="investigate",
            status=status,
            redirect_location=redirect_location,
            html_canonical=None,
        )

    if status == 200 and result.extracted:
        html_canonical = result.extracted.canonical
        if html_canonical == canonical_url:
            return VariantProbeResult(
                verdict="duplicate",
                status=status,
                redirect_location=None,
                html_canonical=html_canonical,
            )
        return VariantProbeResult(
            verdict="investigate",
            status=status,
            redirect_location=None,
            html_canonical=html_canonical,
        )

    if status == 404:
        return VariantProbeResult(
            verdict="absent",
            status=status,
            redirect_location=None,
            html_canonical=None,
        )

    return VariantProbeResult(
        verdict="investigate",
        status=status,
        redirect_location=redirect_location,
        html_canonical=html_canonical,
    )
