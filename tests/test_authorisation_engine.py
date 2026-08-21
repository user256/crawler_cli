"""Ticket 148: the compiled scope predicate at the engine's shared boundaries.

These tests exercise the integration half of the ticket: one predicate governs
initial, discovered, sitemap-document, sitemap-loc, hreflang, robots.txt, and
redirect URL classes; a scope denial is recorded as a scope refusal rather than
an HTTP failure; the canonical snapshot reaches run metadata and saved
artifacts; and a changed scope digest blocks a resume even with the ordinary
config-mismatch opt-in.

The ``TrackingBackend`` in this module records every URL it is asked to fetch,
which is how "no request was made" is proved for each denial: the denied URL
must be absent from its ledger.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import pytest

from crawler_cli import CrawlConfig, CrawlEngine
from crawler_cli.authorisation import (
    SCOPE_MANIFEST_SCHEMA_VERSION,
    ScopeManifestDenied,
    ScopePredicate,
    parse_scope_manifest,
)
from crawler_cli.engine import CrawlRunSelectionError
from crawler_cli.models import FetchResponse
from crawler_cli.serialization import (
    CRAWL_ARTIFACT_SCHEMA_VERSION,
    serialize_crawl_job,
)

from test_sitemap_scope import FakeRobots, TrackingStore, _sitemap_index, _urlset


def predicate_for(
    origins: list[str],
    *,
    allowed_paths: list[str] | None = None,
    excluded_paths: list[str] | None = None,
) -> ScopePredicate:
    """Compile a predicate whose validity window brackets the real clock."""
    now = datetime.now(timezone.utc)
    document = {
        "schema_version": SCOPE_MANIFEST_SCHEMA_VERSION,
        "authorization_reference": "CHANGE-148",
        "operator": "team-evidence",
        "valid_from": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valid_until": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "allowed_origins": origins,
        "allowed_path_prefixes": allowed_paths or ["/"],
        "excluded_path_prefixes": excluded_paths or [],
    }
    return ScopePredicate(parse_scope_manifest(document))


class TrackingBackend:
    """Serves canned pages and records every URL a fetch was attempted for."""

    def __init__(self, pages: dict[str, tuple[bytes, str]], redirects: dict[str, str] | None = None) -> None:
        self.pages = pages
        self.redirects = redirects or {}
        self.fetched: list[str] = []

    async def fetch(self, url: str) -> FetchResponse:
        self.fetched.append(url)
        # A redirect is modelled the way aiohttp reports one: the client has
        # already followed the chain by the time the engine sees the response.
        final_url = self.redirects.get(url, url)
        chain = [{"url": url, "status": 301}] if final_url != url else []
        if final_url not in self.pages:
            return FetchResponse(
                url=final_url,
                requested_url=url,
                status=404,
                headers={"Content-Type": "text/plain"},
                body=b"missing",
                text="missing",
                redirect_chain=chain,
            )
        body, content_type = self.pages[final_url]
        return FetchResponse(
            url=final_url,
            requested_url=url,
            status=200,
            headers={"Content-Type": content_type},
            body=body,
            text=body.decode("utf-8", errors="replace"),
            redirect_chain=chain,
        )

    def fetched_hosts(self) -> set[str]:
        return {urlparse(url).netloc.lower() for url in self.fetched}


def html(*hrefs: str) -> bytes:
    links = "".join(f'<a href="{href}">link</a>' for href in hrefs)
    return f"<html><body>{links}</body></html>".encode("utf-8")


def build_engine(predicate: ScopePredicate, backend: TrackingBackend, store: TrackingStore, **config_kwargs):
    settings: dict[str, object] = {
        "max_concurrency": 2,
        "default_open_crawl_limit": 25,
        "respect_robots_txt": False,
        "discover_sitemaps": False,
        "scope_predicate": predicate,
    }
    settings.update(config_kwargs)
    engine = CrawlEngine(CrawlConfig(**settings), store=store)
    engine.backend = backend
    engine._robots = FakeRobots()
    return engine


# --- Shared admission boundary -------------------------------------------------


@pytest.mark.asyncio
async def test_discovered_link_outside_the_manifest_is_never_fetched() -> None:
    pages = {
        "https://www.example.com/": (html("https://www.example.com/a", "https://other.example/b"), "text/html"),
        "https://www.example.com/a": (html(), "text/html"),
        "https://other.example/b": (html(), "text/html"),
    }
    backend = TrackingBackend(pages)
    store = TrackingStore()
    # ``allowed_hosts`` names the extra host so the pre-existing host-scope
    # filter admits the link and the compiled predicate is demonstrably the
    # thing that refuses it.
    engine = build_engine(
        predicate_for(["https://www.example.com"]),
        backend,
        store,
        allowed_hosts=["other.example"],
    )

    job = await engine.crawl_open(["https://www.example.com/"], max_urls=25)

    assert "https://other.example/b" not in backend.fetched
    # It is recorded as out-of-scope provenance and marked done, never queued.
    assert store.frontier["https://other.example/b"]["status"] == "done"
    assert backend.fetched_hosts() == {"www.example.com"}
    assert {result.final_url for result in job.results if result.skip_reason is None} == {
        "https://www.example.com/",
        "https://www.example.com/a",
    }
    assert any(
        url == "https://other.example/b" and detail == "scope_manifest_denied:origin"
        for url, _source, detail in store.recorded
    )


@pytest.mark.asyncio
async def test_excluded_path_prefix_blocks_a_discovered_link() -> None:
    pages = {
        "https://www.example.com/": (
            html("https://www.example.com/shop/socks", "https://www.example.com/customer/export/all"),
            "text/html",
        ),
        "https://www.example.com/shop/socks": (html(), "text/html"),
        "https://www.example.com/customer/export/all": (html(), "text/html"),
    }
    backend = TrackingBackend(pages)
    store = TrackingStore()
    engine = build_engine(
        predicate_for(["https://www.example.com"], excluded_paths=["/customer/export"]),
        backend,
        store,
    )

    await engine.crawl_open(["https://www.example.com/"], max_urls=25)

    assert "https://www.example.com/customer/export/all" not in backend.fetched
    assert any(
        url == "https://www.example.com/customer/export/all" and detail == "scope_manifest_denied:path"
        for url, _source, detail in store.recorded
    )


@pytest.mark.asyncio
async def test_frontier_entry_outside_scope_is_refused_without_a_fetch() -> None:
    """Even a URL already in the frontier takes the shared admission decision.

    A frontier row can predate a narrowing of scope, so the engine must decide
    admission when it dequeues the URL rather than trusting the queue.
    """
    backend = TrackingBackend({"https://www.example.com/": (html(), "text/html")})
    store = TrackingStore()
    store.frontier["https://other.example/stale"] = {
        "depth": 0,
        "parent_url": None,
        "status": "queued",
        "priority_score": 100.0,
        "retry_count": 0,
    }
    engine = build_engine(predicate_for(["https://www.example.com"]), backend, store)

    await engine.crawl_open(["https://www.example.com/"], max_urls=25)

    assert "https://other.example/stale" not in backend.fetched
    assert store.frontier["https://other.example/stale"]["status"] == "done"


@pytest.mark.asyncio
async def test_direct_crawl_records_a_scope_refusal_not_an_http_failure() -> None:
    backend = TrackingBackend({})
    engine = build_engine(predicate_for(["https://www.example.com"]), backend, TrackingStore())

    result = await engine.crawl("https://other.example/a")

    assert backend.fetched == []
    assert result.status == 0
    assert result.skip_reason == "scope_manifest_denied:origin"


@pytest.mark.asyncio
async def test_expired_window_denies_at_fetch_time_without_a_request() -> None:
    now = datetime.now(timezone.utc)
    expired = ScopePredicate(
        parse_scope_manifest(
            {
                "schema_version": SCOPE_MANIFEST_SCHEMA_VERSION,
                "authorization_reference": "CHANGE-148",
                "operator": "team-evidence",
                "valid_from": (now - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "valid_until": (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "allowed_origins": ["https://www.example.com"],
                "allowed_path_prefixes": ["/"],
            }
        )
    )
    backend = TrackingBackend({"https://www.example.com/": (html(), "text/html")})
    engine = build_engine(expired, backend, TrackingStore())

    result = await engine.crawl("https://www.example.com/")

    assert backend.fetched == []
    assert result.skip_reason == "scope_manifest_denied:time_window"


# --- Auxiliary URL classes ------------------------------------------------------


@pytest.mark.asyncio
async def test_sitemap_document_outside_the_manifest_is_never_fetched() -> None:
    """A robots.txt Sitemap: directive cannot point the crawl off the manifest."""
    pages = {
        "https://www.example.com/sitemap.xml": (_urlset("https://www.example.com/a"), "application/xml"),
        "https://www.example.com/a": (html(), "text/html"),
        "https://cdn.other.example/sitemap.xml": (_urlset("https://www.example.com/b"), "application/xml"),
    }
    backend = TrackingBackend(pages)
    store = TrackingStore()
    engine = build_engine(
        predicate_for(["https://www.example.com"]),
        backend,
        store,
        discover_sitemaps=True,
        allowed_hosts=["cdn.other.example"],
    )
    engine._robots = FakeRobots(
        sitemaps=["https://www.example.com/sitemap.xml", "https://cdn.other.example/sitemap.xml"]
    )

    await engine.crawl_open(["https://www.example.com/"], max_urls=25)

    assert "https://cdn.other.example/sitemap.xml" not in backend.fetched
    assert any(
        url == "https://cdn.other.example/sitemap.xml" and detail == "scope_manifest_denied:origin"
        for url, _source, detail in store.recorded
    )


@pytest.mark.asyncio
async def test_sitemap_index_child_outside_the_manifest_is_never_fetched() -> None:
    pages = {
        "https://www.example.com/sitemap.xml": (
            _sitemap_index("https://www.example.com/sitemap-a.xml", "https://cdn.other.example/sitemap-b.xml"),
            "application/xml",
        ),
        "https://www.example.com/sitemap-a.xml": (_urlset("https://www.example.com/a"), "application/xml"),
        "https://cdn.other.example/sitemap-b.xml": (_urlset("https://www.example.com/b"), "application/xml"),
        "https://www.example.com/a": (html(), "text/html"),
    }
    backend = TrackingBackend(pages)
    store = TrackingStore()
    engine = build_engine(
        predicate_for(["https://www.example.com"]),
        backend,
        store,
        discover_sitemaps=True,
        allowed_hosts=["cdn.other.example"],
    )
    engine._robots = FakeRobots(sitemaps=["https://www.example.com/sitemap.xml"])

    await engine.crawl_open(["https://www.example.com/"], max_urls=25)

    assert "https://cdn.other.example/sitemap-b.xml" not in backend.fetched


@pytest.mark.asyncio
async def test_sitemap_loc_and_hreflang_take_the_same_decision() -> None:
    """The manifest is the backstop when host scope alone would have admitted.

    ``allowed_hosts`` deliberately names the extra host so the older host-scope
    check passes and the compiled predicate is the thing that refuses the loc
    and its hreflang alternate.
    """
    pages = {
        "https://www.example.com/sitemap.xml": (
            _urlset(
                "https://www.example.com/a",
                "https://other.example/b",
                hreflang=[("https://www.example.com/a", "de", "https://other.example/a-de")],
            ),
            "application/xml",
        ),
        "https://www.example.com/a": (html(), "text/html"),
    }
    backend = TrackingBackend(pages)
    store = TrackingStore()
    engine = build_engine(
        predicate_for(["https://www.example.com"]),
        backend,
        store,
        discover_sitemaps=True,
        allowed_hosts=["other.example"],
    )
    engine._robots = FakeRobots(sitemaps=["https://www.example.com/sitemap.xml"])

    await engine.crawl_open(["https://www.example.com/"], max_urls=25)

    assert "https://other.example/b" not in backend.fetched
    assert "https://other.example/b" not in store.frontier
    assert store.hreflang_pairs == []
    recorded = {url: detail for url, _source, detail in store.recorded}
    assert recorded["https://other.example/b"] == "scope_manifest_denied:origin"
    assert recorded["https://other.example/a-de"] == "scope_manifest_denied:origin"


@pytest.mark.asyncio
async def test_robots_txt_uses_the_same_scope_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    """An out-of-scope robots.txt is refused before any HTTP session is opened."""
    from crawler_cli import robots as robots_module

    config = CrawlConfig(
        respect_robots_txt=True,
        discover_sitemaps=False,
        scope_predicate=predicate_for(["https://www.example.com"]),
    )
    cache = robots_module.RobotsPolicyCache(config)

    def _forbidden(*args: object, **kwargs: object):
        raise AssertionError("robots.txt fetch attempted for an out-of-scope origin")

    monkeypatch.setattr(robots_module.aiohttp, "ClientSession", _forbidden)

    content, headers, status = await cache._fetch_robots_txt("https://other.example/page")

    assert content is None
    assert headers == {}
    # Status 0 routes into the RFC 9309 unreachable handling, so the origin is
    # treated as fully disallowed rather than as an allow-all missing file.
    assert status == 0
    assert await cache.is_allowed("https://other.example/page") is False


@pytest.mark.asyncio
async def test_in_scope_robots_txt_is_still_allowed_under_a_narrow_path_manifest() -> None:
    predicate = predicate_for(["https://www.example.com"], allowed_paths=["/shop"])
    assert predicate.is_allowed("https://www.example.com/robots.txt", purpose="robots")


# --- Redirect boundary ----------------------------------------------------------


@pytest.mark.asyncio
async def test_redirect_out_of_scope_is_refused_and_not_recorded_as_content() -> None:
    """A client-followed redirect chain is re-checked as soon as it is visible."""
    pages = {"https://other.example/landing": (html(), "text/html")}
    backend = TrackingBackend(pages, redirects={"https://www.example.com/go": "https://other.example/landing"})
    engine = build_engine(predicate_for(["https://www.example.com"]), backend, TrackingStore())

    result = await engine.crawl("https://www.example.com/go")

    assert result.skip_reason == "scope_manifest_denied:origin"
    assert result.status == 0
    assert result.raw_html is None


@pytest.mark.asyncio
async def test_in_scope_redirect_is_admitted_normally() -> None:
    pages = {"https://www.example.com/landing": (html(), "text/html")}
    backend = TrackingBackend(pages, redirects={"https://www.example.com/go": "https://www.example.com/landing"})
    engine = build_engine(predicate_for(["https://www.example.com"]), backend, TrackingStore())

    result = await engine.crawl("https://www.example.com/go")

    assert result.skip_reason is None
    assert result.final_url == "https://www.example.com/landing"


@pytest.mark.asyncio
async def test_sitemap_redirect_out_of_scope_does_not_open_the_breaker() -> None:
    pages = {"https://other.example/sitemap.xml": (_urlset("https://www.example.com/a"), "application/xml")}
    backend = TrackingBackend(
        pages, redirects={"https://www.example.com/sitemap.xml": "https://other.example/sitemap.xml"}
    )
    engine = build_engine(predicate_for(["https://www.example.com"]), backend, TrackingStore())

    response = await engine._bounded_fetch_response("https://www.example.com/sitemap.xml")

    assert response is None
    circuit = engine._circuit_breakers.for_host("www.example.com")
    assert circuit.should_allow() is True


def test_scope_denial_is_a_distinct_exception_type() -> None:
    predicate = predicate_for(["https://www.example.com"])
    with pytest.raises(ScopeManifestDenied):
        predicate.require("https://other.example/a", purpose="redirect")


# --- Snapshot, artifacts, and resume --------------------------------------------


@pytest.mark.asyncio
async def test_run_metadata_and_artifact_carry_the_scope_snapshot(tmp_path) -> None:
    class MetadataStore(TrackingStore):
        def __init__(self) -> None:
            super().__init__()
            self.metadata: dict[str, dict[str, object]] = {}

        async def save_metadata(self, key: str, value: dict[str, object]) -> None:
            self.metadata[key] = value

    predicate = predicate_for(["https://www.example.com"])
    backend = TrackingBackend({"https://www.example.com/": (html(), "text/html")})
    store = MetadataStore()
    engine = build_engine(predicate, backend, store)
    artifact_path = tmp_path / "crawl.json"

    job = await engine.crawl_open(["https://www.example.com/"], max_urls=5, save_to=str(artifact_path))

    scope = job.authorization_scope
    assert scope is not None
    assert scope["authorization_reference"] == "CHANGE-148"
    assert scope["allowed_origins"] == ["https://www.example.com:443"]

    metadata_scope = store.metadata["crawl_open"]["authorization_scope"]
    assert metadata_scope == scope

    payload = serialize_crawl_job(job)
    assert payload["schema_version"] == CRAWL_ARTIFACT_SCHEMA_VERSION
    assert payload["authorization_scope"] == scope


def test_artifact_without_a_manifest_carries_an_explicit_null_scope() -> None:
    from crawler_cli.models import CrawlJobResult

    payload = serialize_crawl_job(CrawlJobResult(mode="list", seed_urls=[], results=[]))
    assert payload["schema_version"] == CRAWL_ARTIFACT_SCHEMA_VERSION
    assert "authorization_scope" in payload
    assert payload["authorization_scope"] is None


@pytest.mark.asyncio
async def test_changed_scope_digest_blocks_resume_even_with_the_mismatch_opt_in() -> None:
    from crawler_cli.persistence import MemoryStore

    original = predicate_for(["https://www.example.com"])
    widened = predicate_for(["https://www.example.com", "https://cdn.example.com"])
    store = MemoryStore()
    backend = TrackingBackend({"https://www.example.com/": (html(), "text/html")})

    engine = build_engine(original, backend, store)
    await engine.crawl_open(["https://www.example.com/"], max_urls=5, run_id="run-148")

    resumed = build_engine(widened, TrackingBackend({}), store)
    with pytest.raises(CrawlRunSelectionError) as excinfo:
        await resumed.crawl_open(
            ["https://www.example.com/"],
            max_urls=5,
            run_id="run-148",
            resume=True,
            allow_run_config_mismatch=True,
        )
    message = str(excinfo.value)
    assert "authorization scope changed" in message
    assert "not waivable by --allow-run-config-mismatch" in message


@pytest.mark.asyncio
async def test_unchanged_scope_digest_permits_resume() -> None:
    from crawler_cli.persistence import MemoryStore

    store = MemoryStore()
    backend = TrackingBackend({"https://www.example.com/": (html(), "text/html")})
    engine = build_engine(predicate_for(["https://www.example.com"]), backend, store)
    await engine.crawl_open(["https://www.example.com/"], max_urls=5, run_id="run-148b")

    resumed = build_engine(predicate_for(["https://www.example.com"]), TrackingBackend({}), store)
    job = await resumed.crawl_open(
        ["https://www.example.com/"],
        max_urls=5,
        run_id="run-148b",
        resume=True,
    )
    assert job.run_id == "run-148b"


@pytest.mark.asyncio
async def test_adding_a_manifest_to_an_existing_run_is_refused() -> None:
    """A manifest-free run cannot silently acquire an authorisation scope."""
    from crawler_cli.persistence import MemoryStore

    store = MemoryStore()
    backend = TrackingBackend({"https://www.example.com/": (html(), "text/html")})
    engine = CrawlEngine(
        CrawlConfig(max_concurrency=1, respect_robots_txt=False, discover_sitemaps=False),
        store=store,
    )
    engine.backend = backend
    engine._robots = FakeRobots()
    await engine.crawl_open(["https://www.example.com/"], max_urls=5, run_id="run-148c")

    resumed = build_engine(predicate_for(["https://www.example.com"]), TrackingBackend({}), store)
    with pytest.raises(CrawlRunSelectionError) as excinfo:
        await resumed.crawl_open(
            ["https://www.example.com/"],
            max_urls=5,
            run_id="run-148c",
            resume=True,
            allow_run_config_mismatch=True,
        )
    assert "stored digest none" in str(excinfo.value)


@pytest.mark.asyncio
async def test_scope_logging_names_the_digest_not_the_manifest_body(caplog) -> None:
    predicate = predicate_for(["https://www.example.com"])
    engine = build_engine(predicate, TrackingBackend({}), TrackingStore())
    with caplog.at_level("INFO"):
        engine._log_scope_manifest()
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "CHANGE-148" in logged
    assert predicate.digest[:16] in logged
    assert "allowed_path_prefixes" not in logged


def test_run_snapshot_is_absent_for_a_manifest_free_crawl() -> None:
    from crawler_cli.engine import _crawl_run_config_snapshot

    snapshot = _crawl_run_config_snapshot(CrawlConfig(), ["https://www.example.com/"])
    assert "authorization_scope" not in snapshot
    # The serialized fingerprint is unchanged for ordinary crawls, so runs
    # created before ticket 148 stay resumable.
    assert json.loads(json.dumps(snapshot))["seed_urls"] == ["https://www.example.com/"]
