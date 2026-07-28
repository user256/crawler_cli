from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

import pytest

from crawler_cli import portal_adapter as adapter

PUBLIC_IP = "93.184.216.34"
JOB_ID = "a" * 32
ATTEMPT_ID = "b" * 32
RUN_ID = "c" * 32


def dispatch_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": adapter.DISPATCH_SCHEMA,
        "crawler_version": adapter.CRAWLER_VERSION,
        "crawler_release": adapter.CRAWLER_RELEASE,
        "connection_guard_protocol": adapter.GUARD_PROTOCOL,
        "job_id": JOB_ID,
        "attempt_id": ATTEMPT_ID,
        "run_id": RUN_ID,
        "lease_fence": 1,
        "target": {
            "url": "https://example.test/start",
            "origin": "https://example.test:443",
            "initial_pinned_ip": PUBLIC_IP,
            "deployment_profile": "saas",
            "allow_private_network": False,
            "credentials_origin_only": True,
        },
        "budgets": {
            "max_pages": 2,
            "max_requests": 10,
            "max_bytes": 1_048_576,
            "duration_seconds": 60,
            "javascript": False,
            "embeddings": False,
        },
        "wall_clock_timeout_seconds": 60,
        "command": ["crawler-cli", "crawl", "https://example.test/start"],
        "result_schema_version": adapter.RESULT_SCHEMA,
    }
    payload.update(overrides)
    return payload


def policy() -> adapter.TargetPolicy:
    return adapter.TargetPolicy("saas", False, "https://example.test:443")


@pytest.mark.asyncio
async def test_redirect_to_private_is_rejected_before_second_connection() -> None:
    resolutions = {
        "example.test": [PUBLIC_IP],
        "metadata.test": ["169.254.169.254"],
    }
    connected: list[str] = []

    async def resolve(host: str, _port: int) -> list[str]:
        return resolutions[host]

    async def request(
        target: adapter.ValidatedTarget,
        _headers: Mapping[str, str],
        _timeout: float,
        _max_bytes: int,
    ) -> tuple[int, Mapping[str, str], bytes]:
        connected.append(target.pinned_ip)
        return 302, {"Location": "http://metadata.test/latest/"}, b""

    client = adapter.SafeHttpClient(policy(), resolve_host=resolve, request_pinned=request)
    with pytest.raises(adapter.UrlPolicyError, match="denied"):
        await client.fetch("https://example.test/start", 5)
    assert connected == [PUBLIC_IP]


@pytest.mark.asyncio
async def test_every_connection_reresolves_and_pins_the_validated_answer() -> None:
    answers = iter([[PUBLIC_IP], ["10.0.0.8"]])
    connected: list[str] = []

    async def resolve(_host: str, _port: int) -> list[str]:
        return next(answers)

    async def request(
        target: adapter.ValidatedTarget,
        _headers: Mapping[str, str],
        _timeout: float,
        _max_bytes: int,
    ) -> tuple[int, Mapping[str, str], bytes]:
        connected.append(target.pinned_ip)
        if len(connected) == 1:
            return 302, {"Location": "/next"}, b""
        raise AssertionError("denied rebinding answer must never reach the transport")

    client = adapter.SafeHttpClient(policy(), resolve_host=resolve, request_pinned=request)
    with pytest.raises(adapter.UrlPolicyError, match="denied"):
        await client.fetch("https://example.test/start", 5)
    assert connected == [PUBLIC_IP]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.pop("schema_version"),
        lambda data: data.update(schema_version="migration-manager/crawl-dispatch/2"),
        lambda data: data.update(job_id="not-an-id"),
        lambda data: data["target"].update(url="file:///etc/passwd"),
        lambda data: data["budgets"].update(javascript=True),
        lambda data: data["budgets"].update(embeddings=True),
        lambda data: data["budgets"].update(max_requests=0),
        lambda data: data["budgets"].update(max_bytes=100),
        lambda data: data["target"].update(credentials_origin_only=False),
        lambda data: data["target"].update(initial_pinned_ip="169.254.169.254"),
        lambda data: data.update(lease_fence=0),
        lambda data: data["command"].extend(["--auth-token", "inline-secret"]),
        lambda data: data["command"].append("--js"),
        lambda data: data.update(operation="live_compare"),
    ],
)
def test_malformed_or_unsupported_dispatch_fails_closed(mutation: Any) -> None:
    payload = dispatch_payload()
    mutation(payload)
    with pytest.raises((adapter.DispatchError, adapter.UrlPolicyError)):
        adapter.parse_dispatch(payload)


