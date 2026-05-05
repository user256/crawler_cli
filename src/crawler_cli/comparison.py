from __future__ import annotations

from dataclasses import dataclass, field

from .models import CrawlJobResult, CrawlResult


@dataclass(slots=True)
class CrawlDiff:
    missing_urls: list[str] = field(default_factory=list)
    new_urls: list[str] = field(default_factory=list)
    canonical_changes: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)
    content_hash_mismatches: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)


def compare(baseline: CrawlJobResult | list[CrawlResult], candidate: CrawlJobResult | list[CrawlResult]) -> CrawlDiff:
    baseline_results = baseline.results if isinstance(baseline, CrawlJobResult) else baseline
    candidate_results = candidate.results if isinstance(candidate, CrawlJobResult) else candidate

    base_map = {result.final_url: result for result in baseline_results}
    cand_map = {result.final_url: result for result in candidate_results}

    diff = CrawlDiff()
    base_urls = set(base_map)
    cand_urls = set(cand_map)
    diff.missing_urls = sorted(base_urls - cand_urls)
    diff.new_urls = sorted(cand_urls - base_urls)

    for url in sorted(base_urls & cand_urls):
        base_result = base_map[url]
        cand_result = cand_map[url]
        base_canonical = base_result.extracted.canonical if base_result.extracted else None
        cand_canonical = cand_result.extracted.canonical if cand_result.extracted else None
        if base_canonical != cand_canonical:
            diff.canonical_changes[url] = (base_canonical, cand_canonical)
        if base_result.content_hash_sha256 != cand_result.content_hash_sha256:
            diff.content_hash_mismatches[url] = (
                base_result.content_hash_sha256,
                cand_result.content_hash_sha256,
            )
    return diff

