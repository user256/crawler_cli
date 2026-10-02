#!/usr/bin/env python3
"""Local bridge between ``crawler_gui`` and a crawler_cli Postgres database.

This is deliberately a development server, not the product control plane. It
binds loopback only, serves the static GUI, and exposes immutable run snapshots
through JSON endpoints.

**Boundary (ticket 124).** The bridge was read-only by design, with crawl
submission reserved for ``crawler_api``. Ticket 124 consciously relaxes that for
local-first use: ``POST /api/live/crawls`` starts a real crawl by spawning the
``crawler_cli`` CLI as a subprocess against this bridge's DSN. Cancellation and
**deletion stay out** — ``delete-crawl`` remains a CLI/API action. Submission is
in-memory and single-job: it is a local convenience, not job management.

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
snapshot, so it reflects the most recent crawl. External outlinks initially
come from a snapshot's ``links_json``. The saved HTML evidence endpoint also
recovers links, social metadata, and scripts on demand without visiting the
original website.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
import uuid
from collections import OrderedDict, defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import asyncpg
from aiohttp import web
from lxml import html as lxml_html

from crawler_cli.compression import decompress_html
if __name__ == "__main__" and not __package__:
    from resume import resume_configuration
else:
    from crawler_gui.resume import resume_configuration


GUI_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = GUI_DIR / "sample-data.json"
MAX_PAGE_LIMIT = 10_000
DEFAULT_PAGE_LIMIT = 5_000
LEGACY_RUN_ID = "current-state"
LOG_TAIL_LINES = 40
CHROME_LOCK_NAMES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


def _chrome_user_data_candidates(
    *, home: Path | None = None, platform_name: str | None = None, environ: Mapping[str, str] | None = None
) -> list[tuple[str, Path]]:
    """Return standard Chrome/Chromium user-data directories for an OS.

    This is deliberately discovery-only: it reads Chrome's ``Local State``
    metadata, never profile cookies or browser databases (ticket 128).
    """
    home = home if home is not None else Path.home()
    platform_name = platform_name if platform_name is not None else sys.platform
    environ = environ if environ is not None else os.environ
    candidates: list[tuple[str, Path]] = []

    def add(browser: str, path: Path) -> None:
        path = path.expanduser()
        if (browser, path) not in candidates:
            candidates.append((browser, path))

    if platform_name.startswith("win"):
        local_appdata = Path(environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
        add("chrome", local_appdata / "Google" / "Chrome" / "User Data")
        add("chromium", local_appdata / "Chromium" / "User Data")
    elif platform_name == "darwin":
        app_support = home / "Library" / "Application Support"
        add("chrome", app_support / "Google" / "Chrome")
        add("chromium", app_support / "Chromium")
    else:
        config_home = Path(environ.get("XDG_CONFIG_HOME", str(home / ".config")))
        add("chrome", config_home / "google-chrome")
        add("chromium", config_home / "chromium")

    return candidates


def _path_has_lock(path: Path) -> bool:
    """Detect Chrome's lock files, including broken SingletonLock symlinks."""
    return any((path / name).exists() or (path / name).is_symlink() for name in CHROME_LOCK_NAMES)


def _safe_profile_directory(value: str) -> bool:
    """Only accept a single Chrome profile-directory component."""
    return bool(value) and value not in {".", ".."} and "/" not in value and "\\" not in value


def _is_default_chrome_user_data_dir(path: Path) -> bool:
    """Whether *path* is one of Chrome's normal, user-owned data roots."""
    return path.name in {"User Data", "google-chrome", "chromium", "Chrome", "Chromium"}