def test_capability_probe_is_truthful_and_complete(capsys: pytest.CaptureFixture[str]) -> None:
    assert adapter.main(["--capabilities"]) == 0
    capabilities = json.loads(capsys.readouterr().out)
    assert capabilities["crawler_release"] == "crawler-cli@v0.2.1"
    assert capabilities["generated_at"].endswith("Z")
    assert capabilities["connection_guard_protocol"] == "portal-url-policy/1"
    assert capabilities["guarded_paths"] == {
        "http_redirect": True,
        "sitemap": True,
        "browser_navigation": True,
        "browser_subresource": True,
        "live_compare": True,
    }
    assert capabilities["schema_version"] == 1
    assert capabilities["capabilities"] == {
        "crawl_http": True,
        "crawl_browser": False,
        "crawl_embeddings": False,
    }
    assert capabilities["path_enforcement"]["browser_subresource"].startswith("fail-closed")


def test_result_identity_and_schema_are_exact() -> None:
    dispatch = adapter.parse_dispatch(dispatch_payload())
    result = adapter.build_result(
        dispatch,
        [
            {
                "observation_key": "d" * 64,
                "outcome_state": "observed",
                "requested_url": dispatch.target_url,
                "final_url": dispatch.target_url,
                "http_status": 200,
                "content_type": "text/html",
                "fetch_backend": "portal-aiohttp-pinned",
                "allowed_by_robots": True,
                "skip_reason": None,
                "content_sha256": "e" * 64,
                "content_hash_version": "raw-bytes/1",
                "semantic_hash": None,
                "semantic_hash_version": None,
                "preprocessing_version": None,
                "redirect_chain": [],
                "extracted_fields": {},
                "artifacts": [],
            }
        ],
        "2026-07-28T01:00:00Z",
        "2026-07-28T01:00:01Z",
    )
    assert result["schema_version"] == "migration-manager/run-result/1"
    assert result["run_id"] == RUN_ID
    assert result["producer"] == {
        "kind": "migration_manager_crawl",
        "job_id": JOB_ID,
        "attempt_id": ATTEMPT_ID,
    }
    assert result["terminal"]["status"] == "complete"
    assert result["terminal"]["artifact_availability"] == "none"


def test_config_fd_never_places_secret_in_argv_stdout_or_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "SUPER_SECRET_CANARY_93517"
    payload = dispatch_payload(
        command=[
            "crawler-cli",
            "crawl",
            "https://example.test/start",
            "--auth-type",
            "bearer",
            "--auth-token-env",
            "MM_CRAWL_AUTH_TOKEN",
        ]
    )
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, json.dumps(payload).encode())
    finally:
        os.close(write_fd)
    monkeypatch.setenv("MM_CRAWL_AUTH_TOKEN", secret)

    async def fake_run(dispatch: adapter.Dispatch) -> dict[str, Any]:
        assert dispatch.bearer_env == "MM_CRAWL_AUTH_TOKEN"
        assert secret not in repr(dispatch)
        return adapter.build_result(
            dispatch,
            [],
            "2026-07-28T01:00:00Z",
            "2026-07-28T01:00:01Z",
        )

    monkeypatch.setattr(adapter, "run_dispatch", fake_run)
    try:
        assert adapter.main(["--config-fd", str(read_fd)]) == 0
    finally:
        os.close(read_fd)
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    envelope = json.loads(captured.out)
    assert envelope["terminal"]["status"] == "complete"
    assert captured.out.count("\n") == 1


@pytest.mark.asyncio
async def test_missing_declared_secret_returns_one_contract_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = dispatch_payload(
        command=[
            "crawler-cli",
            "crawl",
            "https://example.test/start",
            "--auth-token-env",
            "MM_CRAWL_AUTH_TOKEN",
        ]
    )
    monkeypatch.delenv("MM_CRAWL_AUTH_TOKEN", raising=False)
    dispatch = adapter.parse_dispatch(payload)
    result = await adapter.run_dispatch(dispatch)
    assert result["terminal"]["status"] == "partial"
    assert result["terminal"]["error_count"] == 1
    assert result["observations"][0]["skip_reason"] == "credential_unavailable"


@pytest.mark.asyncio
async def test_private_network_requires_explicit_appliance_policy() -> None:
    async def resolve(_host: str, _port: int) -> list[str]:
        return ["192.168.10.20"]

    with pytest.raises(adapter.UrlPolicyError):
        await adapter.validate_and_pin("http://internal.example/", policy(), resolve)
    appliance = adapter.TargetPolicy("appliance", True, "http://internal.example:80")
    validated = await adapter.validate_and_pin("http://internal.example/", appliance, resolve)
    assert validated.pinned_ip == "192.168.10.20"


