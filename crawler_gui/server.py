#!/usr/bin/env python3
"""Local, read-only bridge between ``crawler_gui`` and crawler_cli Postgres.

This is deliberately a development server, not the product control plane. It
binds loopback only, serves the static GUI, and exposes immutable run snapshots
through JSON endpoints. Crawl submission, cancellation, and deletion stay out of
this read-only bridge (ticket 125); local submission is added separately by
ticket 124.

Two database shapes are supported:

* **Snapshot schema** (ticket 095, ``page_run_snapshots`` present): every run is
  listed with its own immutable page set, and snapshots are genuinely
  run-scoped. This is the accurate mode.
* **Legacy schema** (no snapshot table): only the global latest-write-wins
  current-state tables exist, which cannot be attributed to a single run. Rather
  than list every ``crawl_runs`` row claiming the whole database, the bridge
  collapses to a single explicit "current state" entry and labels the view as
  not run-scoped.

The internal link graph (inlinks/outlinks) is read from the current-state
``internal_links`` table on both schemas; it is not part of the immutable
snapshot, so it reflects the most recent crawl. External outlinks come from a
snapshot's ``links_json`` and are only present when the crawl ran with
``same_host_only=False`` — the default crawl drops cross-host links at
extraction time, so they are genuinely absent rather than hidden here.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import asyncpg
from aiohttp import web


GUI_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = GUI_DIR / "sample-data.json"
MAX_PAGE_LIMIT = 10_000
DEFAULT_PAGE_LIMIT = 5_000
LEGACY_RUN_ID = "current-state"


def status_label(code: int | None) -> str:
    return {
        200: "OK", 201: "Created", 204: "No Content", 301: "Moved Permanently",
        302: "Found", 307: "Temporary Redirect", 308: "Permanent Redirect",
        400: "Bad Request", 401: "Unauthorised", 403: "Forbidden", 404: "Not Found",
        410: "Gone", 429: "Too Many Requests", 500: "Server Error", 502: "Bad Gateway",
        503: "Service Unavailable", 504: "Gateway Timeout",
    }.get(code, "Unknown" if code is not None else "Not fetched")


def iso_time(epoch: int | None) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat().replace("+00:00", "Z")


def headers(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def percent(value: int, total: int) -> float:
    return round(100 * value / total, 1) if total else 0.0


def as_list(value: Any) -> list[Any]:
    """Coerce a JSONB column that asyncpg may hand back as list or str."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, list) else []
        except json.JSONDecodeError:
            return []
    return []


def host_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return ""


def is_external(href: str, page_host: str) -> bool:
    """A resolved absolute href on a different host is external.

    Relative or hostless hrefs are treated as internal (same host)."""
    target_host = host_of(href)
    return bool(target_host) and target_host != page_host


def category_hints(page: dict[str, Any]) -> list[str]:
    hints = ["internal"]
    code, content_type = page["statusCode"], page["contentType"]
    if code != 200:
        hints.append("response-codes")
    if content_type == "text/html":
        hints.extend(["page-titles", "meta-description", "h1", "content", "canonicals", "links"])
    else:
        hints.append("url")
    if page["indexability"] != "Indexable":
        hints.append("directives")
    return sorted(set(hints))


