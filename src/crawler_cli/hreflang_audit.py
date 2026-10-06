"""Pure, bounded hreflang facts for technical-audit checks.

The crawler already saves the facts needed to validate a set of alternate
annotations.  This module deliberately does not query a store, load a profile,
or make network requests: callers supply the page records for one crawl run
and receive stable finding rows.  That makes partial-crawl limits explicit and
keeps report collection separate from validation.

The public input accepts either :class:`HreflangPage` values or mappings shaped
like saved ``page_run_snapshots`` records.  In particular, ``hreflang_json``
from the snapshot is accepted directly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from .hreflang_groups import normalise_url


HTML_HREFLANG_SOURCE = "html_head"
SITEMAP_HREFLANG_SOURCE = "sitemap"


@dataclass(frozen=True, slots=True)
class HreflangAnnotation:
    """One saved alternate annotation.

    ``source`` is the crawler source name (normally ``html_head``,
    ``http_header`` or ``sitemap``).  Keeping it on the annotation lets Q83
    distinguish HTML-head annotations from sitemap annotations.
    """

    hreflang: str
    href: str
    source: str = HTML_HREFLANG_SOURCE


@dataclass(frozen=True, slots=True)
class HreflangPage:
    """The bounded saved-page state needed by hreflang checks.

    ``indexable`` is ``False`` only when the saved page is known to be
    noindex/non-indexable.  ``None`` preserves an unknown state, which does
    not create a false finding.  Likewise a missing ``canonical`` is not
    treated as a non-canonical target; that is covered by the canonical
    presence check rather than Q9.
    """

    url: str
    annotations: tuple[HreflangAnnotation, ...] = ()
    status: int | None = None
    indexable: bool | None = None
    canonical: str | None = None
    html_lang: str | None = None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _optional_bool(value: object) -> bool | None:
    """Return only an actual boolean; strings are ambiguous saved evidence."""
    return value if isinstance(value, bool) else None


def _first_text(record: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
    return None


def _annotations_from(value: object) -> tuple[HreflangAnnotation, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    annotations: list[HreflangAnnotation] = []
    for item in value:
        if isinstance(item, HreflangAnnotation):
            if item.href.strip():
                annotations.append(item)
            continue
        if not isinstance(item, Mapping):
            continue
        href = item.get("href")
        if not isinstance(href, str) or not href.strip():
            continue
        hreflang = item.get("hreflang")
        source = item.get("source")
        annotations.append(
            HreflangAnnotation(
                hreflang=hreflang.strip() if isinstance(hreflang, str) else "",
                href=href.strip(),
                source=source.strip() if isinstance(source, str) and source.strip() else HTML_HREFLANG_SOURCE,
            )
        )
    return tuple(annotations)


def coerce_hreflang_page(record: HreflangPage | Mapping[str, object]) -> HreflangPage:
    """Convert one saved record to the small, explicit validation shape.

    Snapshot collectors may use ``hreflang_json`` / ``final_status_code`` /
    ``overall_indexable`` while a report can provide the shorter aliases.  The
    conversion is intentionally narrow and does not guess at truthy strings.
    """
    if isinstance(record, HreflangPage):
        return record
    url = record.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("hreflang page record requires a non-empty url")
    raw_annotations = record.get("annotations", record.get("hreflang_json", record.get("hreflang_links", [])))
    indexable = _optional_bool(record.get("indexable", record.get("overall_indexable")))
    if indexable is None and isinstance(record.get("noindex"), bool):
        indexable = not bool(record["noindex"])
    return HreflangPage(
        url=url.strip(),
        annotations=_annotations_from(raw_annotations),
        status=_optional_int(record.get("status", record.get("final_status_code"))),
        indexable=indexable,
        canonical=_first_text(record, "canonical", "canonical_url", "canonical_urls", "canonical_urls_json"),
        html_lang=_first_text(record, "html_lang"),
    )


def _resolved_target_url(source_url: str, href: str) -> str:
    return normalise_url(urljoin(source_url, href))


def _source_name(annotation: HreflangAnnotation) -> str:
    return annotation.source.strip().casefold()


def _language_primary(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().casefold()
    if not text or text == "x-default":
        return None
    primary = text.split("-", 1)[0]
    return primary if primary.isalpha() and 2 <= len(primary) <= 3 else None


def _locale_folder(url: str) -> str | None:
    """Return a leading locale-looking segment, never infer one at root.

    Q41 cannot know that a non-locale path (``/products/``) should have been
    ``/en/products/`` without a site's locale profile.  It can deterministically
    flag a declared ``fr`` page under ``/en/`` (and vice versa).
    """
    first = next((segment for segment in urlparse(normalise_url(url)).path.split("/") if segment), "")
    return _language_primary(first)


def _fact_key(fact: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    """Stable, content-based ordering and de-duplication for report rows."""
    return tuple((key, str(fact.get(key, ""))) for key in sorted(fact))


def iter_hreflang_facts(
    records: Iterable[HreflangPage | Mapping[str, object]],
    *,
    sitemap_hreflang_present: bool | None = None,
    max_html_hreflangs: int = 20,
) -> Iterable[dict[str, object]]:
    """Yield deterministic Q9/Q41/Q83 fact rows from saved page records.

    Facts emitted:

    * ``hreflang-non-reciprocal`` — both ends were crawled and the target has
      no annotation back to the source;
    * ``hreflang-target-non-200``, ``hreflang-target-noindex`` and
      ``hreflang-target-noncanonical`` — saved target state invalidates an
      alternate;
    * ``locale-path-language-mismatch`` — an existing locale folder conflicts
      with ``html_lang`` or a self-hreflang;
    * ``hreflang-html-bloat-without-sitemap`` — more than the supplied limit
      of HTML-head alternates and no sitemap hreflang evidence.

    Missing target pages create no reciprocity/state finding: a saved crawl
    cannot distinguish a genuinely absent return link from an uncrawled target.
    Callers should expose that coverage limit separately.  Set
    ``sitemap_hreflang_present`` when the sitemap collector has a definitive
    answer; when omitted it is derived from saved annotations.
    """
    if max_html_hreflangs < 0:
        raise ValueError("max_html_hreflangs must be non-negative")

    pages = [coerce_hreflang_page(record) for record in records]
    pages_by_url = {normalise_url(page.url): page for page in pages if normalise_url(page.url)}
    if sitemap_hreflang_present is None:
        sitemap_hreflang_present = any(
            _source_name(annotation) == SITEMAP_HREFLANG_SOURCE
            for page in pages
            for annotation in page.annotations
        )

    edge_pairs = {
        (normalise_url(page.url), _resolved_target_url(page.url, annotation.href))
        for page in pages
        for annotation in page.annotations
        if normalise_url(page.url) and _resolved_target_url(page.url, annotation.href)
    }
    facts: list[dict[str, object]] = []

    for page in pages:
        source_url = normalise_url(page.url)
        if not source_url:
            continue
        for annotation in page.annotations:
            target_url = _resolved_target_url(page.url, annotation.href)
            target = pages_by_url.get(target_url)
            common = {
                "url": page.url,
                "target_url": target.url if target is not None else target_url,
                "hreflang": annotation.hreflang,
                "annotation_source": _source_name(annotation),
            }
            if target is None:
                continue
            if target_url != source_url and (target_url, source_url) not in edge_pairs:
                facts.append({"kind": "hreflang-non-reciprocal", **common})
            if target.status is not None and target.status != 200:
                facts.append({"kind": "hreflang-target-non-200", "target_status": target.status, **common})
            if target.indexable is False:
                facts.append({"kind": "hreflang-target-noindex", **common})
            target_canonical = normalise_url(urljoin(target.url, target.canonical or ""))
            if target_canonical and target_canonical != target_url:
                facts.append(
                    {
                        "kind": "hreflang-target-noncanonical",
                        "target_canonical": target.canonical or "",
                        **common,
                    }
                )

        locale = _locale_folder(page.url)
        if locale is not None:
            declarations: list[tuple[str, str]] = []
            if page.html_lang:
                declarations.append(("html_lang", page.html_lang))
            declarations.extend(
                ("self_hreflang", annotation.hreflang)
                for annotation in page.annotations
                if _resolved_target_url(page.url, annotation.href) == source_url
            )
            seen_declarations: set[tuple[str, str]] = set()
            for declared_from, declared in declarations:
                declared_primary = _language_primary(declared)
                key = (declared_from, declared_primary or "")
                if declared_primary is None or key in seen_declarations:
                    continue
                seen_declarations.add(key)
                if declared_primary != locale:
                    facts.append(
                        {
                            "kind": "locale-path-language-mismatch",
                            "url": page.url,
                            "locale_folder": locale,
                            "declared_language": declared,
                            "declared_from": declared_from,
                        }
                    )

        html_count = sum(1 for annotation in page.annotations if _source_name(annotation) == HTML_HREFLANG_SOURCE)
        if not sitemap_hreflang_present and html_count > max_html_hreflangs:
            facts.append(
                {
                    "kind": "hreflang-html-bloat-without-sitemap",
                    "url": page.url,
                    "html_hreflang_count": html_count,
                    "max_html_hreflangs": max_html_hreflangs,
                }
            )

    unique = {_fact_key(fact): fact for fact in facts}
    yield from (unique[key] for key in sorted(unique))


def hreflang_facts(
    records: Iterable[HreflangPage | Mapping[str, object]],
    *,
    sitemap_hreflang_present: bool | None = None,
    max_html_hreflangs: int = 20,
) -> list[dict[str, object]]:
    """Materialise :func:`iter_hreflang_facts` for simple report callers."""
    return list(
        iter_hreflang_facts(
            records,
            sitemap_hreflang_present=sitemap_hreflang_present,
            max_html_hreflangs=max_html_hreflangs,
        )
    )
