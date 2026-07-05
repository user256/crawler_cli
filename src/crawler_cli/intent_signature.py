"""Per-page intent signatures ported from Intent_Overlap (ticket 076).

An *intent signature* is the boilerplate-stripped composition of a page's
title, H1, meta description and the lead of its main body text.  It is the
input that the embedding step (ticket 077) encodes and the analyse step
(ticket 079) compares, and it is hashed once (``signature_hash``) so unchanged
pages can be skipped on re-embed.

Every public function here is a verbatim port of the *fixed* Intent_Overlap
reference (``intent_overlap.py`` @ upstream HEAD 96fce80, v2.1.0): the unified
``signature_text``/``signature_hash`` contract landed in IO tickets 109/114 —
the single hash definition shared by crawl and embed so boilerplate pages never
re-embed every run.  Do not add a second hash definition.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .persistence import AsyncpgStore, IntentSignatureRow

# Title separator characters, in priority order, used to split site-level
# boilerplate prefixes/suffixes off a title (intent_overlap.py:886).
_TITLE_SPLITS = (" | ", " – ", " — ", " - ", "|", "–", "—")

# The signature caps body text at this many characters so embeddings stay
# comparable with Intent_Overlap goldens (intent_overlap.py:989).
_TEXT_CAP = 1500

# Confidence/boilerplate defaults mirror the upstream CLI defaults.
DEFAULT_BOILERPLATE_SHARE = 0.30
DEFAULT_MIN_WORDS = 50


def _split_title_part(title: str, which: str) -> str:
    """Return the prefix or suffix segment of *title* around the first
    separator found (intent_overlap.py:889)."""
    for sep in _TITLE_SPLITS:
        if sep in title:
            parts = title.split(sep)
            return (parts[0] if which == "prefix" else parts[-1]).strip()
    return ""


def detect_boilerplate(
    titles_by_site: Mapping[str, list[str]],
    min_share: float = DEFAULT_BOILERPLATE_SHARE,
) -> dict[str, tuple[str | None, str | None]]:
    """Per-site ``(prefix, suffix)`` boilerplate appearing on > *min_share* of
    a site's titles (intent_overlap.py:897).

    Upstream reads titles from its SQLite ``pages`` table; this port takes
    titles already grouped by site (``netloc.lower()``) so it stays pure and
    unit-testable.  A pattern must appear on *strictly more* than *min_share*
    of a site's titles to count as boilerplate; sites with fewer than two
    titles are skipped.
    """
    patterns: dict[str, tuple[str | None, str | None]] = {}
    for site, titles in titles_by_site.items():
        n = len(titles)
        if n < 2:
            continue
        prefixes: Counter[str] = Counter()
        suffixes: Counter[str] = Counter()
        for t in titles:
            p, s = _split_title_part(t, "prefix"), _split_title_part(t, "suffix")
            if p:
                prefixes[p] += 1
            if s:
                suffixes[s] += 1
        prefix = suffix = None
        if prefixes:
            p, c = prefixes.most_common(1)[0]
            if c / n > min_share and p:
                prefix = p
        if suffixes:
            s, c = suffixes.most_common(1)[0]
            if c / n > min_share and s:
                suffix = s
        if prefix or suffix:
            patterns[site] = (prefix, suffix)
    return patterns


def strip_boilerplate_field(text: str, prefix: str | None, suffix: str | None) -> str:
    """Strip a detected boilerplate *prefix*/*suffix* off *text*
    (intent_overlap.py:940)."""
    if not text:
        return text
    t = text.strip()
    for sep in _TITLE_SPLITS:
        if prefix and t.startswith(prefix + sep):
            t = t.split(sep, 1)[-1].strip()
            break
        if prefix and t == prefix:
            t = ""
            break
    for sep in _TITLE_SPLITS:
        if suffix and t.endswith(sep + suffix):
            t = t.rsplit(sep, 1)[0].strip()
            break
        if suffix and t == suffix:
            t = ""
            break
    return t


def _s(v: Any) -> str:
    """Coerce a possibly-None / NaN field to a stripped string
    (intent_overlap.py:975)."""
    if v is None or (isinstance(v, float) and v != v):
        return ""
    return str(v).strip()


def intent_text(
    row: Mapping[str, Any],
    boilerplate: Mapping[str, tuple[str | None, str | None]] | None = None,
) -> str:
    """The intent signature: ``title + h1 + meta_description + text[:1500]``
    (intent_overlap.py:971), weighted toward title/h1/meta so pages targeting
    the same query cluster together even when body copy differs.

    *row* is a mapping with ``site``/``title``/``h1``/``meta_description``/``text``.
    """
    site = row.get("site")
    prefix = suffix = None
    if boilerplate:
        prefix, suffix = boilerplate.get(site or "", boilerplate.get("", (None, None)))
    title = strip_boilerplate_field(_s(row.get("title")), prefix, suffix)
    h1 = strip_boilerplate_field(_s(row.get("h1")), prefix, suffix)
    parts = [
        title,
        h1,
        _s(row.get("meta_description")),
        _s(row.get("text"))[:_TEXT_CAP],
    ]
    return "\n".join(p for p in parts if p)


def signature_text(
    row: Mapping[str, Any],
    boilerplate: Mapping[str, tuple[str | None, str | None]] | None = None,
) -> str:
    """The signature used for BOTH embedding input and ``signature_hash``.

    The site key is derived from ``netloc.lower()`` of the row's URL so crawl
    and embed compute the identical signature and never diverge
    (intent_overlap.py:993, IO ticket 114).
    """
    url = row.get("url")
    site = urlparse(url).netloc.lower() if url else (row.get("site") or "")
    return intent_text(
        {
            "site": site,
            "title": row.get("title"),
            "h1": row.get("h1"),
            "meta_description": row.get("meta_description"),
            "text": row.get("text"),
        },
        boilerplate,
    )


def signature_hash(
    row: Mapping[str, Any],
    boilerplate: Mapping[str, tuple[str | None, str | None]] | None = None,
) -> str:
    """SHA-256 of ``signature_text`` — the single unified hash definition
    (intent_overlap.py:1005)."""
    return hashlib.sha256(signature_text(row, boilerplate).encode("utf-8")).hexdigest()


def extract_main_text(html: str) -> tuple[str | None, str]:
    """Extract main body text from raw *html*.

    Returns ``(text, extraction_method)`` where method is one of
    ``"trafilatura"`` / ``"fallback"`` / ``"none"``, matching Intent_Overlap's
    ``extract_page`` chain (intent_overlap.py:592): trafilatura first, an
    lxml tag-strip fallback second.
    """
    try:
        import trafilatura

        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if text:
            return text, "trafilatura"
    except Exception:
        pass
    try:
        from lxml import html as lhtml

        tree = lhtml.fromstring(html)
        for bad in tree.xpath("//script|//style|//nav|//header|//footer"):
            bad.drop_tree()
        text = re.sub(r"\s+", " ", tree.text_content()).strip()
        if text:
            return text, "fallback"
    except Exception:
        pass
    return None, "none"


def resolve_signal_confidence(
    word_count: int | None,
    extraction_method: str | None,
    min_words: int = DEFAULT_MIN_WORDS,
) -> str:
    """``"low"`` when the page is thin (< *min_words*) or only had a fallback
    extraction, else ``"high"`` (intent_overlap.py:961)."""
    if (word_count or 0) < min_words or extraction_method == "fallback":
        return "low"
    return "high"


@dataclass(slots=True)
class SignatureBackfillResult:
    processed: int = 0
    updated: int = 0
    unchanged: int = 0
    low_confidence: int = 0
    no_text: int = 0
    by_method: dict[str, int] = field(default_factory=dict)


async def backfill_intent_signatures(
    store: AsyncpgStore,
    *,
    urls: list[str] | None = None,
    boilerplate_share: float = DEFAULT_BOILERPLATE_SHARE,
    min_words: int = DEFAULT_MIN_WORDS,
    dry_run: bool = False,
) -> SignatureBackfillResult:
    """Compute and persist intent signatures over stored HTML.

    Boilerplate detection is per-site and needs the full title set, so this
    runs as a post-pass: extract every page's main text, learn the site-level
    boilerplate, then strip + hash once titles are known.  Only rows whose
    ``signature_hash`` actually changed are written, so re-running on an
    unchanged crawl rewrites zero hashes (the IO ticket-114 zero-re-embed
    proof).
    """
    pages = await store.fetch_pages_for_signatures(urls=urls)

    # Pass 1: extract main text and gather titles per site.
    extracted: list[dict[str, Any]] = []
    titles_by_site: dict[str, list[str]] = {}
    for page in pages:
        html = page.get("html") or ""
        text, method = extract_main_text(html)
        word_count = len(text.split()) if text else 0
        url = str(page.get("url") or "")
        site = urlparse(url).netloc.lower()
        title = page.get("title")
        if title:
            titles_by_site.setdefault(site, []).append(str(title))
        extracted.append(
            {
                "url_id": int(page["url_id"]),
                "url": url,
                "title": title,
                "h1": page.get("h1"),
                "meta_description": page.get("meta_description"),
                "text": text,
                "extraction_method": method,
                "word_count": word_count,
            }
        )

    boilerplate = detect_boilerplate(titles_by_site, boilerplate_share)
    existing = await store.existing_signature_hashes()

    result = SignatureBackfillResult()
    to_write: list[IntentSignatureRow] = []
    for row in extracted:
        result.processed += 1
        result.by_method[row["extraction_method"]] = result.by_method.get(row["extraction_method"], 0) + 1
        if row["text"] is None:
            result.no_text += 1
        sig_text = signature_text(row, boilerplate)
        sig_hash = hashlib.sha256(sig_text.encode("utf-8")).hexdigest()
        confidence = resolve_signal_confidence(row["word_count"], row["extraction_method"], min_words)
        if confidence == "low":
            result.low_confidence += 1
        if existing.get(row["url_id"]) == sig_hash:
            result.unchanged += 1
            continue
        result.updated += 1
        to_write.append(
            {
                "url_id": row["url_id"],
                "main_text": row["text"],
                "extraction_method": row["extraction_method"],
                "signal_confidence": confidence,
                "signature_hash": sig_hash,
                "signature_model_input": sig_text,
            }
        )

    if to_write and not dry_run:
        await store.store_intent_signatures_bulk(to_write)
    elif dry_run:
        # Nothing written; report what would have changed but leave counts.
        pass
    return result