def discover_chrome_profiles(
    *, home: Path | None = None, platform_name: str | None = None, environ: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    """Discover named Chrome profiles without reading private profile data.

    The returned paths are intended for the loopback GUI only. ``Local State``
    contains profile labels and the last-used directory; cookies and browsing
    history remain untouched. Missing or malformed browser metadata is skipped.
    """
    profiles: list[dict[str, Any]] = []
    for browser, user_data_dir in _chrome_user_data_candidates(home=home, platform_name=platform_name, environ=environ):
        state_path = user_data_dir / "Local State"
        if not state_path.is_file():
            continue
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        profile_root = state.get("profile") if isinstance(state, dict) else None
        info_cache = profile_root.get("info_cache") if isinstance(profile_root, dict) else None
        if not isinstance(info_cache, dict):
            continue
        last_used = profile_root.get("last_used") if isinstance(profile_root, dict) else None
        default_root = _is_default_chrome_user_data_dir(user_data_dir)
        locked = _path_has_lock(user_data_dir)
        for directory, info in sorted(info_cache.items()):
            directory = str(directory)
            if not _safe_profile_directory(directory) or not isinstance(info, dict):
                continue
            profile_path = user_data_dir / directory
            warning = None
            if locked:
                warning = "Chrome appears to be using this profile; close Chrome before starting the crawl."
            elif default_root:
                warning = (
                    "Chrome 136+ may block automation from the default user-data directory; "
                    "a dedicated directory is recommended."
                )
            profiles.append(
                {
                    "id": f"{browser}:{user_data_dir}:{directory}",
                    "browser": browser,
                    "name": str(info.get("name") or info.get("gaia_name") or directory),
                    "email": str(info.get("user_name") or ""),
                    "userDataDir": str(user_data_dir),
                    "profileDirectory": directory,
                    "lastUsed": directory == last_used,
                    "profileExists": profile_path.is_dir(),
                    "locked": locked,
                    "requiresDedicatedUserDataDir": default_root,
                    "warning": warning,
                }
            )
    return sorted(profiles, key=lambda item: (not item["lastUsed"], item["name"].lower()))


def chrome_profile_preflight(user_data_dir: str, profile_directory: str) -> dict[str, Any]:
    """Validate a selected profile before spawning Playwright.

    Lock detection is fail-closed because launching against a live personal
    profile can corrupt the profile or fail unpredictably. The default-data-dir
    warning is advisory: dedicated profile guidance is returned to the UI while
    preserving the engine's existing persistent-profile capability.
    """
    if not user_data_dir:
        raise ValueError("a Chrome user-data directory is required")
    if not _safe_profile_directory(profile_directory):
        raise ValueError("profile directory must be one Chrome profile name, such as 'Default' or 'Profile 1'")
    root = Path(user_data_dir).expanduser()
    profile = root / profile_directory
    if not root.is_dir():
        raise ValueError(f"Chrome user-data directory does not exist: {root}")
    if not profile.is_dir():
        raise ValueError(f"Chrome profile does not exist: {profile_directory}")
    locked = _path_has_lock(root)
    default_root = _is_default_chrome_user_data_dir(root)
    return {
        "locked": locked,
        "profileExists": True,
        "requiresDedicatedUserDataDir": default_root,
        "warning": (
            "Chrome 136+ may block automation from the default user-data directory; "
            "a dedicated directory is recommended."
            if default_root
            else None
        ),
    }


def status_label(code: int | None) -> str:
    return {
        200: "OK",
        201: "Created",
        204: "No Content",
        301: "Moved Permanently",
        302: "Found",
        307: "Temporary Redirect",
        308: "Permanent Redirect",
        400: "Bad Request",
        401: "Unauthorised",
        403: "Forbidden",
        404: "Not Found",
        410: "Gone",
        429: "Too Many Requests",
        500: "Server Error",
        502: "Bad Gateway",
        503: "Service Unavailable",
        504: "Gateway Timeout",
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
    hints = ["internal", "url", "response-codes"]
    code, content_type = page["statusCode"], page["contentType"]
    if code != 200:
        hints.append("response-codes")
    if content_type == "text/html":
        hints.extend(["page-titles", "meta-description", "h1", "content", "canonicals", "links"])
    else:
        hints.append("url")
    if page["indexability"] != "Indexable":
        hints.append("directives")
    for key, category in (("structuredData", "structured-data"), ("h2", "h2"),
                          ("images", "images"), ("hreflang", "hreflang"),
                          ("social", "social"), ("scripts", "javascript")):
        if page.get(key):
            hints.append(category)
    return sorted(set(hints))


def live_category_tabs(template_tabs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert live URL-source tabs without changing the static prototype.

    The crawler records whether a URL came from a link, sitemap, archive.org,
    or seed.  In live mode those are useful first-class grid views, unlike the
    static fixture where that provenance does not exist.
    """
    source_tabs = [
        {"id": "internal", "label": "Internal URLs"},
        {"id": "archive-org", "label": "Archive.org URLs"},
        {"id": "backlinks", "label": "External backlinks"},
        {"id": "custom-checks", "label": "Custom checks"},
        {"id": "host-protocol-checks", "label": "Host & protocol"},
        {"id": "url-variant-checks", "label": "URL variants"},
        {"id": "fictional-url-checks", "label": "Fictional URLs"},
        {"id": "external", "label": "External outlinks"},
        {"id": "security", "label": "Insecure HTTP URLs"},
    ]
    remaining = [tab for tab in template_tabs if tab["id"] not in {"internal", "external", "security"}]
    return source_tabs + remaining + [{"id": "social", "label": "Social Metadata"}]


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
            {
                "label": label,
                "count": value,
                "pct": percent(value, total),
                "tone": "ok" if label.startswith("2") else "warn" if label.startswith("3") else "bad",
            }
            for label, value in codes.items()
        ],
        "content": [
            {"label": "HTML", "count": html, "pct": percent(html, total)},
            {
                "label": "Missing Title",
                "count": counts.get("missing_title", 0),
                "pct": percent(counts.get("missing_title", 0), total),
                "tone": "warn",
            },
            {
                "label": "Missing Meta Description",
                "count": counts.get("missing_meta", 0),
                "pct": percent(counts.get("missing_meta", 0), total),
                "tone": "warn",
            },
            {
                "label": "Missing H1",
                "count": counts.get("missing_h1", 0),
                "pct": percent(counts.get("missing_h1", 0), total),
                "tone": "warn",
            },
        ],
    }


def structured_data_of(schema_json: Any) -> list[dict[str, Any]]:
    """Map a snapshot ``schema_json`` array into the GUI structured-data shape."""
    out: list[dict[str, Any]] = []
    for item in as_list(schema_json):
        if isinstance(item, dict):
            stype = item.get("@type") or item.get("type") or "Item"
            parsed = headers(item.get("parsed_data"))
            name = item.get("name") or item.get("headline") or parsed.get("name") or parsed.get("headline") or ""
            entry: dict[str, Any] = {"type": str(stype), "name": str(name) if name else ""}
            for key in ("format", "is_valid", "validation_errors"):
                if key in item:
                    entry[key] = item[key]
            out.append(entry)
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
    raw_content_type = response_headers.get("content-type") or (
        "text/html" if row.get("kind") == "html" else row.get("kind") or "unknown"
    )
    content_type = str(raw_content_type).split(";")[0].strip().lower()

    if has_snapshots:
        canonical_values = as_list(row.get("canonical_urls_json"))
        structured = structured_data_of(row.get("schema_json"))
        # Snapshot link inventory includes external links without widening the
        # crawl frontier. Internal links come from internal_links below.
        external_outlinks = [
            {
                "targetUrl": link.get("href"),
                "anchorText": link.get("anchor_text") or "",
                "external": True,
                "follow": bool(link.get("follow", True)),
            }
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
        "statusCode": code,
        "status": status_label(code),
        "indexability": "Indexable" if row.get("overall_indexable") else "Non-Indexable",
        "indexabilityStatus": "" if row.get("overall_indexable") else "blocked or non-indexable",
        "title": row.get("title") or "",
        "titleLength": len(row.get("title") or ""),
        "metaDescription": row.get("meta_description") or "",
        "metaDescriptionLength": len(row.get("meta_description") or ""),
        "h1": h1_tags,
        "h1Count": len(h1_tags.splitlines()) if h1_tags else 0,
        "h2": row.get("h2_tags") or "",
        "h2Count": len((row.get("h2_tags") or "").splitlines()),
        "images": as_list(row.get("images_json")),
        "hreflang": as_list(row.get("hreflang_json")),
        "social": [],
        "scripts": [],
        "hasStoredHtml": bool(row.get("has_stored_html")),
        "responseTimeMs": round(float(duration) * 1000) if duration else None,
        "redirectUrl": row.get("redirect_url"),
        "internalInlinks": 0,
        "externalInlinks": 0,
        "wordCount": int(row.get("word_count") or 0),
        "canonical": canonical_values[0] if canonical_values else None,
        "robots": ", ".join(str(v) for v in as_list(row.get("robots_json"))) or "Not recorded",
        "headers": response_headers,
        "structuredData": structured,
        "inlinks": [],
        "outlinks": external_outlinks,
        # Populated from url_sources by the live store.  The static fixture has
        # no equivalent provenance, so this deliberately starts empty.
        "sources": [],
        "sourceEvidence": [],
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


def attach_url_sources(pages: list[dict[str, Any]], sources: dict[int, list[dict[str, str]]]) -> None:
    """Attach run-scoped source evidence to the matching page rows."""
    for page in pages:
        evidence = sources.get(page["id"], [])
        page["sourceEvidence"] = evidence
        page["sources"] = list(dict.fromkeys(row["source"] for row in evidence))
        if any(source in page["sources"] for source in ("sitemap", "robots_sitemap")):
            page["categoryHints"].append("sitemaps")
        # Backlink imports are inbound-link evidence, unlike the crawler's
        # native internal-link graph.
        page["externalInlinks"] = len(
            {row.get("detail") or row["source"] for row in evidence if row["source"] == "backlink"}
        )


@dataclass
class CrawlSpec:
    """A validated New Crawl request from the GUI."""

    target: str
    mode: str = "Spider"
    run_id: str = ""
    name: str = ""
    max_pages: int | None = None
    concurrency: int | None = None
    backend: str = ""
    user_agent: str = ""
    respect_robots: bool = True
    csv_column: str = "url"
    browser_channel: str = ""
    user_data_dir: str = ""
    profile_directory: str = ""
    headed: bool = False


def new_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"gui-{stamp}-{uuid.uuid4().hex[:8]}"


def parse_crawl_spec(payload: dict[str, Any]) -> CrawlSpec:
    """Validate a New Crawl payload into a CrawlSpec (pure).

    Raises ``ValueError`` with an operator-readable message; the caller maps
    that to a 400 rather than a traceback."""
    target = str(payload.get("url") or "").strip()
    if not target:
        raise ValueError("a crawl target is required")
    mode = str(payload.get("mode") or "Spider").strip() or "Spider"
    if mode not in {"Spider", "List"}:
        raise ValueError(f"unknown crawl mode: {mode}")
    if mode == "Spider":
        scheme = urlparse(target).scheme.lower()
        if scheme not in {"http", "https"}:
            raise ValueError("seed URL must be an http(s) URL")
    else:
        # The CLI's list mode reads a local CSV file; a hosted list URL is not
        # something crawler_cli ingests today, so say so instead of guessing.
        if not Path(target).expanduser().is_file():
            raise ValueError("list mode needs a path to a local CSV file of URLs (hosted URL lists are not supported)")

    def _positive_int(key: str) -> int | None:
        raw = payload.get(key)
        if raw in (None, ""):
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a whole number") from None
        if value < 0:
            raise ValueError(f"{key} must not be negative")
        return value

    backend = str(payload.get("backend") or "").strip()
    if backend and backend not in {"aiohttp", "curl_cffi", "playwright", "obscura"}:
        raise ValueError(f"unknown backend: {backend}")

    browser_channel = str(payload.get("browserChannel") or "").strip()
    user_data_dir = str(payload.get("userDataDir") or "").strip()
    profile_directory = str(payload.get("profileDirectory") or "").strip()
    headed = bool(payload.get("headed", False))
    has_profile = bool(user_data_dir or profile_directory)
    if has_profile or browser_channel or headed:
        if backend == "obscura":
            raise ValueError("Chrome profile launch flags cannot be combined with the Obscura backend")
        if backend not in {"", "playwright"}:
            raise ValueError("Chrome profiles require the Playwright backend")
        backend = "playwright"
    if has_profile:
        try:
            preflight = chrome_profile_preflight(user_data_dir, profile_directory)
        except ValueError as exc:
            raise ValueError(str(exc)) from None
        if preflight["locked"]:
            raise ValueError("Chrome appears to be using this profile; close Chrome first")

    return CrawlSpec(
        target=target,
        mode=mode,
        run_id=str(payload.get("runId") or "").strip() or new_run_id(),
        name=str(payload.get("name") or "").strip(),
        max_pages=_positive_int("maxPages"),
        concurrency=_positive_int("concurrency"),
        backend=backend,
        user_agent=str(payload.get("userAgent") or "").strip(),
        respect_robots=bool(payload.get("respectRobots", True)),
        csv_column=str(payload.get("csvColumn") or "url").strip() or "url",
        browser_channel=browser_channel,
        user_data_dir=user_data_dir,
        profile_directory=profile_directory,
        headed=headed,
    )


def build_crawl_argv(spec: CrawlSpec, dsn: str) -> list[str]:
    """Map a CrawlSpec onto a ``crawler_cli crawl`` argv (pure).

    Only fields with a real CLI flag are mapped — the GUI's ``delay`` has no
    crawl-side equivalent and is deliberately not invented here. Built as an
    argv list and spawned without a shell, so values cannot inject."""
    argv = [sys.executable, "-m", "crawler_cli", "crawl"]
    if spec.mode == "List":
        argv += ["--csv-file", spec.target, "--csv-column", spec.csv_column]
    else:
        argv.append(spec.target)
    argv += ["--postgres-dsn", dsn, "--crawl-run-id", spec.run_id]
    if spec.max_pages is not None:
        argv += ["--max-pages", str(spec.max_pages)]
    if spec.concurrency:
        argv += ["--concurrency", str(spec.concurrency)]
    if not spec.respect_robots:
        argv.append("--ignore-robots")
    if spec.user_agent:
        argv += ["--custom-ua", spec.user_agent]
    if spec.backend == "obscura":
        argv.append("--obscura")
    elif spec.backend == "playwright":
        argv.append("--js")
    elif spec.backend:
        argv += ["--http-backend", spec.backend]
    if spec.browser_channel:
        argv += ["--playwright-channel", spec.browser_channel]
    if spec.user_data_dir:
        argv += ["--playwright-user-data-dir", spec.user_data_dir]
    if spec.profile_directory:
        argv += ["--playwright-profile-directory", spec.profile_directory]
    if spec.headed:
        argv.append("--headed")
    return argv


@dataclass
class CrawlJob:
    id: str
    run_id: str
    target: str
    mode: str
    state: str = "running"  # running | succeeded | failed
    started_at: str = ""
    finished_at: str | None = None
    exit_code: int | None = None
    log: deque[str] = field(default_factory=lambda: deque(maxlen=LOG_TAIL_LINES))

    def as_json(self) -> dict[str, Any]:
        return {
            "jobId": self.id,
            "runId": self.run_id,
            "target": self.target,
            "mode": self.mode,
            "state": self.state,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "exitCode": self.exit_code,
            "log": list(self.log),
        }


class CrawlLauncher:
    """Runs one crawl at a time by spawning the crawler_cli CLI (ticket 124).

    Deliberately minimal: in-memory job records, single active job, no cancel
    and no delete. Real job management belongs to ``crawler_api``.
    """

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.jobs: dict[str, CrawlJob] = {}
        self._active_id: str | None = None

    def active_job(self) -> CrawlJob | None:
        job = self.jobs.get(self._active_id or "")
        return job if job and job.state == "running" else None

    async def start(self, spec: CrawlSpec) -> CrawlJob:
        running = self.active_job()
        if running is not None:
            raise RuntimeError(running.id)
        job = CrawlJob(
            id=uuid.uuid4().hex[:12],
            run_id=spec.run_id,
            target=spec.target,
            mode=spec.mode,
            started_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
        argv = build_crawl_argv(spec, self.dsn)
        self.jobs[job.id] = job
        self._active_id = job.id
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(GUI_DIR.parent),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except Exception:
            job.state = "failed"
            raise
        asyncio.create_task(self._watch(job, proc))
        return job

    async def _watch(self, job: CrawlJob, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout
        async for raw in proc.stdout:
            job.log.append(raw.decode("utf-8", "replace").rstrip())
        job.exit_code = await proc.wait()
        job.state = "succeeded" if job.exit_code == 0 else "failed"
        job.finished_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    async def resume(self, payload: dict[str, Any], target: str) -> CrawlJob:
        if self.active_job():
            raise RuntimeError("Another GUI crawl is running")
        job = CrawlJob(id=uuid.uuid4().hex[:12], run_id=payload["runId"], target=target,
                       mode="Resume", started_at=datetime.now(UTC).isoformat())
        # Reserve the slot before the subprocess await to prevent duplicate starts.
        self.jobs[job.id] = job
        self._active_id = job.id
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "crawler_gui.resume", cwd=str(GUI_DIR.parent),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            proc.stdin.write(json.dumps({**payload, "dsn": self.dsn}).encode())
            await proc.stdin.drain()
            proc.stdin.close()
        except Exception:
            job.state = "failed"
            raise
        asyncio.create_task(self._watch(job, proc))
        return job


def saved_html_evidence(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"id": int(row["url_id"]), "social": [], "scripts": [], "savedOutlinks": [], "evidenceLoaded": True}
    if not row.get("html_compressed"):
        result["evidenceNote"] = "No saved HTML for this URL."
        return result
    try:
        document = lxml_html.fromstring(decompress_html(row["html_compressed"]))
        base = row["url"]
        base_tags = document.xpath("//base[@href]/@href")
        if base_tags:
            base = urljoin(base, base_tags[0])
        for node in document.xpath("//meta[@property or @name]"):
            key = (node.get("property") or node.get("name") or "").lower()
            if key.startswith(("og:", "twitter:")):
                result["social"].append({"property": key, "content": node.get("content", "")})
        for node in document.xpath("//script"):
            kind = node.get("type", "").lower()
            if kind and kind not in {"module", "text/javascript", "application/javascript"}:
                continue
            result["scripts"].append({"url": urljoin(base, node.get("src")) if node.get("src") else "Inline script", "type": kind or "text/javascript"})
        seen = set()
        for node in document.xpath("//a[@href]"):
            target = urljoin(base, node.get("href"))
            if urlparse(target).scheme not in {"http", "https"} or target in seen:
                continue
            seen.add(target)
            result["savedOutlinks"].append({"targetUrl": target, "anchorText": " ".join(node.text_content().split()),
                                          "external": is_external(target, host_of(row["url"])),
                                          "follow": "nofollow" not in node.get("rel", "").lower().split()})
        result["evidenceNote"] = "Recovered from this run’s saved HTML; no live requests."
    except (ValueError, OSError, lxml_html.etree.ParserError) as exc:
        result["evidenceNote"] = f"Saved HTML could not be read ({type(exc).__name__})."
    return result


class LiveStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None
        self.has_run_snapshots = False
        self.has_crawl_schema = False
        self.has_url_sources = False
        self.has_run_url_sources = False
        self.template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
        self.evidence_cache: OrderedDict[tuple[str, int, int], dict[str, Any]] = OrderedDict()

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=4)
        await self._refresh_schema()

    async def _refresh_schema(self) -> None:
        """Re-read which tables exist, per request.

        Not cached at startup: the bridge may be pointed at an empty database
        and the first GUI-started crawl (ticket 124) creates the schema
        underneath it. A stale 'no snapshots' flag would then mislabel every
        run as unscoped current state until the bridge was restarted."""
        assert self.pool
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT to_regclass('crawl_runs') IS NOT NULL AS has_runs,
                       to_regclass('page_run_snapshots') IS NOT NULL AS has_snapshots,
                       to_regclass('page_metadata') IS NOT NULL AS has_pages,
                       to_regclass('url_sources') IS NOT NULL AS has_url_sources,
                       to_regclass('run_url_sources') IS NOT NULL AS has_run_url_sources
                """
            )
        self.has_crawl_schema = bool(row["has_runs"] and row["has_pages"])
        self.has_run_snapshots = bool(row["has_snapshots"])
        self.has_url_sources = bool(row["has_url_sources"])
        self.has_run_url_sources = bool(row["has_run_url_sources"])

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def resume_plan(self, run_id: str, backend: str | None = None) -> dict[str, Any]:
        assert self.pool
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM crawl_runs WHERE run_id=$1", run_id)
            if row is None:
                raise web.HTTPNotFound(text="Crawl run not found")
            counts = await conn.fetch("SELECT status, count(*) AS n FROM frontier WHERE run_id=$1 GROUP BY status", run_id)
        counts = {item["status"]: int(item["n"]) for item in counts}
        reason = ""
        config = None
        if row["mode"] != "open":
            reason = "Only open crawls have a resumable frontier."
        elif not counts.get("queued", 0) + counts.get("pending", 0):
            reason = "No queued or pending URLs remain. Resume does not re-fetch completed URLs or retry recorded HTTP errors."
        elif row["status"] == "running":
            reason = "This run is marked running. Check its original worker before resuming with the CLI."
        else:
            try:
                config, _ = resume_configuration(row, backend)
            except ValueError as exc:
                reason = str(exc)
        return {"runId": run_id, "status": row["status"], "queued": counts.get("queued", 0),
                "pending": counts.get("pending", 0), "done": counts.get("done", 0),
                "canResume": not reason, "reason": reason, "backend": config.backend if config else backend or "aiohttp",
                "url": self._first_seed(row["seed_urls_json"])}

    async def runs(self) -> list[dict[str, Any]]:
        assert self.pool
        await self._refresh_schema()
        if not self.has_crawl_schema:
            # An empty database is a legitimate starting point: the GUI can
            # still open and start its first crawl (ticket 124).
            return []
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
            html_stored = int(
                await conn.fetchval("SELECT COUNT(*)::int FROM pages WHERE html_compressed IS NOT NULL") or 0
            )
            latest = await conn.fetchrow(
                "SELECT mode, seed_urls_json, created_at, updated_at FROM crawl_runs ORDER BY updated_at DESC LIMIT 1"
            )
        url = self._first_seed(latest["seed_urls_json"]) if latest else ""
        return [
            {
                "id": LEGACY_RUN_ID,
                "mode": str(latest["mode"]) if latest else "open",
                "status": "current state",
                "url": url,
                "domain": urlparse(url).netloc or "—",
                "urls": urls,
                "htmlStored": html_stored,
                "date": ((iso_time(latest["updated_at"]) if latest else "") or "")[:10],
                "createdAt": iso_time(latest["created_at"]) if latest else None,
                "updatedAt": iso_time(latest["updated_at"]) if latest else None,
                "runScoped": False,
            }
        ]

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
            "id": str(row["run_id"]),
            "mode": str(row["mode"]),
            "status": str(row["status"]),
            "url": url,
            "domain": urlparse(url).netloc or "—",
            "urls": int(row["urls"]),
            "htmlStored": int(row["html_stored"]),
            "date": date,
            "createdAt": iso_time(row["created_at"]),
            "updatedAt": iso_time(row["updated_at"]),
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

    async def _url_sources(
        self, conn: asyncpg.Connection, run_id: str, url_ids: list[int]
    ) -> dict[int, list[dict[str, str]]]:
        """Return source evidence for the selected run's URL identities.

        New databases use ``run_url_sources``. The older identity-level table
        remains a compatibility fallback, but cannot claim that a historical
        source belonged to the run currently on screen.
        """
        sources: dict[int, list[dict[str, str]]] = defaultdict(list)
        if not url_ids:
            return sources
        if self.has_run_url_sources:
            rows = await conn.fetch(
                """
                SELECT DISTINCT url_id, source, detail
                FROM run_url_sources
                WHERE run_id = $1 AND url_id = ANY($2::int[])
                ORDER BY url_id, source, detail
                """,
                run_id,
                url_ids,
            )
        else:
            rows = []
        for row in rows:
            sources[int(row["url_id"])].append({"source": str(row["source"]), "detail": str(row["detail"] or ""), "scope": "run"})
        if self.has_url_sources:
            legacy_rows = await conn.fetch(
                """
                SELECT DISTINCT url_id, source, detail
                FROM url_sources
                WHERE url_id = ANY($1::int[])
                ORDER BY url_id, source, detail
                """,
                url_ids,
            )
            for row in legacy_rows:
                uid = int(row["url_id"])
                source, detail = str(row["source"]), str(row["detail"] or "")
                if not any(item["source"] == source and item["detail"] == detail for item in sources[uid]):
                    sources[uid].append({"source": source, "detail": detail, "scope": "database"})
        return sources

    async def evidence(self, run_id: str, ids: list[int]) -> list[dict[str, Any]]:
        """Recover fields from saved HTML only; never visit a crawled website."""
        assert self.pool
        if not self.has_run_snapshots:
            return [saved_html_evidence({"url_id": uid}) for uid in ids]
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT s.url_id, u.url, s.fetched_at, s.html_compressed
                   FROM page_run_snapshots s JOIN urls u ON u.id=s.url_id
                   WHERE s.run_id=$1 AND s.url_id=ANY($2::int[])""", run_id, ids,
            )
        results = []
        for row in rows:
            key = (run_id, int(row["url_id"]), int(row["fetched_at"]))
            if key not in self.evidence_cache:
                self.evidence_cache[key] = await asyncio.to_thread(saved_html_evidence, dict(row))
            self.evidence_cache.move_to_end(key)
            results.append(self.evidence_cache[key])
            while len(self.evidence_cache) > 1000:
                self.evidence_cache.popitem(last=False)
        return results

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
                       s.title, s.meta_description, s.h1_tags, s.h2_tags, s.word_count, s.overall_indexable,
                       s.images_json, s.hreflang_json, s.robots_json,
                       (s.html_compressed IS NOT NULL) AS has_stored_html,
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

    def _empty_snapshot(self) -> dict[str, Any]:
        """A valid, empty payload for a database with no crawls yet.

        Returned instead of a 404 so the GUI shell renders and New Crawl works
        against a fresh database (ticket 124). An explicitly requested but
        unknown run still 404s — that is a different, real error."""
        data = copy.deepcopy(self.template)
        data["meta"] = {"uiName": "crawler_gui · live", "source": "PostgreSQL (no crawls yet)", "runId": None}
        data["nav"] = [item for item in data["nav"] if item["id"] != "intent-overlap"]
        data["categoryTabs"] = live_category_tabs(data["categoryTabs"])
        data["pages"] = []
        data["customChecks"] = []
        data["history"] = []
        data["crawl"] = {
            "id": None,
            "url": "",
            "mode": "Spider",
            "status": "none",
            "statusLabel": "No crawls in this database yet — start one with New crawl",
            "progress": {"completed": 0, "total": 0, "pct": 0.0, "remaining": 0},
            "speed": {"average": 0.0, "current": 0.0},
            "startedAt": None,
            "finishedAt": None,
        }
        data["overview"] = overview_from_counts({})
        data["issues"] = []
        data["live"] = {
            "runId": None,
            "totalPages": 0,
            "snapshotBacked": self.has_run_snapshots,
            "runScoped": True,
            "offset": 0,
            "limit": 0,
            "loaded": 0,
            "windowEnd": 0,
            "hasMore": False,
            "truncated": False,
            "empty": True,
        }
        return data

    async def snapshot(self, run_id: str | None, limit: int, offset: int = 0) -> dict[str, Any]:
        runs = await self.runs()
        if not runs:
            if run_id:
                raise web.HTTPNotFound(text=f"Crawl run not found: {run_id}")
            return self._empty_snapshot()
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
            url_sources = await self._url_sources(conn, selected["id"], [page["id"] for page in pages])
        attach_link_graph(pages, inlinks, outlinks)
        attach_url_sources(pages, url_sources)

        data = copy.deepcopy(self.template)
        source = "PostgreSQL run snapshot" if self.has_run_snapshots else "PostgreSQL legacy current-state tables"
        data["meta"] = {"uiName": "crawler_gui · live", "source": source, "runId": selected["id"]}
        data["nav"] = [item for item in data["nav"] if item["id"] != "intent-overlap"]
        data["categoryTabs"] = live_category_tabs(data["categoryTabs"])
        data["pages"] = pages
        # Ticket 257 will add a dedicated run-scoped probe-results relation.
        # URL provenance is not a result and must never populate this view.
        data["customChecks"] = []
        data["detailTabs"] += [
            {"id": "social", "label": "Social Metadata"},
            {"id": "images", "label": "Images"},
            {"id": "hreflang", "label": "Hreflang"},
            {"id": "javascript", "label": "JavaScript"},
            {"id": "sources", "label": "Sources"},
        ]
        data["history"] = [{**run, "viewing": run["id"] == selected["id"]} for run in runs]
        total = selected["urls"]
        window_end = offset + len(pages)
        status_label_text = "snapshot" if self.has_run_snapshots else "legacy state"
        data["crawl"] = {
            "id": selected["id"],
            "url": selected["url"],
            "mode": "Spider" if selected["mode"] == "open" else selected["mode"],
            "status": selected["status"],
            "statusLabel": f"Live {status_label_text} · {selected['status']}",
            "progress": {
                "completed": min(window_end, total),
                "total": total,
                "pct": percent(min(window_end, total), total),
                "remaining": max(0, total - window_end),
            },
            "speed": {"average": 0.0, "current": 0.0},
            "startedAt": selected["createdAt"],
            "finishedAt": selected["updatedAt"],
        }
        # Overview/issues describe the whole run (SQL aggregate), so they stay
        # correct while the grid pages through a large run.
        data["overview"] = overview_from_counts(counts)
        data["issues"] = [
            {
                "severity": "warn",
                "label": "Non-indexable",
                "count": counts.get("total", 0) - counts.get("indexable", 0),
            },
            {"severity": "warn", "label": "Non-200 response", "count": counts.get("total", 0) - counts.get("c2xx", 0)},
        ]
        data["live"] = {
            "runId": selected["id"],
            "totalPages": total,
            "snapshotBacked": self.has_run_snapshots,
            "runScoped": selected.get("runScoped", True),
            "offset": offset,
            "limit": limit,
            "loaded": len(pages),
            "windowEnd": window_end,
            "hasMore": window_end < total,
            "truncated": window_end < total,
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
    limit = _parse_int(
        request.query.get("limit", str(DEFAULT_PAGE_LIMIT)), minimum=1, maximum=MAX_PAGE_LIMIT, name="limit"
    )
    offset = _parse_int(request.query.get("offset", "0"), minimum=0, maximum=2**31, name="offset")
    return web.json_response(await store.snapshot(request.query.get("run"), limit, offset))


async def runs_handler(request: web.Request) -> web.Response:
    store: LiveStore = request.app["store"]
    return web.json_response({"runs": await store.runs()})


async def evidence_handler(request: web.Request) -> web.Response:
    store: LiveStore = request.app["store"]
    run_id = request.query.get("run", "")
    try:
        ids = [int(value) for value in request.query.get("ids", "").split(",") if value]
    except ValueError:
        raise web.HTTPBadRequest(text="ids must be integers") from None
    if not run_id or not ids or len(ids) > 100:
        raise web.HTTPBadRequest(text="Supply a run and 1–100 URL IDs")
    return web.json_response({"pages": await store.evidence(run_id, ids)})


async def resume_plan_handler(request: web.Request) -> web.Response:
    return web.json_response(await request.app["store"].resume_plan(request.match_info["run_id"]))


async def resume_handler(request: web.Request) -> web.Response:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="Expected a JSON object")
    backend = payload.get("backend", "aiohttp")
    if backend not in {"aiohttp", "curl_cffi", "playwright"}:
        raise web.HTTPBadRequest(text="Unknown backend")
    max_pages = _parse_int(str(payload.get("maxPages", 200)), minimum=1, maximum=100000, name="maxPages")
    concurrency = _parse_int(str(payload.get("concurrency", 2)), minimum=1, maximum=20, name="concurrency")
    plan = await request.app["store"].resume_plan(request.match_info["run_id"], backend)
    if not plan["canResume"]:
        raise web.HTTPConflict(text=plan["reason"])
    try:
        job = await request.app["launcher"].resume({"runId": plan["runId"], "backend": backend,
                                                   "maxPages": max_pages, "concurrency": concurrency}, plan["url"])
    except RuntimeError as exc:
        raise web.HTTPConflict(text=str(exc)) from None
    return web.json_response(job.as_json(), status=202)


async def chrome_profiles_handler(_: web.Request) -> web.Response:
    """List local Chrome profile metadata for the profile picker (ticket 128)."""
    return web.json_response({"profiles": discover_chrome_profiles()})


async def create_crawl_handler(request: web.Request) -> web.Response:
    """Start a crawl (ticket 124). 409 while another job is running."""
    launcher: CrawlLauncher = request.app["launcher"]
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text="body must be JSON") from None
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="body must be a JSON object")
    try:
        spec = parse_crawl_spec(payload)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None
    try:
        job = await launcher.start(spec)
    except RuntimeError as exc:
        raise web.HTTPConflict(text=f"a crawl is already running (job {exc})") from None
    except OSError as exc:
        raise web.HTTPInternalServerError(text=f"could not start crawl: {exc}") from None
    return web.json_response(job.as_json(), status=202)


async def crawl_status_handler(request: web.Request) -> web.Response:
    launcher: CrawlLauncher = request.app["launcher"]
    job = launcher.jobs.get(request.match_info["job_id"])
    if job is None:
        raise web.HTTPNotFound(text=f"unknown job: {request.match_info['job_id']}")
    return web.json_response(job.as_json())


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
    app["launcher"] = CrawlLauncher(dsn)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.on_response_prepare.append(no_cache)
    app.router.add_get("/api/live/runs", runs_handler)
    app.router.add_get("/api/live/snapshot", snapshot_handler)
    app.router.add_get("/api/live/evidence", evidence_handler)
    app.router.add_get("/api/live/runs/{run_id}/resume", resume_plan_handler)
    app.router.add_post("/api/live/runs/{run_id}/resume", resume_handler)
    app.router.add_get("/api/live/chrome-profiles", chrome_profiles_handler)
    app.router.add_post("/api/live/crawls", create_crawl_handler)
    app.router.add_get("/api/live/crawls/{job_id}", crawl_status_handler)
    app.router.add_get("/", index_handler)
    app.router.add_static("/", GUI_DIR, show_index=True)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve crawler_gui against a live crawler_cli PostgreSQL database.")
    parser.add_argument(
        "--postgres-dsn",
        default=os.environ.get("CRAWLER_CLI_POSTGRES_DSN"),
        help="Postgres DSN (or set CRAWLER_CLI_POSTGRES_DSN)",
    )
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if not args.postgres_dsn:
        parser.error("set --postgres-dsn or CRAWLER_CLI_POSTGRES_DSN")
    web.run_app(build_app(args.postgres_dsn), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
