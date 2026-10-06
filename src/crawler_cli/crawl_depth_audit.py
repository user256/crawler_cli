"""Pure, bounded evidence for technical-audit Q44 crawl depth.

The crawler owns shortest-path calculation and persistence.  This module does
not attempt to recreate it from a partial edge list: it evaluates the saved
depths only when the caller explicitly declares their root and coverage.  In
particular, a missing root, incomplete graph, or unknown depth can never be
reported as a healthy priority landing page.

Saved page records have a ``url`` and may have ``crawl_depth`` (or the legacy
``depth`` alias).  The graph record must explicitly contain ``root_urls``,
``depths_from_roots`` and ``coverage_complete``.  A site profile supplies
``templates.priority.pattern`` and ``commercial_hubs``.  Priority is the
union of the matching template pages and listed hubs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import re
from typing import Literal
from urllib.parse import urlsplit, urlunsplit


FactOutcome = Literal["finding", "observed", "unavailable"]


@dataclass(frozen=True)
class CrawlDepthFact:
    """One priority URL's saved click-depth evidence."""

    url: str
    outcome: FactOutcome
    priority_sources: tuple[str, ...]
    crawl_depth: int | None
    max_depth: int
    rule: str

    def as_dict(self) -> dict[str, object]:
        """Return evidence ready for a report detail tab."""

        return asdict(self)


@dataclass(frozen=True)
class CrawlDepthCheck:
    """Q44 facts, eligibility, and coverage without a report-layer verdict.

    ``available`` describes whether a valid priority policy was supplied.
    ``complete`` says whether the root-qualified graph and every observed
    priority URL have enough evidence to rule out an issue.  ``eligible`` is
    false when the crawl contains no priority URLs at all, so that an empty
    population cannot masquerade as a pass.
    """

    available: bool
    complete: bool
    eligible: bool
    denominator: int
    max_depth: int
    facts: tuple[CrawlDepthFact, ...]
    unavailable_reasons: tuple[str, ...] = ()
    facts_truncated: bool = False

    @property
    def affected(self) -> tuple[CrawlDepthFact, ...]:
        """Priority pages beyond Q44's configured depth."""

        return tuple(fact for fact in self.facts if fact.outcome == "finding")

    @property
    def threshold_breached(self) -> bool:
        """Q44 fires once one priority page is deeper than ``max_depth``."""

        return bool(self.affected)


def analyse_priority_crawl_depth(
    pages: Sequence[Mapping[str, object]],
    graph: Mapping[str, object] | None,
    site_profile: Mapping[str, object] | None,
    *,
    max_depth: int = 3,
    max_facts: int = 500,
) -> CrawlDepthCheck:
    """Evaluate Q44 from supplied page depths and an explicit graph contract.

    The function preserves input order and retains no more than ``max_facts``
    records.  It never infers a homepage, treats a missing depth as zero, or
    treats an incomplete crawl graph as a clean depth result.
    """

    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0:
        raise ValueError("max_depth must be a non-negative integer")
    if isinstance(max_facts, bool) or not isinstance(max_facts, int) or max_facts < 1:
        raise ValueError("max_facts must be at least 1")

    reasons: set[str] = set()
    priority_pattern, commercial_hubs = _priority_policy(site_profile, reasons)
    available = priority_pattern is not None and commercial_hubs is not None
    roots = _roots(graph, reasons)
    graph_complete = _graph_complete(graph, reasons)
    saved_pages = tuple(page for page in pages if isinstance(page, Mapping))
    if len(saved_pages) != len(pages):
        reasons.add("invalid_saved_page_record")

    records: dict[str, Mapping[str, object]] = {}
    priority_sources: dict[str, set[str]] = {}
    for page in saved_pages:
        url = _url(page)
        if url is None:
            reasons.add("missing_page_url")
            continue
        normalised = _normalise_url(url)
        if normalised in records:
            reasons.add("duplicate_saved_page_url")
            continue
        records[normalised] = page
        if priority_pattern is not None and _matches(priority_pattern, url):
            priority_sources.setdefault(normalised, set()).add("templates.priority")

    if commercial_hubs is not None:
        for hub in commercial_hubs:
            priority_sources.setdefault(hub, set()).add("commercial_hubs")

    _verify_roots(records, roots, reasons)
    facts: list[CrawlDepthFact] = []
    truncated = False
    for url, sources in priority_sources.items():
        page = records.get(url)
        depth = _depth(page) if page is not None else None
        if page is None:
            reasons.add("priority_hub_not_observed")
        elif depth is None:
            reasons.add("missing_or_invalid_crawl_depth")
        outcome: FactOutcome
        if page is None or depth is None:
            outcome = "unavailable"
        elif depth > max_depth:
            outcome = "finding"
        else:
            outcome = "observed"
        fact = CrawlDepthFact(
            url=url,
            outcome=outcome,
            priority_sources=tuple(sorted(sources)),
            crawl_depth=depth,
            max_depth=max_depth,
            rule="priority landing page must be reachable within the configured click depth",
        )
        if len(facts) < max_facts:
            facts.append(fact)
        else:
            truncated = True

    if not priority_sources:
        reasons.add("no_priority_pages_observed")
    if truncated:
        reasons.add("facts_truncated")
    complete = available and graph_complete and not reasons and not truncated
    return CrawlDepthCheck(
        available=available,
        complete=complete,
        eligible=bool(priority_sources),
        denominator=len(priority_sources),
        max_depth=max_depth,
        facts=tuple(facts),
        unavailable_reasons=tuple(sorted(reasons)),
        facts_truncated=truncated,
    )