@pytest.mark.asyncio
async def test_mixed_dns_answer_set_fails_closed() -> None:
    async def resolve(_host: str, _port: int) -> list[str]:
        return [PUBLIC_IP, "10.0.0.8"]

    with pytest.raises(adapter.UrlPolicyError, match="denied"):
        await adapter.validate_and_pin("https://example.test/", policy(), resolve)


@pytest.mark.asyncio
async def test_total_request_budget_includes_redirect_hops() -> None:
    connected: list[str] = []

    async def resolve(_host: str, _port: int) -> list[str]:
        return [PUBLIC_IP]

    async def request(
        target: adapter.ValidatedTarget,
        _headers: Mapping[str, str],
        _timeout: float,
        _max_bytes: int,
    ) -> tuple[int, Mapping[str, str], bytes]:
        connected.append(target.url)
        return 302, {"Location": "/next"}, b"redirect"

    client = adapter.SafeHttpClient(
        policy(),
        resolve_host=resolve,
        request_pinned=request,
        max_requests=1,
        max_bytes=1024,
    )
    with pytest.raises(adapter.FetchError, match="request budget"):
        await client.fetch("https://example.test/start", 5)
    assert connected == ["https://example.test/start"]
    assert client.requests_used == 1
    assert client.bytes_used == len(b"redirect")


@pytest.mark.asyncio
async def test_total_byte_budget_is_enforced_across_connections() -> None:
    calls = 0

    async def resolve(_host: str, _port: int) -> list[str]:
        return [PUBLIC_IP]

    async def request(
        _target: adapter.ValidatedTarget,
        _headers: Mapping[str, str],
        _timeout: float,
        max_bytes: int,
    ) -> tuple[int, Mapping[str, str], bytes]:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert max_bytes == 10
            return 302, {"Location": "/next"}, b"123456"
        assert max_bytes == 4
        return 200, {}, b"12345"

    client = adapter.SafeHttpClient(
        policy(),
        resolve_host=resolve,
        request_pinned=request,
        max_requests=3,
        max_bytes=10,
    )
    with pytest.raises(adapter.FetchError, match="byte budget"):
        await client.fetch("https://example.test/start", 5)
    assert calls == 2
    assert client.bytes_used == 6


@pytest.mark.asyncio
async def test_exhausted_request_budget_with_frontier_is_partial_not_false_success() -> None:
    payload = dispatch_payload()
    payload["budgets"].update(max_requests=2, discover_sitemaps=False)
    dispatch = adapter.parse_dispatch(payload)

    async def resolve(_host: str, _port: int) -> list[str]:
        return [PUBLIC_IP]

    async def request(
        target: adapter.ValidatedTarget,
        _headers: Mapping[str, str],
        _timeout: float,
        _max_bytes: int,
    ) -> tuple[int, Mapping[str, str], bytes]:
        if target.url.endswith("/robots.txt"):
            return 404, {"Content-Type": "text/plain"}, b""
        return (
            200,
            {"Content-Type": "text/html"},
            b'<html><a href="/remaining">remaining</a></html>',
        )

    client = adapter.SafeHttpClient(
        dispatch.target_policy,
        resolve_host=resolve,
        request_pinned=request,
        max_requests=dispatch.max_requests,
        max_bytes=dispatch.max_bytes,
    )
    crawler = adapter.PortalCrawler(dispatch, client)
    observations = await crawler.crawl()
    assert len(observations) == 1
    assert observations[0]["outcome_state"] == "observed"
    assert crawler.incomplete_due_to_transport_budget is True
    result = adapter.build_result(
        dispatch,
        observations,
        "2026-07-28T01:00:00Z",
        "2026-07-28T01:00:01Z",
        forced_partial=crawler.incomplete_due_to_transport_budget,
    )
    assert result["terminal"]["status"] == "partial"
    assert result["terminal"]["incomplete_count"] == 0


def test_config_fd_rejects_invalid_json_without_echoing_input(
    capsys: pytest.CaptureFixture[str],
) -> None:
    canary = "SECRET_MALFORMED_DISPATCH"
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, (canary + "{").encode())
    finally:
        os.close(write_fd)
    try:
        assert adapter.main(["--config-fd", str(read_fd)]) == 2
    finally:
        os.close(read_fd)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert canary not in captured.err
