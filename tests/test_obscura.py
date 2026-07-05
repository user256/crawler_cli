from __future__ import annotations

import argparse
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from crawler_cli.__main__ import _build_config, _build_parser, _validate_obscura_args
from crawler_cli.backends import PlaywrightBackend, build_backend
from crawler_cli.config import CrawlConfig
from crawler_cli.engine import CrawlEngine
from crawler_cli.models import BrowserRuntime, CrawlResult


class FakeArgs:
    """Minimal argparse.Namespace stand-in for _build_config tests."""

    def __init__(self, **kwargs):
        defaults = {
            "js": False,
            "http_backend": None,
            "custom_ua": "",
            "concurrency": None,
            "max_workers": None,
            "max_requests_per_context": 50,
            "max_pages": 0,
            "timeout": 30.0,
            "playwright_network_idle_timeout": 5.0,
            "playwright_cdp_endpoint": "",
            "memory_high_watermark": 85.0,
            "memory_recovery_watermark": 70.0,
            "ignore_robots": False,
            "offsite": False,
            "archive_org_check": False,
            "allowed_hosts": "",
            "path_restriction": "",
            "path_exclude": "",
            "auth_type": "",
            "auth_username": "",
            "auth_password": "",
            "auth_token": "",
            "csv_file": None,
            "csv_column": "url",
            "csv_seed": False,
            "skip_sitemaps": False,
            "cms_detection": False,
            "analytics_detection": False,
            "analytics_expected_id": [],
            "content_hashing": False,
            "no_html_compression": False,
            "no_store_html": False,
            "obscura": False,
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


def test_obscura_implies_js_and_playwright_backend():
    args = FakeArgs(obscura=True)
    config = _build_config(args)
    assert config.backend == "playwright"
    assert args.js is True
    assert config.obscura_enabled is True


def test_obscura_default_stealth_when_no_analytics():
    args = FakeArgs(obscura=True)
    config = _build_config(args)
    assert config.obscura_stealth is None
    # Effective stealth is resolved later; config stores None for implicit default


def test_obscura_explicit_stealth():
    args = FakeArgs(obscura=True, obscura_stealth=True)
    config = _build_config(args)
    assert config.obscura_stealth is True


def test_obscura_explicit_no_stealth():
    args = FakeArgs(obscura=True, no_obscura_stealth=True)
    config = _build_config(args)
    assert config.obscura_stealth is False


def test_obscura_analytics_without_stealth_choice_exits():
    args = FakeArgs(obscura=True, analytics_detection=True)
    with pytest.raises(SystemExit) as exc_info:
        _build_config(args)
    assert exc_info.value.code == 2


def test_obscura_analytics_with_explicit_stealth_allowed():
    args = FakeArgs(obscura=True, analytics_detection=True, obscura_stealth=True)
    config = _build_config(args)
    assert config.obscura_stealth is True


def test_obscura_analytics_with_explicit_no_stealth_allowed():
    args = FakeArgs(obscura=True, analytics_detection=True, no_obscura_stealth=True)
    config = _build_config(args)
    assert config.obscura_stealth is False


def test_obscura_flag_without_obscura_fails():
    args = FakeArgs(obscura=False, obscura_port=9333)
    with pytest.raises(SystemExit) as exc_info:
        _validate_obscura_args(args)
    assert exc_info.value.code == 2


def test_obscura_default_value_flag_without_obscura_still_fails():
    parser = _build_parser()
    args = parser.parse_args(["crawl", "https://example.com", "--obscura-port", "9222"])
    with pytest.raises(SystemExit) as exc_info:
        _build_config(args)
    assert exc_info.value.code == 2


def test_obscura_and_cdp_endpoint_mutually_exclusive():
    args = FakeArgs(
        obscura=True,
        playwright_cdp_endpoint="http://127.0.0.1:9222",
    )
    with pytest.raises(SystemExit) as exc_info:
        _validate_obscura_args(args)
    assert exc_info.value.code == 2


def test_conflicting_obscura_stealth_flags_fail():
    args = FakeArgs(obscura=True, obscura_stealth=True, no_obscura_stealth=True)
    with pytest.raises(SystemExit) as exc_info:
        _build_config(args)
    assert exc_info.value.code == 2


def test_obscura_unmanaged_sets_managed_false():
    args = FakeArgs(obscura=True, obscura_unmanaged=True)
    config = _build_config(args)
    assert config.obscura_managed is False


def test_build_backend_obscura_returns_playwright():
    config = CrawlConfig(backend="playwright", obscura_enabled=True)
    backend = build_backend(config)
    assert isinstance(backend, PlaywrightBackend)


@pytest.mark.asyncio
async def test_managed_obscura_spawns_expected_argv(monkeypatch):
    """Managed mode should build the correct command line."""
    config = CrawlConfig(
        backend="playwright",
        obscura_enabled=True,
        obscura_managed=True,
        obscura_binary="/usr/bin/obscura",
        obscura_port=9333,
        obscura_workers=4,
        obscura_proxy="http://proxy:8080",
        obscura_stealth=True,
    )
    backend = PlaywrightBackend(config)
    fake_browser = MagicMock()
    fake_browser.close = AsyncMock()
    captured_call: dict[str, object] = {}

    class FakeChromium:
        def __init__(self) -> None:
            self.connect_calls: list[str] = []

        async def connect_over_cdp(self, endpoint: str):
            self.connect_calls.append(endpoint)
            return fake_browser

    fake_playwright = MagicMock()
    fake_playwright.chromium = FakeChromium()
    backend._playwright = fake_playwright

    async def fake_subprocess_exec(*argv, **kwargs):
        captured_call["argv"] = list(argv)
        captured_call["kwargs"] = kwargs
        proc = MagicMock()
        proc.stderr = MagicMock()
        proc.stderr.read = AsyncMock(return_value=b"")
        proc.returncode = None
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=0)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
    await backend._start_managed_obscura()

    assert backend._managed_obscura_proc is not None
    assert captured_call["argv"] == [
        "/usr/bin/obscura",
        "serve",
        "--port",
        "9333",
        "--workers",
        "4",
        "--proxy",
        "http://proxy:8080",
        "--stealth",
    ]
    assert captured_call["kwargs"] == {"stderr": asyncio.subprocess.PIPE}
    assert fake_playwright.chromium.connect_calls == ["http://127.0.0.1:9333"]
    fake_browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_managed_obscura_shutdown_terminates_only_managed():
    """Close should terminate the managed process but never an unmanaged one."""
    config = CrawlConfig(
        backend="playwright",
        obscura_enabled=True,
        obscura_managed=True,
    )
    backend = PlaywrightBackend(config)

    proc = MagicMock()
    proc.returncode = None
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    backend._managed_obscura_proc = proc  # type: ignore[assignment]

    await backend.close()

    proc.terminate.assert_called_once()
    assert backend._managed_obscura_proc is None