def overview_from_counts(counts: dict[str, int]) -> dict[str, list[dict[str, Any]]]:
    """Build the sidebar overview from whole-run aggregate counts (pure).

    Counts come from a single run-scoped SQL aggregate rather than the loaded
    page window, so the sidebar describes the entire run and stays correct as
    the grid pages through it."""
    total = counts.get("total", 0)
    indexed = counts.get("indexable", 0)
    html = counts.get("html", 0)
    codes = {
        "2xx OK": counts.get("c2xx", 0),
        "3xx Redirect": counts.get("c3xx", 0),
        "4xx Client Error": counts.get("c4xx", 0),
        "5xx Server Error": counts.get("c5xx", 0),
    }
    return {
        "summary": [
            {"label": "Total URLs Crawled", "count": total, "pct": 100.0 if total else 0.0},
            {"label": "Indexable", "count": indexed, "pct": percent(indexed, total)},
            {"label": "Non-Indexable", "count": total - indexed, "pct": percent(total - indexed, total)},
            {"label": "HTTPS", "count": counts.get("https", 0), "pct": percent(counts.get("https", 0), total)},
        ],
        "responseCodes": [
            {"label": label, "count": value, "pct": percent(value, total), "tone": "ok" if label.startswith("2") else "warn" if label.startswith("3") else "bad"}
            for label, value in codes.items()
        ],
        "content": [
            {"label": "HTML", "count": html, "pct": percent(html, total)},
            {"label": "Missing Title", "count": counts.get("missing_title", 0), "pct": percent(counts.get("missing_title", 0), total), "tone": "warn"},
            {"label": "Missing Meta Description", "count": counts.get("missing_meta", 0), "pct": percent(counts.get("missing_meta", 0), total), "tone": "warn"},
            {"label": "Missing H1", "count": counts.get("missing_h1", 0), "pct": percent(counts.get("missing_h1", 0), total), "tone": "warn"},
        ],
    }


def structured_data_of(schema_json: Any) -> list[dict[str, Any]]:
    """Map a snapshot ``schema_json`` array into the GUI structured-data shape."""
    out: list[dict[str, Any]] = []
    for item in as_list(schema_json):
        if isinstance(item, dict):
            stype = item.get("@type") or item.get("type") or "Item"
            name = item.get("name") or item.get("headline") or ""
            out.append({"type": str(stype), "name": str(name) if name else ""})
        elif isinstance(item, str):
            out.append({"type": item, "name": ""})
    return out


def page_from_row(row: dict[str, Any], *, has_snapshots: bool) -> dict[str, Any]:
    """Map one DB row to the GUI page shape (pure — no DB access).

    Link-graph fields (``inlinks``/``outlinks`` and their counts) are left empty
    here and populated by :func:`attach_link_graph` from ``internal_links``.
    """
    response_headers = headers(row.get("headers_json"))
    code = int(row.get("final_status_code") or 0)
    h1_tags = row.get("h1_tags") or ""
    address = str(row.get("url"))
    page_host = host_of(address)
    # Normalise "text/html; charset=utf-8" -> "text/html" so the exact-match
    # content-type checks in category_hints/overview work on live data.
    raw_content_type = response_headers.get("content-type") or ("text/html" if row.get("kind") == "html" else row.get("kind") or "unknown")
    content_type = str(raw_content_type).split(";")[0].strip().lower()

    if has_snapshots:
        canonical_values = as_list(row.get("canonical_urls_json"))
        structured = structured_data_of(row.get("schema_json"))
        # External outlinks are only recoverable from the snapshot link list;
        # internal ones come from internal_links via attach_link_graph.
        external_outlinks = [
            {"targetUrl": link.get("href"), "anchorText": link.get("anchor_text") or "", "external": True}
            for link in as_list(row.get("links_json"))
            if isinstance(link, dict) and link.get("href") and is_external(str(link["href"]), page_host)
        ]
    else:
        canonical_url = row.get("canonical_url")
        canonical_values = [canonical_url] if canonical_url else []
        structured = []
        external_outlinks = []

    duration = row.get("total_duration_seconds")
    page = {
        "id": int(row["url_id"]),
        "address": address,
        "path": urlparse(address).path or "/",
        "contentType": content_type,
        "statusCode": code, "status": status_label(code),
        "indexability": "Indexable" if row.get("overall_indexable") else "Non-Indexable",
        "indexabilityStatus": "" if row.get("overall_indexable") else "blocked or non-indexable",
        "title": row.get("title") or "", "titleLength": len(row.get("title") or ""),
        "metaDescription": row.get("meta_description") or "", "metaDescriptionLength": len(row.get("meta_description") or ""),
        "h1": h1_tags, "h1Count": 1 if h1_tags else 0,
        "responseTimeMs": round(float(duration) * 1000) if duration else None,
        "redirectUrl": row.get("redirect_url"), "internalInlinks": 0, "externalInlinks": 0,
        "wordCount": int(row.get("word_count") or 0), "canonical": canonical_values[0] if canonical_values else None,
        "robots": "index, follow" if row.get("overall_indexable") else "non-indexable",
        "headers": response_headers, "structuredData": structured,
        "inlinks": [], "outlinks": external_outlinks,
    }
    page["categoryHints"] = category_hints(page)
    return page


