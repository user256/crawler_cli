"""Hreflang alternate groups + URL identity resolution (ticket 078).

Turns the crawler's already-captured hreflang edges (the three tables
``hreflang_http_header`` / ``hreflang_html_head`` / ``hreflang_sitemap``) into
union-find alternate groups, resolves per-page language buckets, and folds URL
variants to one representative per normalized URL — the two identity layers the
intent-overlap analysis (ticket 079) needs to suppress false-positive
duplicates.

**100% crawler-powered.** Everything here runs on data the crawler captured
itself; there is no external CSV/import path. A fresh crawl alone yields groups.

Ported from the *fixed* Intent_Overlap reference (``intent_overlap.py`` @
upstream HEAD 96fce80, v2.1.0): ``normalise_url`` incl. the tracking-param
denylist (:222, IO ticket 108), ``UnionFind`` (:800),
``rebuild_hreflang_groups`` (:816), ``hreflang_reciprocity_issues`` (:867),
``lang_bucket`` (:1108), and the variant ``rep_rank`` (:455).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlparse

from .persistence import AsyncpgStore, HreflangIdentityRow

# Tracking query keys stripped during normalisation so ?gclid=… variants fold
# to one representative (intent_overlap.py:209, IO ticket 108).
TRACKING_QUERY_KEYS = frozenset({"gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "dclid", "gbraid", "wbraid"})

# Default-document filenames folded onto their directory URL so ``/index.php``
# and ``/`` are one identity (ticket 102).  Longest suffix first so ``.html``
# never loses to a ``.htm`` prefix match.
INDEX_DOCUMENT_TAILS = ("/index.php", "/index.html", "/index.htm")


def _fold_index_document(path: str) -> str:
    """Fold a default-document tail (``/index.php`` / ``.html`` / ``.htm``) onto
    its directory, mirroring the trailing-slash rule (ticket 102).  Expects an
    already-lowercased path and returns the directory with a trailing slash so
    the caller's ``rstrip('/')`` collapses it exactly like a directory URL."""
    for tail in INDEX_DOCUMENT_TAILS:
        if path.endswith(tail):
            return path[: -len(tail)] + "/"
    return path


def _strip_tracking_query(query: str) -> str:
    if not query:
        return ""
    kept = [
        (k, v)
        for k, v in parse_qsl(query, keep_blank_values=True)
        if not (k.lower().startswith("utm_") or k.lower() in TRACKING_QUERY_KEYS)
    ]
    return urlencode(kept, doseq=True)


def normalise_url(url: str) -> str:
    """Light normalisation: drop fragment, trailing slash, lowercase
    scheme/host/path, fold default-document tails (``/index.php`` → ``/``,
    ticket 102), strip known tracking query params (intent_overlap.py:222).
    """
    if not url or not isinstance(url, str):
        return ""
    url = url.strip().split("#", 1)[0]
    p = urlparse(url)
    path = _fold_index_document(p.path.lower())
    path = path.rstrip("/") or "/"
    q = _strip_tracking_query(p.query)
    q = f"?{q}" if q else ""
    return f"{p.scheme.lower()}://{p.netloc.lower()}{path}{q}"


UrlRelation = Literal["parent-child", "sibling", "same-section", "cross-section"]


def _path_segments(path: str) -> list[str]:
    """Split a URL path into non-empty segments (``/a/b/`` -> ``["a", "b"]``)."""
    return [seg for seg in path.strip("/").split("/") if seg]


def section_of(url: str) -> str:
    """First path segment of *url* (ticket 101); ``/`` for the homepage.

    Normalises first (``normalise_url``) so trailing slashes / tracking
    params don't change the answer.
    """
    segs = _path_segments(urlparse(normalise_url(url)).path)
    return segs[0] if segs else "/"


def path_depth(url: str) -> int:
    """Number of non-empty path segments of *url* (ticket 101); ``0`` for the
    homepage. Used to pick the shallowest ("hub") page as the natural
    canonical survivor of an all-parent-child cluster.
    """
    return len(_path_segments(urlparse(normalise_url(url)).path))