@pytest.mark.asyncio
async def test_unmanaged_obscura_shutdown_does_not_kill():
    config = CrawlConfig(
        backend="playwright",
        obscura_enabled=True,
        obscura_managed=False,
    )
    backend = PlaywrightBackend(config)

    # No managed process; close should be a no-op for Obscura lifecycle
    await backend.close()
    assert backend._managed_obscura_proc is None


def test_engine_browser_runtime_for_obscura():
    config = CrawlConfig(
        backend="playwright",
        obscura_enabled=True,
        obscura_managed=True,
        obscura_stealth=None,
    )
    engine = CrawlEngine(config)
    runtime = engine._build_browser_runtime()
    assert runtime is not None
    assert runtime.provider == "obscura"
    assert runtime.cdp_endpoint == "http://127.0.0.1:9222"
    assert runtime.managed is True
    assert runtime.stealth is True  # default when analytics off
    assert runtime.persistent is None


def test_engine_browser_runtime_for_unmanaged_obscura_without_explicit_stealth():
    config = CrawlConfig(
        backend="playwright",
        obscura_enabled=True,
        obscura_managed=False,
        obscura_stealth=None,
    )
    engine = CrawlEngine(config)
    runtime = engine._build_browser_runtime()
    assert runtime is not None
    assert runtime.provider == "obscura"
    assert runtime.managed is False
    assert runtime.stealth is None