def attach_link_graph(
    pages: list[dict[str, Any]],
    inlinks: dict[int, list[dict[str, Any]]],
    outlinks: dict[int, list[dict[str, Any]]],
) -> None:
    """Fold resolved internal inlinks/outlinks (by url_id) onto the page rows.

    Internal outlinks are prepended to any external outlinks already present.
    External inbound links are not crawlable, so ``externalInlinks`` stays 0.
    """
    for page in pages:
        uid = page["id"]
        page_inlinks = inlinks.get(uid, [])
        page["inlinks"] = page_inlinks
        page["internalInlinks"] = len(page_inlinks)
        page["outlinks"] = outlinks.get(uid, []) + page["outlinks"]


class LiveStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None
        self.has_run_snapshots = False
        self.template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=4)
        async with self.pool.acquire() as conn:
            self.has_run_snapshots = bool(await conn.fetchval("SELECT to_regclass('page_run_snapshots')"))

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def runs(self) -> list[dict[str, Any]]:
        assert self.pool
        if self.has_run_snapshots:
            # The 'legacy' DEFAULT_CRAWL_RUN_ID row is a schema compatibility
            # placeholder, not a user crawl; hide it when it holds no pages.
            # A genuinely empty real run (created/running) still lists.
            query = """
                SELECT r.run_id, r.mode, r.status, r.seed_urls_json, r.created_at, r.updated_at,
                       COUNT(s.url_id)::int AS urls, COUNT(s.html_compressed)::int AS html_stored
                FROM crawl_runs r
                LEFT JOIN page_run_snapshots s ON s.run_id = r.run_id
                GROUP BY r.run_id, r.mode, r.status, r.seed_urls_json, r.created_at, r.updated_at
                HAVING NOT (r.run_id = 'legacy' AND r.status = 'legacy' AND COUNT(s.url_id) = 0)
                ORDER BY r.updated_at DESC, r.run_id DESC
            """
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            return [self._run_entry(row) for row in rows]

        # Legacy schema: the page tables are global current state and cannot be
        # split per run, so collapse to a single explicit current-state entry
        # instead of repeating global counts against every crawl_runs row.
        async with self.pool.acquire() as conn:
            urls = int(await conn.fetchval("SELECT COUNT(*)::int FROM page_metadata") or 0)
            html_stored = int(await conn.fetchval("SELECT COUNT(*)::int FROM pages WHERE html_compressed IS NOT NULL") or 0)
            latest = await conn.fetchrow(
                "SELECT mode, seed_urls_json, created_at, updated_at FROM crawl_runs ORDER BY updated_at DESC LIMIT 1"
            )
        url = self._first_seed(latest["seed_urls_json"]) if latest else ""
        return [{
            "id": LEGACY_RUN_ID, "mode": str(latest["mode"]) if latest else "open", "status": "current state",
            "url": url, "domain": urlparse(url).netloc or "—", "urls": urls, "htmlStored": html_stored,
            "date": ((iso_time(latest["updated_at"]) if latest else "") or "")[:10],
            "createdAt": iso_time(latest["created_at"]) if latest else None,
            "updatedAt": iso_time(latest["updated_at"]) if latest else None,
            "runScoped": False,
        }]

    @staticmethod
    def _first_seed(seed_urls_json: Any) -> str:
        try:
            seeds = json.loads(seed_urls_json)
        except (TypeError, json.JSONDecodeError):
            seeds = []
        return str(seeds[0]) if isinstance(seeds, list) and seeds else ""

    def _run_entry(self, row: Any) -> dict[str, Any]:
        url = self._first_seed(row["seed_urls_json"])
        date = (iso_time(row["updated_at"]) or "")[:10]
        return {
            "id": str(row["run_id"]), "mode": str(row["mode"]), "status": str(row["status"]),
            "url": url, "domain": urlparse(url).netloc or "—", "urls": int(row["urls"]),
            "htmlStored": int(row["html_stored"]), "date": date,
            "createdAt": iso_time(row["created_at"]), "updatedAt": iso_time(row["updated_at"]),
            "runScoped": True,
        }

    async def _link_graph(
        self, conn: asyncpg.Connection, url_ids: list[int]
    ) -> tuple[dict[int, list[dict[str, Any]]], dict[int, list[dict[str, Any]]]]:
        """Resolved inlinks/outlinks for the given url_ids from internal_links.

        Bounded to the loaded page window (``= ANY(url_ids)``) so it stays cheap
        regardless of run size. Current-state (latest crawl), not snapshot."""
        inlinks: dict[int, list[dict[str, Any]]] = defaultdict(list)
        outlinks: dict[int, list[dict[str, Any]]] = defaultdict(list)
        if not url_ids:
            return inlinks, outlinks
        if not await conn.fetchval("SELECT to_regclass('internal_links')"):
            return inlinks, outlinks
        in_rows = await conn.fetch(
            """
            SELECT il.target_url_id AS uid, su.url AS other, at.text AS anchor
            FROM internal_links il
            JOIN urls su ON su.id = il.source_url_id
            LEFT JOIN anchor_texts at ON at.id = il.anchor_text_id
            WHERE il.target_url_id = ANY($1::int[])
            """,
            url_ids,
        )
        for row in in_rows:
            inlinks[int(row["uid"])].append(
                {"sourceUrl": str(row["other"]), "anchorText": row["anchor"] or "", "follow": True}
            )
        out_rows = await conn.fetch(
            """
            SELECT il.source_url_id AS uid, tu.url AS other, at.text AS anchor
            FROM internal_links il
            JOIN urls tu ON tu.id = il.target_url_id
            LEFT JOIN anchor_texts at ON at.id = il.anchor_text_id
            WHERE il.source_url_id = ANY($1::int[])
            """,
            url_ids,
        )
        for row in out_rows:
            outlinks[int(row["uid"])].append(
                {"targetUrl": str(row["other"]), "anchorText": row["anchor"] or "", "external": False}
            )
        return inlinks, outlinks

    async def _run_counts(self, run_id: str) -> dict[str, int]:
        """Whole-run aggregate counts for the overview sidebar.

        Computed in SQL over the entire run so the sidebar is independent of the
        paginated page window."""
        assert self.pool
        if self.has_run_snapshots:
            query = """
                SELECT COUNT(*)::int AS total,
                       COUNT(*) FILTER (WHERE s.overall_indexable)::int AS indexable,
                       COUNT(*) FILTER (WHERE u.url LIKE 'https://%')::int AS https,
                       COUNT(*) FILTER (WHERE s.final_status_code BETWEEN 200 AND 299)::int AS c2xx,
                       COUNT(*) FILTER (WHERE s.final_status_code BETWEEN 300 AND 399)::int AS c3xx,
                       COUNT(*) FILTER (WHERE s.final_status_code BETWEEN 400 AND 499)::int AS c4xx,
                       COUNT(*) FILTER (WHERE s.final_status_code >= 500)::int AS c5xx,
                       COUNT(*) FILTER (WHERE u.kind = 'html')::int AS html,
                       COUNT(*) FILTER (WHERE u.kind = 'html' AND COALESCE(s.title, '') = '')::int AS missing_title,
                       COUNT(*) FILTER (WHERE u.kind = 'html' AND COALESCE(s.meta_description, '') = '')::int AS missing_meta,
                       COUNT(*) FILTER (WHERE u.kind = 'html' AND COALESCE(s.h1_tags, '') = '')::int AS missing_h1
                FROM page_run_snapshots s
                JOIN urls u ON u.id = s.url_id
                WHERE s.run_id = $1
            """
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, run_id)
            return {key: int(value or 0) for key, value in dict(row).items()}
        query = """
            SELECT COUNT(*)::int AS total,
                   COUNT(*) FILTER (WHERE ix.overall_indexable)::int AS indexable,
                   COUNT(*) FILTER (WHERE u.url LIKE 'https://%')::int AS https,
                   COUNT(*) FILTER (WHERE pm.final_status_code BETWEEN 200 AND 299)::int AS c2xx,
                   COUNT(*) FILTER (WHERE pm.final_status_code BETWEEN 300 AND 399)::int AS c3xx,
                   COUNT(*) FILTER (WHERE pm.final_status_code BETWEEN 400 AND 499)::int AS c4xx,
                   COUNT(*) FILTER (WHERE pm.final_status_code >= 500)::int AS c5xx,
                   COUNT(*) FILTER (WHERE u.kind = 'html')::int AS html,
                   COUNT(*) FILTER (WHERE u.kind = 'html' AND COALESCE(c.title, '') = '')::int AS missing_title,
                   COUNT(*) FILTER (WHERE u.kind = 'html' AND COALESCE(md.description, '') = '')::int AS missing_meta,
                   COUNT(*) FILTER (WHERE u.kind = 'html' AND COALESCE(c.h1_tags, '') = '')::int AS missing_h1
            FROM page_metadata pm
            JOIN urls u ON u.id = pm.url_id
            LEFT JOIN content c ON c.url_id = pm.url_id
            LEFT JOIN meta_descriptions md ON md.id = c.meta_description_id
            LEFT JOIN indexability ix ON ix.url_id = pm.url_id
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query)
        return {key: int(value or 0) for key, value in dict(row).items()}

    async def _fetch_page_rows(self, run_id: str, limit: int, offset: int) -> list[Any]:
        assert self.pool
        if self.has_run_snapshots:
            query = """
                SELECT s.url_id, u.url, u.kind, s.final_status_code, s.fetched_at, s.headers_json,
                       s.title, s.meta_description, s.h1_tags, s.word_count, s.overall_indexable,
                       s.total_duration_seconds, s.canonical_urls_json, s.schema_json, s.links_json,
                       final_url.url AS redirect_url
                FROM page_run_snapshots s
                JOIN urls u ON u.id = s.url_id
                LEFT JOIN urls final_url ON final_url.id = s.final_url_id
                WHERE s.run_id = $1
                ORDER BY u.url
                LIMIT $2 OFFSET $3
            """
            async with self.pool.acquire() as conn:
                return await conn.fetch(query, run_id, limit, offset)
        query = """
            SELECT pm.url_id, u.url, u.kind, pm.final_status_code, pm.fetched_at, p.headers_json,
                   c.title, md.description AS meta_description, c.h1_tags, c.word_count, ix.overall_indexable,
                   pm.total_duration_seconds, canonical.url AS canonical_url,
                   final_url.url AS redirect_url
            FROM page_metadata pm
            JOIN urls u ON u.id = pm.url_id
            LEFT JOIN pages p ON p.url_id = pm.url_id
            LEFT JOIN content c ON c.url_id = pm.url_id
            LEFT JOIN meta_descriptions md ON md.id = c.meta_description_id
            LEFT JOIN indexability ix ON ix.url_id = pm.url_id
            LEFT JOIN urls final_url ON final_url.id = pm.final_url_id
            LEFT JOIN LATERAL (
                SELECT cu.url FROM canonical_urls ca
                JOIN urls cu ON cu.id = ca.canonical_url_id
                WHERE ca.url_id = pm.url_id ORDER BY ca.id LIMIT 1
            ) canonical ON TRUE
            ORDER BY u.url
            LIMIT $1 OFFSET $2
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, limit, offset)

    async def snapshot(self, run_id: str | None, limit: int, offset: int = 0) -> dict[str, Any]:
        runs = await self.runs()
        if not runs:
            raise web.HTTPNotFound(text="No crawl runs found in this database.")
        if self.has_run_snapshots:
            selected = next((run for run in runs if run["id"] == run_id), runs[0])
            if run_id and selected["id"] != run_id:
                raise web.HTTPNotFound(text=f"Crawl run not found: {run_id}")
        else:
            # One current-state entry; ignore a stale ?run= from a shared URL.
            selected = runs[0]

        rows = await self._fetch_page_rows(selected["id"], limit, offset)
        counts = await self._run_counts(selected["id"])
        pages = [page_from_row(dict(row), has_snapshots=self.has_run_snapshots) for row in rows]
        assert self.pool
        async with self.pool.acquire() as conn:
            inlinks, outlinks = await self._link_graph(conn, [page["id"] for page in pages])
        attach_link_graph(pages, inlinks, outlinks)

        data = copy.deepcopy(self.template)
        source = "PostgreSQL run snapshot" if self.has_run_snapshots else "PostgreSQL legacy current-state tables"
        data["meta"] = {"uiName": "crawler_gui · live", "source": source, "runId": selected["id"]}
        data["nav"] = [item for item in data["nav"] if item["id"] != "intent-overlap"]
        data["pages"] = pages
        data["history"] = [{**run, "viewing": run["id"] == selected["id"]} for run in runs]
        total = selected["urls"]
        window_end = offset + len(pages)
        status_label_text = "snapshot" if self.has_run_snapshots else "legacy state"
        data["crawl"] = {
            "id": selected["id"], "url": selected["url"], "mode": "Spider" if selected["mode"] == "open" else selected["mode"],
            "status": selected["status"], "statusLabel": f"Live {status_label_text} · {selected['status']}",
            "progress": {"completed": min(window_end, total), "total": total, "pct": percent(min(window_end, total), total), "remaining": max(0, total - window_end)},
            "speed": {"average": 0.0, "current": 0.0}, "startedAt": selected["createdAt"], "finishedAt": selected["updatedAt"],
        }
        # Overview/issues describe the whole run (SQL aggregate), so they stay
        # correct while the grid pages through a large run.
        data["overview"] = overview_from_counts(counts)
        data["issues"] = [
            {"severity": "warn", "label": "Non-indexable", "count": counts.get("total", 0) - counts.get("indexable", 0)},
            {"severity": "warn", "label": "Non-200 response", "count": counts.get("total", 0) - counts.get("c2xx", 0)},
        ]
        data["live"] = {
            "runId": selected["id"], "totalPages": total, "snapshotBacked": self.has_run_snapshots,
            "runScoped": selected.get("runScoped", True),
            "offset": offset, "limit": limit, "loaded": len(pages), "windowEnd": window_end,
            "hasMore": window_end < total, "truncated": window_end < total,
        }
        return data