def classify_relation(url_a: str, url_b: str) -> UrlRelation:
    """Classify the URL-path relationship between two same-host URLs (ticket 101).

    Both URLs are normalised first (``normalise_url``) so trailing slashes,
    tracking query params, and casing don't affect the result; only the path
    is compared (query strings are ignored beyond that normalisation).  Path
    comparison is segment-wise, not a raw string prefix, so ``/video`` is not
    considered a parent of ``/videos`` (intent_overlap.py has no analogue —
    this is new classification logic per ticket 101).

    Returns:
      - ``parent-child``: one URL's path is a segment-wise prefix of the
        other's (either direction). The homepage (``/``) is a trivial prefix
        of every path, so homepage-vs-anything is parent-child too.
      - ``sibling``: same immediate parent directory, i.e. same depth and
        identical path up to the last segment. Depth-1 pages are excluded
        from this (their "parent directory" is always the root, which would
        make every pair of top-level pages a false-positive sibling) — two
        different top-level pages are ``cross-section`` instead, unless they
        share a first segment (impossible unless identical).  Two URLs that
        normalise to the exact same path (e.g. differ only by a dropped
        tracking query param) also count as siblings.
      - ``same-section``: same first path segment, but not parent-child or
        sibling (e.g. different sub-directories under the same top-level
        section).
      - ``cross-section``: everything else, including cross-host pairs.
    """
    pa = urlparse(normalise_url(url_a))
    pb = urlparse(normalise_url(url_b))
    if pa.netloc != pb.netloc:
        return "cross-section"

    segs_a = _path_segments(pa.path)
    segs_b = _path_segments(pb.path)

    if segs_a == segs_b:
        return "sibling"

    shorter, longer = (segs_a, segs_b) if len(segs_a) < len(segs_b) else (segs_b, segs_a)
    if longer[: len(shorter)] == shorter:
        return "parent-child"

    if len(segs_a) == len(segs_b) and len(segs_a) >= 2 and segs_a[:-1] == segs_b[:-1]:
        return "sibling"

    if segs_a and segs_b and segs_a[0] == segs_b[0]:
        return "same-section"

    return "cross-section"


def lang_bucket(code: Any) -> str:
    """Primary language subtag (``en-us`` -> ``en``); ``unknown`` when absent
    (intent_overlap.py:1108)."""
    return code.split("-")[0].lower() if isinstance(code, str) and code else "unknown"


class UnionFind:
    """Path-halving union-find (intent_overlap.py:800)."""

    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


@dataclass(slots=True)
class HreflangGrouping:
    # url -> group id (only URLs in a component of size > 1)
    groups_by_url: dict[str, str] = field(default_factory=dict)
    # normalized url -> declared language of that page (from alternates)
    self_lang_by_norm: dict[str, str] = field(default_factory=dict)
    group_count: int = 0


def build_groups(edges: Iterable[tuple[str, str, str | None]]) -> HreflangGrouping:
    """Union-find over hreflang edges (any source), keyed by normalized URL.

    *edges* is an iterable of ``(url, alt_url, hreflang_code)``.  Components of
    size > 1 get stable ids ``H%04d`` ordered by their lexicographically-first
    member.  Also records each normalized page's own declared language from the
    alternates that point at it (intent_overlap.py:816).
    """
    edges = [e for e in edges if e[0] and e[1]]
    result = HreflangGrouping()
    if not edges:
        return result

    idx: dict[str, int] = {}
    norms: list[str] = []

    def gi(u: str) -> int:
        n = normalise_url(u)
        if n not in idx:
            idx[n] = len(norms)
            norms.append(n)
        return idx[n]

    # Size up-front to the number of distinct normalized endpoints.
    uf = UnionFind(len({normalise_url(u) for e in edges for u in e[:2]}))
    self_lang: dict[str, str] = {}
    for u, a, h in edges:
        iu, ia = gi(u), gi(a)
        uf.union(iu, ia)
        if h and h != "x-default":
            self_lang.setdefault(norms[ia], h)

    comp: dict[int, list[str]] = {}
    for n in norms:
        comp.setdefault(uf.find(idx[n]), []).append(n)
    groups_by_norm = {
        m: f"H{k:04d}"
        for k, members in enumerate(sorted((v for v in comp.values() if len(v) > 1), key=lambda v: sorted(v)[0]))
        for m in members
    }
    result.self_lang_by_norm = self_lang
    result.group_count = len(set(groups_by_norm.values()))
    # Expose group ids keyed by normalized URL (callers map their page URLs in).
    result.groups_by_url = groups_by_norm
    return result


def reciprocity_issues(
    edges: Iterable[tuple[str, str, str | None]],
) -> list[dict[str, str]]:
    """Alternates that don't link back (intent_overlap.py:867).

    Caveat preserved from upstream: on a partial crawl a missing return link may
    just mean the target wasn't crawled — treat as leads.
    """
    edges = list(edges)
    have = {(normalise_url(u), normalise_url(a)) for u, a, _ in edges}
    return [
        {
            "url": u,
            "declares_alternate": a,
            "hreflang": h or "",
            "issue": "no return link from alternate",
        }
        for u, a, h in edges
        if normalise_url(u) != normalise_url(a) and (normalise_url(a), normalise_url(u)) not in have
    ]