def test_engine_browser_runtime_for_cdp():
    config = CrawlConfig(
        backend="playwright",
        playwright_cdp_endpoint="http://127.0.0.1:9222",
    )
    engine = CrawlEngine(config)
    runtime = engine._build_browser_runtime()
    assert runtime is not None
    assert runtime.provider == "cdp"
    assert runtime.cdp_endpoint == "http://127.0.0.1:9222"
    assert runtime.managed is None
    assert runtime.stealth is None
    assert runtime.persistent is None


def test_engine_browser_runtime_for_chromium():
    config = CrawlConfig(backend="playwright")
    engine = CrawlEngine(config)
    runtime = engine._build_browser_runtime()
    assert runtime is not None
    assert runtime.provider == "chromium"
    assert runtime.cdp_endpoint is None
    assert runtime.persistent is False
    assert runtime.headless is True


def test_engine_browser_runtime_for_persistent_profile_launch():
    config = CrawlConfig(
        backend="playwright",
        playwright_browser_channel="msedge",
        playwright_user_data_dir="/tmp/edge-user-data",
        playwright_profile_directory="Profile 5",
        playwright_headless=False,
    )
    engine = CrawlEngine(config)
    runtime = engine._build_browser_runtime()
    assert runtime is not None
    assert runtime.provider == "chromium"
    assert runtime.persistent is True
    assert runtime.channel == "msedge"
    assert runtime.user_data_dir == "/tmp/edge-user-data"
    assert runtime.profile_directory == "Profile 5"
    assert runtime.headless is False


def test_engine_browser_runtime_none_for_http():
    config = CrawlConfig(backend="aiohttp")
    engine = CrawlEngine(config)
    runtime = engine._build_browser_runtime()
    assert runtime is None


def test_result_to_dict_includes_browser_runtime():
    result = CrawlResult(
        requested_url="https://example.com",
        final_url="https://example.com",
        status=200,
        headers={},
        content_type="text/html",
        fetch_backend="playwright",
        extracted=None,
        raw_html="<html></html>",
        browser_runtime=BrowserRuntime(
            provider="obscura",
            cdp_endpoint="http://127.0.0.1:9222",
            managed=True,
            stealth=True,
        ),
    )
    engine = CrawlEngine(CrawlConfig(backend="playwright"))
    d = engine._result_to_dict(result)
    assert d["fetch_backend"] == "playwright"
    assert d["browser_runtime"] == {
        "provider": "obscura",
        "cdp_endpoint": "http://127.0.0.1:9222",
        "managed": True,
        "stealth": True,
        "persistent": None,
        "channel": None,
        "executable_path": None,
        "user_data_dir": None,
        "profile_directory": None,
        "headless": None,
    }


def test_result_to_dict_omits_browser_runtime_when_none():
    result = CrawlResult(
        requested_url="https://example.com",
        final_url="https://example.com",
        status=200,
        headers={},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=None,
        raw_html="<html></html>",
        browser_runtime=None,
    )
    engine = CrawlEngine(CrawlConfig(backend="aiohttp"))
    d = engine._result_to_dict(result)
    assert "browser_runtime" not in d


@pytest.mark.asyncio
async def test_ensure_started_stops_playwright_after_cdp_connect_failure(monkeypatch):
    class FakeChromium:
        async def connect_over_cdp(self, endpoint: str):
            raise RuntimeError(f"connect failed: {endpoint}")

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = FakeChromium()
            self.stop = AsyncMock()

    fake_playwright = FakePlaywright()

    class FakeAsyncPlaywrightFactory:
        async def start(self):
            return fake_playwright

    async_api_module = MagicMock()
    async_api_module.async_playwright = lambda: FakeAsyncPlaywrightFactory()
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api_module)

    config = CrawlConfig(
        backend="playwright",
        playwright_cdp_endpoint="http://127.0.0.1:9222",
    )
    backend = PlaywrightBackend(config)

    with pytest.raises(RuntimeError, match="connect failed"):
        await backend._ensure_started()

    fake_playwright.stop.assert_awaited_once()
    assert backend._playwright is None