def _parse_int(value: str, *, minimum: int, maximum: int, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise web.HTTPBadRequest(text=f"{name} must be an integer") from None
    return min(maximum, max(minimum, parsed))


async def snapshot_handler(request: web.Request) -> web.Response:
    store: LiveStore = request.app["store"]
    limit = _parse_int(request.query.get("limit", str(DEFAULT_PAGE_LIMIT)), minimum=1, maximum=MAX_PAGE_LIMIT, name="limit")
    offset = _parse_int(request.query.get("offset", "0"), minimum=0, maximum=2**31, name="offset")
    return web.json_response(await store.snapshot(request.query.get("run"), limit, offset))


async def runs_handler(request: web.Request) -> web.Response:
    store: LiveStore = request.app["store"]
    return web.json_response({"runs": await store.runs()})


async def index_handler(_: web.Request) -> web.FileResponse:
    return web.FileResponse(GUI_DIR / "index.html")


async def on_startup(app: web.Application) -> None:
    await app["store"].connect()


async def on_cleanup(app: web.Application) -> None:
    await app["store"].close()


async def no_cache(_: web.Request, response: web.StreamResponse) -> None:
    response.headers["Cache-Control"] = "no-store"


def build_app(dsn: str) -> web.Application:
    app = web.Application()
    app["store"] = LiveStore(dsn)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.on_response_prepare.append(no_cache)
    app.router.add_get("/api/live/runs", runs_handler)
    app.router.add_get("/api/live/snapshot", snapshot_handler)
    app.router.add_get("/", index_handler)
    app.router.add_static("/", GUI_DIR, show_index=True)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve crawler_gui against a live crawler_cli PostgreSQL database.")
    parser.add_argument("--postgres-dsn", default=os.environ.get("CRAWLER_CLI_POSTGRES_DSN"), help="Postgres DSN (or set CRAWLER_CLI_POSTGRES_DSN)")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if not args.postgres_dsn:
        parser.error("set --postgres-dsn or CRAWLER_CLI_POSTGRES_DSN")
    web.run_app(build_app(args.postgres_dsn), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
