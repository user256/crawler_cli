"""PostgreSQL storage and retention for security findings (ticket 153).

The tables here follow the run-scoped precedent set by tickets 041 and 042 for
crawl data: every row carries the ``run_id`` it was produced by, every
retention operation names an exact run id, and every retention operation
supports a dry run that reports counts without changing anything. Nothing in
this module has a "delete everything older than" convenience path, because a
mistake in that shape is unrecoverable and this project has already lost data
to one.

Three tables exist, and the split between them is the point:

``security_findings``
    Redacted, normalised findings. Safe to retain after raw evidence has been
    removed, and safe to project into the GUI and the API.

``security_evidence_raw``
    Raw, unredacted evidence, written only when the operator made the separate
    explicit database-retention choice. This is the table that compaction
    exists to empty.

``security_run_retention``
    Per-run retention metadata: what a run was allowed to keep, and what has
    since been purged.

The helpers take an asyncpg-style connection rather than a store, so they can
be unit-tested against a recording double and reused by any store object.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

SECURITY_TABLES: tuple[str, ...] = (
    "security_evidence_raw",
    "security_findings",
    "security_run_retention",
)
"""Security tables owned by crawler_cli, ordered so children precede parents."""


SECURITY_SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS security_findings (
        id BIGSERIAL PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES crawl_runs(run_id) ON DELETE CASCADE,
        schema_version TEXT NOT NULL,
        rule_id TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        severity TEXT NOT NULL,
        confidence TEXT NOT NULL,
        status TEXT NOT NULL,
        source TEXT NOT NULL,
        detector TEXT NOT NULL,
        detector_version TEXT NOT NULL,
        redacted_url TEXT NOT NULL,
        url_digest TEXT NOT NULL,
        host TEXT NOT NULL DEFAULT '',
        observed_at TIMESTAMPTZ NOT NULL,
        evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        evidence_truncated BOOLEAN NOT NULL DEFAULT FALSE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_security_findings_run_rule
    ON security_findings(run_id, rule_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_security_findings_run_severity
    ON security_findings(run_id, severity)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_security_findings_url_digest
    ON security_findings(url_digest)
    """,
    # Raw evidence is a separate table, not a column on security_findings, so
    # that purging it cannot damage a finding and so that a deployment can
    # restrict access to it independently.
    """
    CREATE TABLE IF NOT EXISTS security_evidence_raw (
        id BIGSERIAL PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES crawl_runs(run_id) ON DELETE CASCADE,
        finding_id BIGINT REFERENCES security_findings(id) ON DELETE CASCADE,
        rule_id TEXT NOT NULL,
        raw_url TEXT NOT NULL,
        raw_evidence TEXT,
        stored_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_security_evidence_raw_run
    ON security_evidence_raw(run_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS security_run_retention (
        run_id TEXT PRIMARY KEY REFERENCES crawl_runs(run_id) ON DELETE CASCADE,
        retain_raw_html BOOLEAN NOT NULL DEFAULT FALSE,
        retain_response_headers BOOLEAN NOT NULL DEFAULT FALSE,
        retain_raw_security_evidence BOOLEAN NOT NULL DEFAULT FALSE,
        raw_evidence_purged_at TIMESTAMPTZ,
        note TEXT NOT NULL DEFAULT ''
    )
    """,
]
"""DDL appended to the main crawler schema, guarded by ``IF NOT EXISTS``."""


class SupportsQuery(Protocol):
    """The subset of the asyncpg connection API these helpers rely on."""

    async def execute(self, query: str, *args: Any) -> Any: ...

    async def fetchval(self, query: str, *args: Any) -> Any: ...


async def record_run_retention(
    conn: SupportsQuery,
    *,
    run_id: str,
    retain_raw_html: bool,
    retain_response_headers: bool,
    retain_raw_security_evidence: bool,
    note: str = "",
) -> None:
    """Record what one run is permitted to retain.

    Written once at the start of a run so that a later compaction, audit or
    incident review can answer "was this run ever allowed to keep raw
    evidence?" without inferring it from the presence of rows.
    """
    await conn.execute(
        """
        INSERT INTO security_run_retention (
            run_id, retain_raw_html, retain_response_headers, retain_raw_security_evidence, note
        ) VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (run_id) DO UPDATE SET
            retain_raw_html = EXCLUDED.retain_raw_html,
            retain_response_headers = EXCLUDED.retain_response_headers,
            retain_raw_security_evidence = EXCLUDED.retain_raw_security_evidence,
            note = EXCLUDED.note
        """,
        run_id,
        retain_raw_html,
        retain_response_headers,
        retain_raw_security_evidence,
        note,
    )