def test_run_compare_loads_old_json_without_browser_runtime():
    """Regression: saved JSON without browser_runtime must still load."""
    from crawler_cli.__main__ import _run_compare

    import json
    from pathlib import Path

    baseline = {
        "mode": "list",
        "seed_urls": [],
        "results": [
            {
                "requested_url": "https://example.com",
                "final_url": "https://example.com",
                "status": 200,
                "headers": {},
                "fetch_backend": "playwright",
            }
        ],
    }
    candidate = {
        "mode": "list",
        "seed_urls": [],
        "results": [
            {
                "requested_url": "https://example.com",
                "final_url": "https://example.com",
                "status": 200,
                "headers": {},
                "fetch_backend": "playwright",
                "browser_runtime": {
                    "provider": "obscura",
                    "cdp_endpoint": "http://127.0.0.1:9222",
                    "managed": True,
                    "stealth": True,
                },
            }
        ],
    }

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        base_path = Path(tmp) / "baseline.json"
        cand_path = Path(tmp) / "candidate.json"
        base_path.write_text(json.dumps(baseline), encoding="utf-8")
        cand_path.write_text(json.dumps(candidate), encoding="utf-8")

        args = argparse.Namespace(
            baseline_json=str(base_path),
            candidate_json=str(cand_path),
            baseline_label="base",
            candidate_label="cand",
            compare_links=False,
            output=None,
            persist=False,
        )
        # _run_compare is async; run it via asyncio
        import asyncio

        code = asyncio.run(_run_compare(args))
        assert code == 0


def test_run_compare_accepts_open_crawl_jsonl_and_preserves_deep_diff_fields():
    """Regression: compare must accept crawl_open JSONL and retain metadata/links."""
    from crawler_cli.__main__ import _run_compare

    import json
    from pathlib import Path

    baseline_lines = [
        {
            "requested_url": "https://example.com/page",
            "final_url": "https://example.com/page",
            "status": 200,
            "headers": {},
            "fetch_backend": "aiohttp",
            "raw_html": "<html></html>",
            "content_hash_sha256": "aaa",
            "discovered_links": [
                {
                    "href": "https://example.com/a",
                    "anchor_text": "A",
                    "xpath": "/html/body/a[1]",
                    "is_image": False,
                    "fragment": None,
                    "url_parameters": None,
                    "original_href": "https://example.com/a",
                }
            ],
            "extracted": {
                "title": "Old title",
                "meta_description": "Old meta",
                "meta_robots": [],
                "x_robots_tag": [],
                "canonical": "https://example.com/page",
                "x_canonical": None,
                "hreflang_links": [],
                "html_lang": "en",
                "headings": {"h1": ["Old H1"], "h2": []},
                "text": "old text",
                "word_count": 100,
                "metadata": {},
                "schema_data": [{"type": "Article", "format": "json-ld", "is_valid": True}],
            },
        },
        {
            "__type": "summary",
            "mode": "open",
            "seed_urls": ["https://example.com/"],
            "crawled_count": 1,
            "blocked_count": 0,
            "persist_error_count": 0,
            "retry_attempts": 0,
            "interrupted": False,
            "saved_to": "baseline.jsonl",
        },
    ]
    candidate_lines = [
        {
            "requested_url": "https://example.com/page",
            "final_url": "https://example.com/page",
            "status": 200,
            "headers": {},
            "fetch_backend": "aiohttp",
            "raw_html": "<html></html>",
            "content_hash_sha256": "bbb",
            "discovered_links": [
                {
                    "href": "https://example.com/b",
                    "anchor_text": "B",
                    "xpath": "/html/body/a[2]",
                    "is_image": False,
                    "fragment": None,
                    "url_parameters": None,
                    "original_href": "https://example.com/b",
                }
            ],
            "extracted": {
                "title": "New title",
                "meta_description": "New meta",
                "meta_robots": [],
                "x_robots_tag": [],
                "canonical": "https://example.com/page",
                "x_canonical": None,
                "hreflang_links": [],
                "html_lang": "en",
                "headings": {"h1": ["New H1"], "h2": []},
                "text": "new text",
                "word_count": 120,
                "metadata": {},
                "schema_data": [{"type": "Product", "format": "json-ld", "is_valid": True}],
            },
        },
        {
            "__type": "summary",
            "mode": "open",
            "seed_urls": ["https://example.com/"],
            "crawled_count": 1,
            "blocked_count": 0,
            "persist_error_count": 0,
            "retry_attempts": 0,
            "interrupted": False,
            "saved_to": "candidate.jsonl",
        },
    ]

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        base_path = Path(tmp) / "baseline.jsonl"
        cand_path = Path(tmp) / "candidate.jsonl"
        out_path = Path(tmp) / "compare_rows.json"
        base_path.write_text("\n".join(json.dumps(line) for line in baseline_lines) + "\n", encoding="utf-8")
        cand_path.write_text("\n".join(json.dumps(line) for line in candidate_lines) + "\n", encoding="utf-8")

        args = argparse.Namespace(
            baseline_json=str(base_path),
            candidate_json=str(cand_path),
            baseline_label="base",
            candidate_label="cand",
            compare_links=True,
            output=str(out_path),
            persist=False,
        )

        code = asyncio.run(_run_compare(args))
        assert code == 0

        rows = json.loads(out_path.read_text(encoding="utf-8"))
        assert rows[0]["baseline_title"] == "Old title"
        assert rows[0]["candidate_title"] == "New title"
        assert rows[0]["baseline_h1"] == "Old H1"
        assert rows[0]["candidate_h1"] == "New H1"
        assert rows[0]["baseline_meta_description"] == "Old meta"
        assert rows[0]["candidate_meta_description"] == "New meta"
        assert rows[0]["baseline_word_count"] == 100
        assert rows[0]["candidate_word_count"] == 120
        assert rows[0]["baseline_schema_types"] == ["Article"]
        assert rows[0]["candidate_schema_types"] == ["Product"]
        assert rows[0]["links_added"][0]["href"] == "https://example.com/b"
        assert rows[0]["links_removed"][0]["href"] == "https://example.com/a"


