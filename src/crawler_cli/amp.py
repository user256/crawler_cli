"""AMP / page-variant classification (ticket 103).

The crawler discovers and fetches AMP variants but historically nothing in the
pipeline *knew* they were AMP: keeping them out of intent-overlap pairing
depended entirely on each AMP page happening to declare a canonical.  This
module gives AMP variants a first-class, structural identity derived purely
from crawler-captured evidence:

* the ``rel="amphtml"`` link edge extracted in :mod:`crawler_cli.extract`
  (the authoritative page->AMP pairing signal), and
* AMP URL shape (a trailing ``/amp`` path segment as produced by Joomla's
  wbAMP, or an ``amp=1`` query parameter) confirmed by content — a matching
  content hash, a canonical pointing to the base page, or simply the base page
  existing in the crawl.

Everything here is a pure function so it can be unit-tested without a database
and reused by the engine (crawl-budget skipping), persistence (classification
UPDATE) and intent-overlap analysis (exclusion + hygiene report).

The mechanism is intentionally variant-agnostic: ``variant_kind`` is an
extensible enum (``'amp'`` today; print/feed variants could follow) so the
classification surface generalises without another migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

#: The only variant kind classified today.  Kept as a named constant so callers
#: (persistence, analysis) never hard-code the literal and future kinds slot in
#: alongside it.
VARIANT_KIND_AMP = "amp"


def _normalise_for_match(url: str) -> str:
    """A lenient key for base<->page identity matching.

    Ignores a trailing slash and a leading ``www.`` so that ``/amp`` mapping to
    ``https://host`` still matches a crawled ``https://host/`` homepage, and so
    canonical-vs-base comparison is not defeated by cosmetic differences.
    """
    parsed = urlparse(url.strip())
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    return urlunparse(parsed._replace(netloc=netloc, path=path, fragment="")).rstrip("/")


def urls_match(a: str, b: str) -> bool:
    """True if *a* and *b* denote the same page ignoring cosmetic differences
    (trailing slash, leading ``www.``).  Used to test whether an AMP page's
    canonical points at its detected base."""
    return _normalise_for_match(a) == _normalise_for_match(b)


def amp_base_url(url: str) -> str | None:
    """Return the base (non-AMP) URL *url* maps to, or ``None`` if *url* is not
    AMP-shaped.

    Two shapes are recognised, both narrowly scoped to AMP so as not to overlap
    the general parameterised-URL classification (ticket 102):

    * a trailing ``/amp`` **path segment** (Joomla wbAMP): ``/foo/amp`` ->
      ``/foo``, ``/amp`` -> ``/``.  A slug that merely ends in ``amp`` such as
      ``/revamp`` is *not* matched (the segment must equal ``amp`` exactly).
    * an ``amp=1`` **query parameter**: ``/foo?amp=1`` -> ``/foo``,
      ``/foo?x=1&amp=1`` -> ``/foo?x=1``.  Only the ``amp`` key with value
      ``1`` is matched.
    """
    parsed = urlparse(url)
    is_amp = False

    new_path = parsed.path
    core = [seg for seg in parsed.path.strip("/").split("/") if seg != ""]
    if core and core[-1].lower() == "amp":
        is_amp = True
        base_core = core[:-1]
        if not base_core:
            new_path = "/"
        else:
            trailing = "/" if parsed.path.endswith("/") else ""
            new_path = "/" + "/".join(base_core) + trailing

    new_query = parsed.query
    if parsed.query:
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        if any(key == "amp" and value == "1" for key, value in pairs):
            is_amp = True
            kept = [(k, v) for k, v in pairs if not (k == "amp" and v == "1")]
            new_query = urlencode(kept)

    if not is_amp:
        return None
    return urlunparse(parsed._replace(path=new_path, query=new_query))


def is_amp_url_shape(url: str) -> bool:
    """True if *url* has an AMP variant URL shape (see :func:`amp_base_url`)."""
    return amp_base_url(url) is not None


@dataclass(slots=True)
class AmpClassification:
    """One page classified as an AMP variant.

    ``base_url`` is the paired non-AMP page when known (from a ``rel="amphtml"``
    source or the URL shape); ``confirmed_by`` records which crawler-captured
    signal justified the classification.
    """

    url_id: int
    url: str
    base_url: str | None
    confirmed_by: str  # amphtml-target | canonical-to-base | content-hash | base-exists


def classify_amp_variants(
    pages: Iterable[Mapping[str, object]],
    amphtml_base_by_target: Mapping[int, str],
) -> list[AmpClassification]:
    """Classify AMP variants from crawler-captured evidence.

    *pages* is an iterable of mappings with keys ``url_id``, ``url``,
    ``canonical_url`` (``str | None``) and ``content_hash`` (``str | None``).
    *amphtml_base_by_target* maps a page's ``url_id`` to the base URL of a page
    that declared ``<link rel="amphtml">`` pointing at it (the authoritative
    signal).

    A page is classified AMP when:

    a. it is the target of another page's ``rel="amphtml"`` edge
       (unconditional — the authoritative pairing signal), **or**
    b. it has an AMP URL shape *and* that shape is confirmed by content — its
       canonical points to the derived base, its content hash matches the base
       page's, or the base page exists in the crawl.

    The content confirmation in (b) is what keeps a page whose slug merely
    contains ``amp`` (already excluded by the URL-shape parser) or a stray
    literal ``/amp`` path from being misclassified.
    """
    page_list = list(pages)

    fetched_keys: set[str] = set()
    hash_by_key: dict[str, str] = {}
    for page in page_list:
        url = str(page["url"])
        key = _normalise_for_match(url)
        fetched_keys.add(key)
        content_hash = page.get("content_hash")
        if content_hash:
            hash_by_key[key] = str(content_hash)

    results: list[AmpClassification] = []
    for page in page_list:
        url_id = int(str(page["url_id"]))
        url = str(page["url"])

        amphtml_base = amphtml_base_by_target.get(url_id)
        if amphtml_base is not None:
            results.append(AmpClassification(url_id, url, amphtml_base, "amphtml-target"))
            continue

        base = amp_base_url(url)
        if base is None:
            continue

        base_key = _normalise_for_match(base)
        canonical = page.get("canonical_url")
        content_hash = page.get("content_hash")

        confirmed_by: str | None = None
        if canonical and _normalise_for_match(str(canonical)) == base_key:
            confirmed_by = "canonical-to-base"
        elif content_hash and hash_by_key.get(base_key) == str(content_hash):
            confirmed_by = "content-hash"
        elif base_key in fetched_keys:
            confirmed_by = "base-exists"

        if confirmed_by is not None:
            results.append(AmpClassification(url_id, url, base, confirmed_by))

    return results
