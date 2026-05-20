from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from .models import CrawlJobResult, CrawlResult, DiscoveredLink


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


def _path_of(url: str) -> str:
    return urlparse(url).path or "/"


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
) -> DeepCrawlDiff:
    baseline_results = baseline.results if isinstance(baseline, CrawlJobResult) else baseline
    candidate_results = candidate.results if isinstance(candidate, CrawlJobResult) else candidate

    diff = DeepCrawlDiff()
    base_by_path: dict[str, CrawlResult] = {}
    cand_by_path: dict[str, CrawlResult] = {}
    for result in baseline_results:
        path = _path_of(result.final_url)
        base_by_path[path] = result
        diff.baseline_urls_by_path[path] = result.final_url
    for result in candidate_results:
        path = _path_of(result.final_url)
        cand_by_path[path] = result
        diff.candidate_urls_by_path[path] = result.final_url
    base_paths = set(base_by_path)
    cand_paths = set(cand_by_path)
    diff.missing_urls = sorted(
        base_by_path[path].final_url for path in sorted(base_paths - cand_paths)
    )
    diff.new_urls = sorted(
        cand_by_path[path].final_url for path in sorted(cand_paths - base_paths)
    )

    for path in sorted(base_paths):
        base_result = base_by_path[path]
        if base_result.requested_url != base_result.final_url:
            from_path = _path_of(base_result.requested_url)
            to_path = _path_of(base_result.final_url)
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
        if base_canonical != cand_canonical:
            diff.canonical_changes[base_result.final_url] = (base_canonical, cand_canonical)

        if base_result.content_hash_sha256 != cand_result.content_hash_sha256:
            diff.content_hash_mismatches[base_result.final_url] = (
                base_result.content_hash_sha256,
                cand_result.content_hash_sha256,
            )

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
            base_links = {_link_signature(link): link for link in base_result.discovered_links}
            cand_links = {_link_signature(link): link for link in cand_result.discovered_links}
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
    missing_paths = {_path_of(url) for url in diff.missing_urls}
    new_paths = {_path_of(url) for url in diff.new_urls}
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
        rows.append(
            {
                "path": path,
                "baseline_url": diff.baseline_urls_by_path.get(path),
                "candidate_url": diff.candidate_urls_by_path.get(path),
                "exists_on_baseline": path in diff.baseline_urls_by_path,
                "exists_on_candidate": path in diff.candidate_urls_by_path,
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