async def store_finding_payload(
    conn: SupportsQuery,
    payload: Mapping[str, Any],
    *,
    run_id: str,
) -> None:
    """Persist one already-serialized finding payload.

    The payload must be one produced by
    :meth:`crawler_cli.security_evidence.EvidenceSerializer.finding_payload`,
    which is the only supported way to obtain a redacted finding. This
    function deliberately has no code path that accepts a raw fact, so no
    caller can persist unredacted evidence by mistake.
    """
    await conn.execute(
        """
        INSERT INTO security_findings (
            run_id, schema_version, rule_id, title, category, description,
            severity, confidence, status, source, detector, detector_version,
            redacted_url, url_digest, host, observed_at, evidence_json, evidence_truncated
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16::timestamptz, $17::jsonb, $18
        )
        """,
        run_id,
        payload["schema_version"],
        payload["rule_id"],
        payload.get("title", ""),
        payload.get("category", ""),
        payload.get("description", ""),
        payload["severity"],
        payload["confidence"],
        payload["status"],
        payload["source"],
        payload["detector"],
        payload["detector_version"],
        payload["url"],
        payload["url_digest"],
        payload.get("host", ""),
        payload["observed_at"],
        json.dumps(payload.get("evidence", {}), sort_keys=True),
        bool(payload.get("evidence_truncated", False)),
    )


async def store_finding_payloads(
    conn: SupportsQuery,
    payloads: Iterable[Mapping[str, Any]],
    *,
    run_id: str,
) -> int:
    """Persist several finding payloads, returning how many were written."""
    written = 0
    for payload in payloads:
        await store_finding_payload(conn, payload, run_id=run_id)
        written += 1
    return written


async def security_run_stats(conn: SupportsQuery, *, run_id: str) -> dict[str, int]:
    """Count the security rows belonging to exactly one run."""
    findings = await conn.fetchval("SELECT COUNT(*) FROM security_findings WHERE run_id = $1", run_id)
    raw_evidence = await conn.fetchval("SELECT COUNT(*) FROM security_evidence_raw WHERE run_id = $1", run_id)
    retention = await conn.fetchval("SELECT COUNT(*) FROM security_run_retention WHERE run_id = $1", run_id)
    return {
        "security_findings": int(findings or 0),
        "security_evidence_raw": int(raw_evidence or 0),
        "security_run_retention": int(retention or 0),
    }


async def purge_run_security_evidence(
    conn: SupportsQuery,
    *,
    run_id: str,
    drop_findings: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    """Purge one run's raw security evidence, and optionally its findings.

    Raw evidence and redacted findings are purged separately on purpose: the
    normal retention step removes the raw evidence and keeps the findings, so
    a report stays reproducible after the sensitive material is gone. Passing
    ``drop_findings`` is the stronger action and is never implied.

    Every statement is scoped by exact run id. A dry run reports the counts it
    would have removed and changes nothing.
    """
    stats = await security_run_stats(conn, run_id=run_id)
    result = {
        "run_id_scoped": 1,
        "raw_evidence_rows": stats["security_evidence_raw"],
        "finding_rows": stats["security_findings"] if drop_findings else 0,
        "dry_run": int(dry_run),
    }
    if dry_run:
        return result
    await conn.execute("DELETE FROM security_evidence_raw WHERE run_id = $1", run_id)
    if drop_findings:
        await conn.execute("DELETE FROM security_findings WHERE run_id = $1", run_id)
    await conn.execute(
        "UPDATE security_run_retention SET raw_evidence_purged_at = now() WHERE run_id = $1",
        run_id,
    )
    return result


async def delete_run_security_data(
    conn: SupportsQuery,
    *,
    run_id: str,
    dry_run: bool = False,
) -> dict[str, int]:
    """Delete every security row for exactly one run.

    Used by the delete path rather than the compaction path: it removes the
    findings, the raw evidence and the retention metadata together, leaving no
    trace of the run in the security tables.
    """
    stats = await security_run_stats(conn, run_id=run_id)
    if dry_run:
        return {**stats, "dry_run": 1}
    for table in SECURITY_TABLES:
        await conn.execute(f"DELETE FROM {table} WHERE run_id = $1", run_id)
    return {**stats, "dry_run": 0}


def security_table_names() -> Sequence[str]:
    """Return the security table names, for row-count summaries."""
    return SECURITY_TABLES
