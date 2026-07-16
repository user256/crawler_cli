from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from .hashing import hamming64
from .models import CrawlJobResult, CrawlResult, DiscoveredLink
from .remap import Remap

DEFAULT_SIMHASH_THRESHOLD = 4
"""Default Hamming distance under which two pages are treated as *near*-duplicates
rather than *changed* (ticket 122). Chosen small: a dev-vs-prod page that differs
only by a banner/footer typically lands at a distance of a handful of bits."""


@dataclass(slots=True)
class UrlMove:
    from_path: str
    to_path: str
    redirect_chain: str
    baseline_final_url: str
    candidate_final_url: str | None = None


@dataclass(slots=True)
class ContentFieldChange:
    field: str
    baseline: str | int | None
    candidate: str | int | None


@dataclass(slots=True)
class LinkChange:
    path: str
    added: list[dict[str, object]] = field(default_factory=list)
    removed: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class CrawlDiff:
    missing_urls: list[str] = field(default_factory=list)
    new_urls: list[str] = field(default_factory=list)
    canonical_changes: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)
    content_hash_mismatches: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)


@dataclass(slots=True)
class DeepCrawlDiff(CrawlDiff):
    baseline_urls_by_path: dict[str, str] = field(default_factory=dict)
    candidate_urls_by_path: dict[str, str] = field(default_factory=dict)
    title_changes: dict[str, ContentFieldChange] = field(default_factory=dict)
    h1_changes: dict[str, ContentFieldChange] = field(default_factory=dict)
    meta_description_changes: dict[str, ContentFieldChange] = field(default_factory=dict)
    word_count_changes: dict[str, ContentFieldChange] = field(default_factory=dict)
    url_moves: list[UrlMove] = field(default_factory=list)
    schema_changes: dict[str, tuple[list[str], list[str]]] = field(default_factory=dict)
    link_changes: dict[str, LinkChange] = field(default_factory=dict)
    simhash_distances: dict[str, int | None] = field(default_factory=dict)
    content_verdicts: dict[str, str] = field(default_factory=dict)


def _path_of(url: str) -> str:
    return urlparse(url).path or "/"


def _content_hashes(result: CrawlResult, remap: Remap | None) -> tuple[str | None, int | None]:
    """Return ``(sha256, simhash64)`` for *result* (ticket 122).

    With a remap active, re-hash remapped content so host-derived text
    differences don't break equality. Without one, prefer the stored hashes but
    compute from ``raw_html``/text when both are absent — so a verdict is still
    available for crawls that ran without ``--content-hashing`` or artifacts that
    predate it. Falls back to the stored (possibly ``None``) hashes when there is
    nothing to hash (e.g. a store-loaded row carrying no raw_html)."""
    stored = (result.content_hash_sha256, result.content_hash_simhash)
    text = result.extracted.text if result.extracted else None
    if remap:
        rehashed = remap.rehash(raw_html=result.raw_html, text=text)
        return stored if rehashed == (None, None) else rehashed
    if stored == (None, None):
        computed = Remap().rehash(raw_html=result.raw_html, text=text)
        if computed != (None, None):
            return computed
    return stored


def _content_verdict(
    base_sha: str | None,
    cand_sha: str | None,
    distance: int | None,
    threshold: int,
) -> str:
    """Classify a shared page: ``identical`` (sha256 equal, incl. both absent),
    ``near`` (simhash within *threshold*), else ``changed``."""
    if base_sha == cand_sha:
        return "identical"
    if distance is not None and distance <= threshold:
        return "near"
    return "changed"


@dataclass(slots=True)
class ContentComparison:
    """sha256/simhash comparison between two pages (ticket 122)."""

    sha256_equal: bool
    simhash_distance: int | None
    verdict: str


def content_comparison(
    base: CrawlResult,
    cand: CrawlResult,
    *,
    remap: Remap | None = None,
    simhash_threshold: int = DEFAULT_SIMHASH_THRESHOLD,
) -> ContentComparison:
    """Compare two pages' content with optional remapping and simhash tolerance.

    Shared by :func:`compare_deep` (path-keyed near-site diff) and the
    ``compare-urls`` pair comparer, so both classify content the same way."""
    base_sha, base_sim = _content_hashes(base, remap)
    cand_sha, cand_sim = _content_hashes(cand, remap)
    distance = hamming64(base_sim, cand_sim) if base_sim is not None and cand_sim is not None else None
    return ContentComparison(
        sha256_equal=base_sha == cand_sha,
        simhash_distance=distance,
        verdict=_content_verdict(base_sha, cand_sha, distance, simhash_threshold),
    )


