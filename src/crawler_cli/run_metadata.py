from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import CrawlConfig
    from .models import CrawlJobResult

CRAWL_RUN_METADATA_SCHEMA_VERSION = "crawler-cli/run-metadata/1"


def compute_file_sha256(path: Path | str) -> str:
    """Compute the SHA-256 hex digest of a file (ticket 400)."""
    target = Path(path)
    hasher = hashlib.sha256()
    with target.open("rb") as stream:
        while chunk := stream.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def sidecar_path_for(artifact_path: Path | str) -> Path:
    """Return the primary companion metadata sidecar path for an artifact.

    If the artifact is named ``crawl.ndjson`` (or ``crawl.json``), the sidecar is
    named ``crawl.meta.json``.
    """
    path = Path(artifact_path)
    return path.with_suffix(".meta.json")


def resolve_sidecar_path(artifact_path: Path | str) -> Path | None:
    """Find an existing sidecar document for an artifact path, or return None.

    Checks candidates in precedence order:
    1. ``<stem>.meta.json``
    2. ``<stem>.metadata.json``
    3. ``<name>.meta.json``
    4. ``<name>.metadata.json``
    5. ``<stem>.json`` (when artifact has ``.ndjson`` extension)
    """
    path = Path(artifact_path)
    candidates = [
        path.with_suffix(".meta.json"),
        path.with_suffix(".metadata.json"),
        path.with_name(f"{path.name}.meta.json"),
        path.with_name(f"{path.name}.metadata.json"),
    ]
    if path.suffix in (".ndjson", ".jsonl"):
        candidates.append(path.with_suffix(".json"))

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def build_run_metadata(
    job: CrawlJobResult,
    *,
    config: CrawlConfig | None = None,
    artifact_path: Path | str | None = None,
    started_at: datetime | str | None = None,
    ended_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Build a stable JSON run-metadata sidecar document (ticket 400)."""
    # Timestamps
    if isinstance(started_at, datetime):
        started_iso = started_at.astimezone(timezone.utc).isoformat()
        start_dt = started_at
    elif isinstance(started_at, str):
        started_iso = started_at
        try:
            start_dt = datetime.fromisoformat(started_at)
        except Exception:
            start_dt = None
    else:
        start_dt = datetime.now(timezone.utc)
        started_iso = start_dt.isoformat()

    if isinstance(ended_at, datetime):
        ended_iso = ended_at.astimezone(timezone.utc).isoformat()
        end_dt = ended_at
    elif isinstance(ended_at, str):
        ended_iso = ended_at
        try:
            end_dt = datetime.fromisoformat(ended_at)
        except Exception:
            end_dt = None
    else:
        end_dt = datetime.now(timezone.utc)
        ended_iso = end_dt.isoformat()

    duration_seconds: float | None = None
    if start_dt and end_dt:
        duration_seconds = max(0.0, round((end_dt - start_dt).total_seconds(), 3))

    # User agent
    ua = "canonicalbot/0.1"
    if config:
        if job.seed_urls:
            ua = config.user_agent_for(job.seed_urls[0])
        else:
            ua = config.user_agent

    # Completion state & clean flag
    completion_state = job.crawl_run_status or (
        "interrupted"
        if job.interrupted
        else "complete_with_errors"
        if (job.persist_error_count or job.frontier_mark_done_error_count)
        else "complete"
    )
    is_clean = completion_state == "complete"

    # Robots policy & results
    respect_robots = bool(config.respect_robots_txt) if config is not None else True
    honor_delay = bool(config.honor_robots_crawl_delay) if config is not None else True
    robots_policy = "respect" if respect_robots else "ignore"

    # Checksum of artifact
    checksum: str | None = None
    file_bytes: int | None = None
    if artifact_path:
        p = Path(artifact_path)
        if p.is_file():
            checksum = compute_file_sha256(p)
            file_bytes = p.stat().st_size

    # Error breakdown
    http_errors = sum(1 for r in job.results if r.status >= 400)
    fetch_errors = sum(1 for r in job.results if r.status == 0)
    total_errors = job.persist_error_count + job.frontier_mark_done_error_count + http_errors + fetch_errors

    metadata: dict[str, Any] = {
        "schema_version": CRAWL_RUN_METADATA_SCHEMA_VERSION,
        "run_id": job.run_id,
        "seed_urls": list(job.seed_urls),
        "crawl_mode": job.mode,
        "mode": job.mode,
        "user_agent": ua,
        "robots": {
            "policy": robots_policy,
            "respect_robots_txt": respect_robots,
            "honor_crawl_delay": honor_delay,
            "blocked_count": job.blocked_count,
        },
        "robots_policy": robots_policy,
        "limits": {
            "max_pages": (
                job.max_urls
                if job.max_urls is not None
                else (getattr(config, "default_open_crawl_limit", None) if config else None)
            ),
            "max_requests": getattr(config, "max_requests", None) if config else None,
            "max_bytes": getattr(config, "max_bytes", None) if config else None,
            "max_depth": getattr(config, "max_depth", None) if config else None,
            "max_duration_seconds": getattr(config, "max_duration_seconds", None) if config else None,
            "concurrency": getattr(config, "max_concurrency", None) if config else None,
            "per_host_concurrency": getattr(config, "per_host_concurrency", None) if config else None,
            "rate_limit_per_second": getattr(config, "rate_limit_per_second", None) if config else None,
            "rate_limit": getattr(config, "rate_limit_per_second", None) if config else None,
            "max_response_bytes": getattr(config, "max_response_bytes", None) if config else None,
        },
        "started_at": started_iso,
        "ended_at": ended_iso,
        "duration_seconds": duration_seconds,
        "completion_state": completion_state,
        "crawl_run_status": completion_state,
        "clean": is_clean,
        "is_clean": is_clean,
        "result_count": len(job.results),
        "crawled_count": job.crawled_count,
        "error_counts": {
            "persist_error_count": job.persist_error_count,
            "frontier_mark_done_error_count": job.frontier_mark_done_error_count,
            "challenge_blocked_count": job.challenge_blocked_count,
            "robots_blocked_count": job.blocked_count,
            "http_error_count": http_errors,
            "fetch_error_count": fetch_errors,
            "total_errors": total_errors,
        },
        "persist_error_count": job.persist_error_count,
        "frontier_mark_done_error_count": job.frontier_mark_done_error_count,
        "persist_failed_urls": list(job.persist_failed_urls),
        "frontier_mark_done_failed_urls": list(job.frontier_mark_done_failed_urls),
        "sha256": checksum,
        "artifact_sha256": checksum,
        "artifact_path": str(artifact_path) if artifact_path else None,
        "artifact_filename": Path(artifact_path).name if artifact_path else None,
        "artifact_bytes": file_bytes,
        "durability": job.durability,
        "retry_attempts": job.retry_attempts,
        "interrupted": job.interrupted,
        "refresh_skipped_count": job.refresh_skipped_count,
        "authorization_scope": job.authorization_scope,
    }
    return metadata


def write_run_metadata(
    metadata: dict[str, Any],
    artifact_path: Path | str,
    sidecar_path: Path | str | None = None,
) -> Path:
    """Write run-metadata sidecar JSON to disk (ticket 400)."""
    target = Path(sidecar_path) if sidecar_path else sidecar_path_for(artifact_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Also write .metadata.json sibling if .meta.json was the target, for complete caller compatibility
    if target.name.endswith(".meta.json"):
        alt = target.with_name(target.name[:-10] + ".metadata.json")
        try:
            alt.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError:
            pass

    return target


def read_run_metadata(path_or_artifact: Path | str) -> dict[str, Any]:
    """Read run metadata from either a sidecar file or its associated artifact."""
    p = Path(path_or_artifact)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")

    if p.name.endswith((".meta.json", ".metadata.json")):
        sidecar_file = p
    else:
        resolved = resolve_sidecar_path(p)
        if resolved is None or not resolved.is_file():
            raise FileNotFoundError(f"No run metadata sidecar found for artifact: {p}")
        sidecar_file = resolved

    data = json.loads(sidecar_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid run metadata document in {sidecar_file}")
    return data
