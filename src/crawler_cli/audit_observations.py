"""Run-scoped observation bundles for the technical-audit question runner.

Rendered, mobile, probe and supplied third-party evidence does not come from
the stored crawl itself. This module gives that evidence one versioned shape so
the question runner can consume it without trusting it blindly:

- every bundle names the crawl run it belongs to, and the runner refuses a
  bundle whose run differs from the audit's, so evidence never drifts between
  runs;
- every collection states its source, collection time, scope and whether it
  covers its whole population (``coverage_state``), so a sample can never be
  read as a complete population;
- every record of a kind carries that kind's identity fields.

Nothing here makes a network request. Adapters convert the artifacts of other
crawler_cli commands (``compare-renders``, ``exposure-inventory``) and stored
HTML into collections; supplied exports are written in this shape directly.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


OBSERVATIONS_SCHEMA_VERSION = "crawler-cli/audit-observations/1"
COVERAGE_STATES = ("complete", "partial")

# kind -> (what it is, identity fields every record must carry).  The answerers
# in technical_audit_questions read the remaining fields and treat a record
# that lacks the field a rule needs as untested for that rule.
OBSERVATION_KINDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "html-signals": ("signals extracted from stored raw HTML (technical-audit-observations)", ("url",)),
    "render-parity": ("raw versus rendered DOM comparison (compare-renders)", ("url", "state")),
    "render-trace": ("browser performance and network trace per page", ("url",)),
    "mobile-render": ("mobile-viewport render with overlay measurement", ("url",)),
    "listing-controls": ("filter and category controls observed in a rendered listing", ("url", "control")),
    "image-resources": ("fetched image responses with content types", ("image_url", "content_type")),
    "locale-probe": ("one URL fetched with a changed Accept-Language or egress country", ("url", "variant")),
    "host-probe": ("unauthenticated request to an alternate or non-production host", ("host",)),
    "utility-path-probe": ("unauthenticated request to a preview, draft, admin or CMS path", ("url",)),
    "external-link-recheck": ("live recheck of an outbound link", ("source_url", "target_url")),
    "tls-probe": ("HSTS header, HSTS preload status and OCSP stapling per host", ("host",)),
    "robots-txt": ("robots.txt response per host, with optional llms.txt presence", ("host", "status")),
    "google-render-inspection": (
        "supplied URL Inspection or Rich Results Test render per key template",
        ("url", "template", "tool"),
    ),
    "verified-google-fetch": ("supplied comparison of a verified Google fetch with a visitor fetch", ("url",)),
    "competitor-topic-gap": (
        "supplied entity or SERP fan-out comparison against competitors",
        ("topic", "site_covers", "competitors_covering"),
    ),
    # Recorded for Q104's manual review; the runner never answers from it.
    "search-host-review": (
        "manual GSC hostname segmentation or documented SERP check",
        ("review_type", "reviewed_at", "permitted_hosts"),
    ),
}


class ObservationError(ValueError):
    """An observation bundle is unreadable or breaks its contract."""


def load_observation_bundle(path: str | Path) -> dict[str, object]:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ObservationError(f"could not read observation bundle {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ObservationError(f"{target}: an observation bundle must be a JSON object")
    validate_observation_bundle(payload)
    return payload


def validate_observation_bundle(bundle: Mapping[str, object]) -> None:
    errors: list[str] = []
    if bundle.get("schema_version") != OBSERVATIONS_SCHEMA_VERSION:
        errors.append(f"schema_version must be {OBSERVATIONS_SCHEMA_VERSION!r}")
    if not _text(bundle.get("crawl_run_id")):
        errors.append("crawl_run_id is required: observations belong to one crawl run")
    collections = bundle.get("collections")
    if not isinstance(collections, list):
        errors.append("collections must be a list")
        collections = []
    for position, collection in enumerate(collections, start=1):
        label = f"collection {position}"
        if not isinstance(collection, Mapping):
            errors.append(f"{label}: must be an object")
            continue
        kind = collection.get("kind")
        if kind not in OBSERVATION_KINDS:
            errors.append(f"{label}: unknown kind {kind!r}")
            continue
        label = f"collection {position} ({kind})"
        for key in ("source", "scope"):
            if not _text(collection.get(key)):
                errors.append(f"{label}: {key} is required")
        if _parse_time(collection.get("collected_at")) is None:
            errors.append(f"{label}: collected_at must be an ISO 8601 timestamp")
        if collection.get("coverage_state") not in COVERAGE_STATES:
            errors.append(f"{label}: coverage_state must be one of {COVERAGE_STATES}")
        records = collection.get("records")
        if not isinstance(records, list):
            errors.append(f"{label}: records must be a list")
            continue
        identity = OBSERVATION_KINDS[str(kind)][1]
        for index, record in enumerate(records, start=1):
            if not isinstance(record, Mapping):
                errors.append(f"{label} record {index}: must be an object")
                continue
            missing = [key for key in identity if record.get(key) is None or record.get(key) == ""]
            if missing:
                errors.append(f"{label} record {index}: missing {', '.join(missing)}")
        if len(errors) > 20:
            break
    if errors:
        raise ObservationError("; ".join(errors[:20]))


def attach_observations(audit: Mapping[str, object], bundles: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Return a copy of the audit carrying the bundles' collections.

    A bundle from another crawl run is refused rather than merged: the runner's
    rows are keyed to the audit's run identity.
    """

    run_id = _text(audit.get("crawl_run_id"))
    existing = audit.get("observations")
    merged: list[dict[str, object]] = (
        [dict(item) for item in existing.get("collections", [])]  # type: ignore[union-attr]
        if isinstance(existing, Mapping)
        else []
    )
    for bundle in bundles:
        validate_observation_bundle(bundle)
        if _text(bundle.get("crawl_run_id")) != run_id:
            raise ObservationError(
                f"observation bundle is for crawl run {bundle.get('crawl_run_id')!r}, the audit is for {run_id!r}"
            )
        merged.extend(dict(item) for item in _items(bundle.get("collections")) if isinstance(item, Mapping))
    return {
        **audit,
        "observations": {
            "schema_version": OBSERVATIONS_SCHEMA_VERSION,
            "crawl_run_id": run_id,
            "collections": merged,
        },
    }