def _first_h1(result: CrawlResult) -> str | None:
    if not result.extracted:
        return None
    headings = result.extracted.headings.get("h1") or []
    return headings[0] if headings else None


def _schema_types(result: CrawlResult) -> list[str]:
    if not result.extracted:
        return []
    types = sorted(
        {
            str(item.get("type"))
            for item in result.extracted.schema_data
            if item.get("type") and item.get("is_valid", True)
        }
    )
    return types


def _link_signature(link: DiscoveredLink) -> tuple[str, str | None]:
    return link.href, link.anchor_text


def _link_payload(link: DiscoveredLink) -> dict[str, object]:
    return {
        "href": link.href,
        "anchor_text": link.anchor_text,
        "xpath": link.xpath,
        "is_image": link.is_image,
    }


def compare(baseline: CrawlJobResult | list[CrawlResult], candidate: CrawlJobResult | list[CrawlResult]) -> CrawlDiff:
    deep = compare_deep(baseline, candidate, compare_links=False)
    return CrawlDiff(
        missing_urls=deep.missing_urls,
        new_urls=deep.new_urls,
        canonical_changes=deep.canonical_changes,
        content_hash_mismatches=deep.content_hash_mismatches,
    )


def compare_deep(
    baseline: CrawlJobResult | list[CrawlResult],
    candidate: CrawlJobResult | list[CrawlResult],
    *,
    compare_links: bool = True,
    remap: Remap | None = None,
    simhash_threshold: int = DEFAULT_SIMHASH_THRESHOLD,
) -> DeepCrawlDiff:
    baseline_results = baseline.results if isinstance(baseline, CrawlJobResult) else baseline
    candidate_results = candidate.results if isinstance(candidate, CrawlJobResult) else candidate

    def _key(url: str) -> str:
        # Remap the URL (e.g. dev host -> prod host, /en/… -> /…) before keying so
        # the same logical page lines up across hosts and path renames.
        return _path_of(remap.apply_to_url(url) if remap else url)

    diff = DeepCrawlDiff()
    base_by_path: dict[str, CrawlResult] = {}
    cand_by_path: dict[str, CrawlResult] = {}
    for result in baseline_results:
        path = _key(result.final_url)
        base_by_path[path] = result
        diff.baseline_urls_by_path[path] = result.final_url
    for result in candidate_results:
        path = _key(result.final_url)
        cand_by_path[path] = result
        diff.candidate_urls_by_path[path] = result.final_url
    base_paths = set(base_by_path)
    cand_paths = set(cand_by_path)
    diff.missing_urls = sorted(base_by_path[path].final_url for path in sorted(base_paths - cand_paths))
    diff.new_urls = sorted(cand_by_path[path].final_url for path in sorted(cand_paths - base_paths))

    for path in sorted(base_paths):
        base_result = base_by_path[path]
        if base_result.requested_url != base_result.final_url:
            from_path = _key(base_result.requested_url)
            to_path = _key(base_result.final_url)
            if from_path != to_path:
                candidate_at_dest = cand_by_path.get(to_path)
                diff.url_moves.append(
                    UrlMove(
                        from_path=from_path,
                        to_path=to_path,
                        redirect_chain=f"{from_path} -> {to_path}",
                        baseline_final_url=base_result.final_url,
                        candidate_final_url=candidate_at_dest.final_url if candidate_at_dest else None,
                    )
                )

    for path in sorted(base_paths & cand_paths):
        base_result = base_by_path[path]
        cand_result = cand_by_path[path]

        base_canonical = base_result.extracted.canonical if base_result.extracted else None
        cand_canonical = cand_result.extracted.canonical if cand_result.extracted else None
        # Remap canonical URLs before comparing so a dev canonical pointing at the
        # dev host isn't reported as a change against its prod equivalent.
        if remap:
            base_canonical_cmp = remap.apply_to_url(base_canonical)
            cand_canonical_cmp = remap.apply_to_url(cand_canonical)
        else:
            base_canonical_cmp, cand_canonical_cmp = base_canonical, cand_canonical
        if base_canonical_cmp != cand_canonical_cmp:
            diff.canonical_changes[base_result.final_url] = (base_canonical, cand_canonical)

        content = content_comparison(base_result, cand_result, remap=remap, simhash_threshold=simhash_threshold)
        diff.simhash_distances[path] = content.simhash_distance
        diff.content_verdicts[path] = content.verdict
        if not content.sha256_equal:
            base_sha, _ = _content_hashes(base_result, remap)
            cand_sha, _ = _content_hashes(cand_result, remap)
            diff.content_hash_mismatches[base_result.final_url] = (base_sha, cand_sha)

        base_title = base_result.extracted.title if base_result.extracted else None
        cand_title = cand_result.extracted.title if cand_result.extracted else None
        if base_title != cand_title:
            diff.title_changes[path] = ContentFieldChange("title", base_title, cand_title)

        base_h1 = _first_h1(base_result)
        cand_h1 = _first_h1(cand_result)
        if base_h1 != cand_h1:
            diff.h1_changes[path] = ContentFieldChange("h1", base_h1, cand_h1)

        base_meta = base_result.extracted.meta_description if base_result.extracted else None
        cand_meta = cand_result.extracted.meta_description if cand_result.extracted else None
        if base_meta != cand_meta:
            diff.meta_description_changes[path] = ContentFieldChange(
                "meta_description",
                base_meta,
                cand_meta,
            )

        base_words = base_result.extracted.word_count if base_result.extracted else None
        cand_words = cand_result.extracted.word_count if cand_result.extracted else None
        if base_words != cand_words:
            diff.word_count_changes[path] = ContentFieldChange("word_count", base_words, cand_words)

        base_schema = _schema_types(base_result)
        cand_schema = _schema_types(cand_result)
        if base_schema != cand_schema:
            diff.schema_changes[path] = (base_schema, cand_schema)

        if compare_links:
            # Remap link hrefs before signing so cross-host links (dev vs prod)
            # don't every show up as added+removed noise.
            def _sig(link: DiscoveredLink) -> tuple[str, str | None]:
                href, anchor = _link_signature(link)
                return (remap.apply_to_url(href) or href, anchor) if remap else (href, anchor)

            base_links = {_sig(link): link for link in base_result.discovered_links}
            cand_links = {_sig(link): link for link in cand_result.discovered_links}
            added_keys = set(cand_links) - set(base_links)
            removed_keys = set(base_links) - set(cand_links)
            if added_keys or removed_keys:
                diff.link_changes[path] = LinkChange(
                    path=path,
                    added=[_link_payload(cand_links[key]) for key in sorted(added_keys)],
                    removed=[_link_payload(base_links[key]) for key in sorted(removed_keys)],
                )

    return diff