def _rep_rank(item: Mapping[str, Any]) -> tuple[int, int, int, int, str]:
    """Representative ranking within a norm_url group (intent_overlap.py:455):
    prefer non-redirected, then 200, then higher word_count, then shorter URL,
    then lexical."""
    redirected = 1 if item.get("redirected") else 0
    non200 = 0 if item.get("status") == 200 else 1
    return (redirected, non200, -int(item.get("word_count") or 0), len(item["url"]), item["url"])


@dataclass(slots=True)
class VariantResolution:
    # variant url -> representative url
    variant_of: dict[str, str] = field(default_factory=dict)
    representatives: list[str] = field(default_factory=list)


def resolve_variants(pages: Sequence[Mapping[str, Any]]) -> VariantResolution:
    """One representative per normalized URL; others are variants
    (intent_overlap.py:445).

    *pages* is a sequence of mappings with ``url``, optional ``norm_url``,
    ``status``, ``redirected`` and ``word_count``.  A self-normalising redirect
    (source and target share a norm_url) simply folds into its group and is
    never dropped; only groups of size > 1 produce variants.
    """
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for page in pages:
        norm = page.get("norm_url") or normalise_url(str(page["url"]))
        groups.setdefault(norm, []).append(page)

    resolution = VariantResolution()
    for _norm, members in groups.items():
        if len(members) < 2:
            continue
        ranked = sorted(members, key=_rep_rank)
        rep = str(ranked[0]["url"])
        resolution.representatives.append(rep)
        for m in ranked[1:]:
            resolution.variant_of[str(m["url"])] = rep
    return resolution


def resolve_language(
    declared_code: str | None,
    html_lang: str | None,
) -> tuple[str | None, str]:
    """Resolve a page's language: hreflang-declared code, else ``<html lang>``;
    return ``(resolved_code, lang_bucket)`` (intent_overlap.py:581/1108)."""
    code = declared_code or (html_lang.strip().lower() if html_lang else None) or None
    return code, lang_bucket(code)


@dataclass(slots=True)
class IdentityResult:
    pages: int = 0
    groups: int = 0
    grouped_urls: int = 0
    variants: int = 0
    representatives: int = 0
    reciprocity_issues: int = 0


async def build_and_store_identity(store: AsyncpgStore, *, run_id: str | None = None) -> IdentityResult:
    """Build hreflang groups, resolve languages, and fold URL variants over a
    crawl, persisting the results (ticket 078).  Reads only crawler-captured
    data; no external input.
    """
    edges = await store.fetch_hreflang_edges(**({"run_id": run_id} if run_id is not None else {}))
    grouping = build_groups(edges)
    pages = await store.fetch_pages_for_identity(**({"run_id": run_id} if run_id is not None else {}))

    result = IdentityResult(pages=len(pages))
    result.groups = grouping.group_count
    result.reciprocity_issues = len(reciprocity_issues(edges))

    # Per-page identity: norm_url, group, resolved language + bucket.
    identity_rows: list[HreflangIdentityRow] = []
    variant_input: list[dict[str, Any]] = []
    url_to_id: dict[str, int] = {}
    for page in pages:
        url = str(page["url"])
        url_to_id[url] = int(page["url_id"])
        norm = normalise_url(url)
        group = grouping.groups_by_url.get(norm)
        declared = grouping.self_lang_by_norm.get(norm)
        code, bucket = resolve_language(declared, page.get("html_lang"))
        identity_rows.append(
            {
                "url_id": int(page["url_id"]),
                "norm_url": norm,
                "hreflang_group": group,
                "resolved_hreflang_code": code,
                "lang_bucket": bucket,
            }
        )
        redirected = bool(page.get("final_url") and page["final_url"] != url)
        variant_input.append(
            {
                "url": url,
                "norm_url": norm,
                "status": page.get("status"),
                "word_count": page.get("word_count"),
                "redirected": redirected,
            }
        )

    if run_id is None:
        await store.store_hreflang_identity(identity_rows)
    else:
        await store.store_hreflang_identity(identity_rows, run_id=run_id)
    result.grouped_urls = sum(1 for r in identity_rows if r["hreflang_group"])

    resolution = resolve_variants(variant_input)
    variant_pairs = [
        (url_to_id[variant], url_to_id[rep])
        for variant, rep in resolution.variant_of.items()
        if variant in url_to_id and rep in url_to_id
    ]
    if run_id is None:
        await store.store_url_variants(variant_pairs)
    else:
        await store.store_url_variants(variant_pairs, run_id=run_id)
    result.variants = len(variant_pairs)
    result.representatives = len(resolution.representatives)
    return result