def observation_collections(audit: Mapping[str, object], kind: str) -> list[Mapping[str, Any]]:
    observations = audit.get("observations")
    if not isinstance(observations, Mapping):
        return []
    if _text(observations.get("crawl_run_id")) != _text(audit.get("crawl_run_id")):
        return []
    return [
        item
        for item in _items(observations.get("collections"))
        if isinstance(item, Mapping) and item.get("kind") == kind and isinstance(item.get("records"), list)
    ]


def new_bundle(crawl_run_id: str, collections: Iterable[Mapping[str, object]]) -> dict[str, object]:
    bundle: dict[str, object] = {
        "schema_version": OBSERVATIONS_SCHEMA_VERSION,
        "crawl_run_id": crawl_run_id,
        "collections": [dict(item) for item in collections],
    }
    validate_observation_bundle(bundle)
    return bundle


def collection(
    kind: str,
    records: Sequence[Mapping[str, object]],
    *,
    source: str,
    scope: str,
    coverage_state: str,
    collected_at: str | None = None,
) -> dict[str, object]:
    return {
        "kind": kind,
        "source": source,
        "scope": scope,
        "coverage_state": coverage_state,
        "collected_at": collected_at or datetime.now(UTC).isoformat(),
        "records": [dict(record) for record in records],
    }