def _priority_policy(
    profile: Mapping[str, object] | None, reasons: set[str]
) -> tuple[re.Pattern[str] | None, tuple[str, ...] | None]:
    if profile is None:
        reasons.add("missing_site_profile")
        return None, None
    templates = profile.get("templates")
    priority = templates.get("priority") if isinstance(templates, Mapping) else None
    pattern = priority.get("pattern") if isinstance(priority, Mapping) else None
    compiled: re.Pattern[str] | None = None
    if not isinstance(pattern, str) or not pattern:
        reasons.add("missing_profile_template:priority")
    else:
        try:
            compiled = re.compile(pattern)
        except re.error:
            reasons.add("invalid_profile_template_pattern:priority")

    configured_hubs = profile.get("commercial_hubs")
    if not isinstance(configured_hubs, Sequence) or isinstance(configured_hubs, (str, bytes)):
        reasons.add("missing_commercial_hubs")
        return compiled, None
    hubs: list[str] = []
    for value in configured_hubs:
        if not isinstance(value, str) or not value:
            reasons.add("invalid_commercial_hub")
            continue
        hubs.append(_normalise_url(value))
    return compiled, tuple(hubs)


def _roots(graph: Mapping[str, object] | None, reasons: set[str]) -> tuple[str, ...]:
    raw_roots = graph.get("root_urls") if isinstance(graph, Mapping) else None
    if not isinstance(raw_roots, Sequence) or isinstance(raw_roots, (str, bytes)) or not raw_roots:
        reasons.add("missing_graph_root_urls")
        return ()
    roots: list[str] = []
    for root in raw_roots:
        if not isinstance(root, str) or not root:
            reasons.add("invalid_graph_root_url")
            continue
        roots.append(_normalise_url(root))
    if not roots:
        reasons.add("missing_graph_root_urls")
    return tuple(roots)


def _graph_complete(graph: Mapping[str, object] | None, reasons: set[str]) -> bool:
    if not isinstance(graph, Mapping):
        reasons.add("missing_graph_evidence")
        return False
    if graph.get("depths_from_roots") is not True:
        reasons.add("depths_not_verified_from_declared_roots")
    if graph.get("coverage_complete") is not True:
        reasons.add("incomplete_graph_coverage")
    return graph.get("depths_from_roots") is True and graph.get("coverage_complete") is True


def _verify_roots(
    records: Mapping[str, Mapping[str, object]], roots: Sequence[str], reasons: set[str]
) -> None:
    if not roots:
        return
    if not any(_depth(records.get(root)) == 0 for root in roots):
        reasons.add("no_declared_root_verified_at_depth_zero")


def _matches(pattern: re.Pattern[str], url: str) -> bool:
    parsed = urlsplit(url)
    return pattern.search(parsed.path + (f"?{parsed.query}" if parsed.query else "")) is not None


def _url(page: Mapping[str, object]) -> str | None:
    value = page.get("url")
    return value if isinstance(value, str) and value else None


def _depth(page: Mapping[str, object] | None) -> int | None:
    if page is None:
        return None
    value = page.get("crawl_depth", page.get("depth"))
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _normalise_url(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))
