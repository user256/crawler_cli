from __future__ import annotations

import asyncio
from types import SimpleNamespace

from crawler_cli import external_link_checks as checks
from crawler_cli.authorisation import ScopeDecision


class _Predicate:
    class _Manifest:
        allowed_origins = ["https://allowed.example"]

    manifest = _Manifest()

    def decide(self, url: str, *, purpose: str, method: str) -> ScopeDecision:
        del purpose, method
        allowed = url.startswith("https://allowed.example/")
        return ScopeDecision(allowed=allowed, reason=None if allowed else "origin")


class _Engine:
    calls: list[str] = []
    statuses: list[int] = []

    def __init__(self, config):
        self.config = config

    async def crawl(self, url: str, *, purpose: str):
        del purpose
        self.calls.append(url)
        status = self.statuses.pop(0)
        return SimpleNamespace(
            requested_url=url,
            final_url=url,
            headers={"Content-Type": "text/html", "Location": "https://allowed.example/path?token=secret"},
            status=status,
            fetch_backend="aiohttp",
            allowed_by_robots=True,
            skip_reason=None,
            challenge=None,
            redirect_chain=[{"status": status, "url": url}],
            content_type="text/html",
        )

    async def close(self):
        return None


def test_external_rechecks_are_bounded_scoped_and_retry_only_failures(monkeypatch):
    _Engine.calls = []
    _Engine.statuses = [503, 200]
    monkeypatch.setattr(checks, "CrawlEngine", _Engine)
    instances = [
        {
            "source_url": "https://site.example/page?session=private",
            "target_url": "https://allowed.example/fail?token=secret#fragment",
            "device": "desktop_viewport",
            "anchor_text": "Out link",
            "dom_path": "main > a:nth-of-type(1)",
            "capture_phase": "after_bounded_scroll",
            "reveal_state": "scroll_revealed",
        },
        {
            "source_url": "https://site.example/other",
            "target_url": "https://blocked.example/no-fetch",
            "device": "mobile_viewport",
        },
        {
            "source_url": "https://site.example/third",
            "target_url": "https://site.example/internal",
        },
    ]

    records = asyncio.run(checks.collect_external_link_rechecks(instances, scope_predicate=_Predicate()))

    coverage, *rows = records
    assert coverage["state"] == "partial"
    assert coverage["attempted_target_count"] == 1
    assert coverage["out_of_scope_target_count"] == 1
    assert coverage["invalid_or_internal_instance_count"] == 1
    assert len(_Engine.calls) == 2  # one initial fetch plus one transient-failure recheck
    observed = next(row for row in rows if row["state"] == "intermittent_failure")
    assert len(observed["attempts"]) == 2
    assert observed["source_page_count"] == 1
    assert "token=secret" not in str(observed)
    assert "session=private" not in str(observed)
    denied = next(row for row in rows if row["state"] == "out_of_scope")
    assert denied["attempts"] == []
    assert _Engine.calls == ["https://allowed.example/fail?token=secret"] * 2


def test_external_rechecks_cap_target_selection_deterministically(monkeypatch):
    _Engine.calls = []
    _Engine.statuses = [200] * 2
    monkeypatch.setattr(checks, "CrawlEngine", _Engine)
    instances = [
        {"source_url": "https://site.example/", "target_url": f"https://allowed.example/{path}"}
        for path in ("z", "a", "m")
    ]

    records = asyncio.run(checks.collect_external_link_rechecks(instances, scope_predicate=_Predicate(), max_targets=2))

    assert records[0]["candidate_target_count"] == 3
    assert records[0]["omitted_target_count"] == 1
    assert [row["target_url"] for row in records[1:]] == [
        "https://allowed.example/a",
        "https://allowed.example/m",
    ]
    assert _Engine.calls == ["https://allowed.example/a", "https://allowed.example/m"]