def collection_from_html_signals(
    records: Sequence[Mapping[str, object]],
    *,
    run_context: Mapping[str, object],
    version: str,
) -> dict[str, object]:
    """Wrap stored-HTML signal records; complete only for a complete run with every parsed page scanned."""

    parsed = run_context.get("parsed_html_count")
    complete = run_context.get("completion_state") == "complete" and isinstance(parsed, int) and len(records) >= parsed
    return collection(
        "html-signals",
        records,
        source=f"crawler-cli technical-audit-observations ({version})",
        scope=f"{len(records)} stored raw-HTML pages of {parsed if parsed is not None else 'unknown'} parsed HTML pages",
        coverage_state="complete" if complete else "partial",
    )


def collection_from_render_comparison(payload: Mapping[str, object], crawl_run_id: str) -> dict[str, object]:
    """Wrap a ``compare-renders --output`` JSON payload as a render-parity collection.

    The comparison is a sample of the run, so it is complete only when it was
    neither capped nor left any page inconclusive.
    """

    inputs = payload.get("input")
    inputs = inputs if isinstance(inputs, Mapping) else {}
    source_run = inputs.get("source_crawl_run")
    source_run_id = _text(source_run.get("run_id")) if isinstance(source_run, Mapping) else ""
    if source_run_id != crawl_run_id:
        raise ObservationError(
            f"render comparison was sampled from crawl run {source_run_id or 'none (explicit URLs)'}, "
            f"not {crawl_run_id}; rerun compare-renders with --crawl-run-id {crawl_run_id}"
        )
    results = [dict(row) for row in _items(payload.get("results")) if isinstance(row, Mapping)]
    capped = bool(inputs.get("input_capped", False))
    candidates = inputs.get("candidate_count")
    complete = (
        not capped
        and isinstance(candidates, int)
        and len(results) >= candidates
        and all(row.get("state") == "complete" for row in results)
    )
    return collection(
        "render-parity",
        results,
        source="crawler-cli compare-renders",
        scope=(
            f"{len(results)} of {candidates if candidates is not None else 'unknown'} render candidates; "
            f"{inputs.get('sampling_basis', 'explicit URL list')}"
        ),
        coverage_state="complete" if complete else "partial",
        collected_at=_text(payload.get("observed_at") or inputs.get("selected_at")) or None,
    )


def collection_from_exposure_inventory(artifact: Mapping[str, object]) -> dict[str, object]:
    """Wrap an ``exposure-inventory`` artifact as a host-probe collection.

    Only the inventory's reachable candidates were requested; every other
    candidate keeps its state and no status, so the answerer counts it as
    untested.  The inventory reads headers only, so meta-robots noindex is
    unknown (``noindex`` is None unless X-Robots-Tag says noindex).
    """

    if artifact.get("schema_version") != "crawler-cli/exposure-inventory/1":
        raise ObservationError("not an exposure-inventory artifact (crawler-cli/exposure-inventory/1)")
    records = []
    for row in _items(artifact.get("candidates")):
        if not isinstance(row, Mapping):
            continue
        http = row.get("http") if isinstance(row.get("http"), Mapping) else {}
        assert isinstance(http, Mapping)
        robots = _text(http.get("x_robots_tag")).casefold()
        records.append(
            {
                "host": _text(row.get("hostname")),
                "discovered_via": "exposure-inventory",
                "state": row.get("state"),
                "status": http.get("status"),
                "content_type": None,
                "auth_required": bool(http.get("auth_demanded")),
                "noindex": True if "noindex" in robots else None,
                "redirect_target": http.get("redirect_target"),
                "title": http.get("title"),
            }
        )
    requested = sum(1 for record in records if record["status"] is not None)
    return collection(
        "host-probe",
        records,
        source="crawler-cli exposure-inventory",
        scope=f"{requested} of {len(records)} declared candidate hosts requested at /",
        coverage_state="complete" if records and requested == len(records) else "partial",
        collected_at=_text(artifact.get("observed_at")) or None,
    )


def _items(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _parse_time(value: object) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""
