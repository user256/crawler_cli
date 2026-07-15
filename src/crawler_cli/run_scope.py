"""Deterministic crawl-run selection for reports and enrichment (ticket 095).

Data layers
-----------
Immutable per fetch/run
    ``page_run_snapshots`` (and frontier / crawl_metadata keyed by ``run_id``):
    page metadata, extracted content, hashes, detections, links, schema,
    canonicals/hreflang, and indexability as observed in that crawl run.

Current URL identity / deduplicated lookups
    ``urls`` plus lookup tables (``meta_descriptions``, ``html_languages``,
    ``schema_instances``, ``analytics_vendors``, …). These are shared across
    runs.

Current-state convenience
    ``pages`` / ``content`` / ``page_metadata`` / satellite fact tables and
    ``url_current_state`` always reflect the latest successful write. Prefer
    snapshots whenever a concrete ``run_id`` is in play.
"""

from __future__ import annotations

from typing import Protocol


class RunSelectionError(ValueError):
    """Raised when a reporting/enrichment command cannot pick a single crawl run."""


class SupportsCrawlRunListing(Protocol):
    async def list_crawl_runs(self, *, include_legacy: bool = True) -> list[dict]: ...

    async def get_crawl_run(self, run_id: str) -> dict | None: ...


async def resolve_reporting_run_id(
    store: SupportsCrawlRunListing,
    explicit_run_id: str | None = None,
    *,
    allow_legacy_fallback: bool = True,
) -> str:
    """Resolve which crawl run a report/enrichment command should use.

    Rules:
    - Explicit ``--crawl-run-id`` wins (must exist).
    - Else if exactly one non-legacy run exists, use it.
    - Else if no non-legacy runs and legacy fallback is allowed, use ``legacy``.
    - Else raise :class:`RunSelectionError` listing candidates.
    """
    from .persistence import DEFAULT_CRAWL_RUN_ID

    if explicit_run_id:
        existing = await store.get_crawl_run(explicit_run_id)
        if existing is None:
            raise RunSelectionError(f"crawl run not found: {explicit_run_id}")
        return explicit_run_id

    non_legacy = await store.list_crawl_runs(include_legacy=False)
    if len(non_legacy) == 1:
        return str(non_legacy[0]["run_id"])
    if len(non_legacy) == 0 and allow_legacy_fallback:
        legacy = await store.get_crawl_run(DEFAULT_CRAWL_RUN_ID)
        if legacy is not None:
            return DEFAULT_CRAWL_RUN_ID
        raise RunSelectionError("no crawl runs found in database")

    candidates = [str(run["run_id"]) for run in non_legacy]
    preview = ", ".join(candidates[:8])
    more = "" if len(candidates) <= 8 else f" (+{len(candidates) - 8} more)"
    raise RunSelectionError(
        "multiple crawl runs present; pass --crawl-run-id to select one. "
        f"Candidates: {preview}{more}"
    )