# ---------------------------------------------------------------------------
# Obscura binary discovery + installer (obscura_install.py)
# ---------------------------------------------------------------------------


def test_asset_matrix_covers_common_platforms():
    from crawler_cli.obscura_install import _ASSET_MATRIX

    assert _ASSET_MATRIX[("linux", "x86_64")] == "obscura-x86_64-linux"
    assert _ASSET_MATRIX[("linux", "aarch64")] == "obscura-aarch64-linux"
    assert _ASSET_MATRIX[("darwin", "arm64")] == "obscura-aarch64-macos"
    assert _ASSET_MATRIX[("darwin", "x86_64")] == "obscura-x86_64-macos"
    assert _ASSET_MATRIX[("windows", "amd64")] == "obscura-x86_64-windows"


def test_asset_for_host_raises_on_unknown(monkeypatch):
    import crawler_cli.obscura_install as oi

    monkeypatch.setattr(oi.platform, "system", lambda: "Plan9")
    monkeypatch.setattr(oi.platform, "machine", lambda: "sparc")
    with pytest.raises(RuntimeError):
        oi._asset_for_host()


def test_find_obscura_prefers_explicit_existing_path(tmp_path, monkeypatch):
    import crawler_cli.obscura_install as oi

    fake = tmp_path / "obscura"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.delenv("OBSCURA_BINARY", raising=False)
    assert oi.find_obscura_binary(str(fake)) == str(fake.resolve())


def test_find_obscura_uses_env_var(tmp_path, monkeypatch):
    import crawler_cli.obscura_install as oi

    fake = tmp_path / "obscura"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("OBSCURA_BINARY", str(fake))
    assert oi.find_obscura_binary(None) == str(fake.resolve())


def test_find_obscura_uses_install_dir(tmp_path, monkeypatch):
    import crawler_cli.obscura_install as oi

    instdir = tmp_path / "inst"
    instdir.mkdir()
    fake = instdir / "obscura"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.delenv("OBSCURA_BINARY", raising=False)
    monkeypatch.setattr(oi, "install_dir", lambda: instdir)
    # Make PATH lookups miss so the install dir is what resolves.
    monkeypatch.setattr(oi.shutil, "which", lambda _name: None)
    assert oi.find_obscura_binary(None) == str(fake)