def comparison_rows(diff: DeepCrawlDiff) -> list[dict[str, object]]:
    paths = sorted(
        set(diff.baseline_urls_by_path)
        | set(diff.candidate_urls_by_path)
        | set(diff.title_changes)
        | set(diff.h1_changes)
        | set(diff.meta_description_changes)
        | set(diff.word_count_changes)
        | set(diff.schema_changes)
        | set(diff.link_changes)
        | {move.from_path for move in diff.url_moves}
    )
    rows: list[dict[str, object]] = []
    for path in paths:
        title = diff.title_changes.get(path)
        h1 = diff.h1_changes.get(path)
        meta = diff.meta_description_changes.get(path)
        words = diff.word_count_changes.get(path)
        schema = diff.schema_changes.get(path)
        links = diff.link_changes.get(path)
        move = next((item for item in diff.url_moves if item.from_path == path), None)
        on_baseline = path in diff.baseline_urls_by_path
        on_candidate = path in diff.candidate_urls_by_path
        # ``missing`` when the page exists on only one side; otherwise the
        # content verdict computed from sha256 + simhash distance.
        content_verdict = diff.content_verdicts.get(path) if (on_baseline and on_candidate) else "missing"
        rows.append(
            {
                "path": path,
                "baseline_url": diff.baseline_urls_by_path.get(path),
                "candidate_url": diff.candidate_urls_by_path.get(path),
                "exists_on_baseline": on_baseline,
                "exists_on_candidate": on_candidate,
                "content_verdict": content_verdict,
                "simhash_distance": diff.simhash_distances.get(path),
                "baseline_title": title.baseline if title else None,
                "candidate_title": title.candidate if title else None,
                "baseline_h1": h1.baseline if h1 else None,
                "candidate_h1": h1.candidate if h1 else None,
                "baseline_meta_description": meta.baseline if meta else None,
                "candidate_meta_description": meta.candidate if meta else None,
                "baseline_word_count": words.baseline if words else None,
                "candidate_word_count": words.candidate if words else None,
                "is_moved_content": move is not None,
                "moved_from_path": move.from_path if move else None,
                "moved_to_path": move.to_path if move else None,
                "redirect_chain": move.redirect_chain if move else None,
                "baseline_schema_types": schema[0] if schema else [],
                "candidate_schema_types": schema[1] if schema else [],
                "links_added": links.added if links else [],
                "links_removed": links.removed if links else [],
            }
        )
    return rows
