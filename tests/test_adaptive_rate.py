"""Ticket 261: adaptive rate calibration and crawl-budget pressure detection.

Every test runs on a simulated clock: ``FakeClock.sleep`` advances time
instead of waiting, so Retry-After pauses and latency curves are exact and
the suite never touches the network.
"""

from __future__ import annotations

import asyncio
import json
from email.utils import format_datetime
from datetime import datetime, timezone

import pytest

from crawler_cli import CrawlConfig, CrawlEngine
from crawler_cli.__main__ import _build_config, _build_parser
from crawler_cli.adaptive_rate import (
    AdaptiveRateController,
    AdaptiveRateRegistry,
    CalibrationSample,
    detect_origin_stack,
    format_pressure_summary,
    parse_retry_after,
    summarize_calibration,
)
from crawler_cli.destination_policy import DestinationRejection
from crawler_cli.models import CrawlJobResult, FetchResponse
from crawler_cli.serialization import serialize_crawl_job, serialize_job_summary_metadata

from test_engine import FakeRobots, FakeStore


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.now += seconds
        await asyncio.sleep(0)


def _controller(clock: FakeClock, **kwargs) -> AdaptiveRateController:
    kwargs.setdefault("max_concurrency", 8)
    return AdaptiveRateController(
        "example.com",
        clock=clock,
        sleep=clock.sleep,
        wall_clock=lambda: 1_000_000.0,
        **kwargs,
    )


def _response(url: str, status: int = 200, *, ttfb: float | None = 0.1, headers: dict[str, str] | None = None):
    html = "<html><body>ok</body></html>"
    merged = {"Content-Type": "text/html; charset=utf-8", **(headers or {})}
    return FetchResponse(
        url=url,
        requested_url=url,
        status=status,
        headers=merged,
        body=html.encode(),
        text=html,
        ttfb_seconds=ttfb,
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_parse_retry_after_delta_seconds_and_http_date() -> None:
    assert parse_retry_after("2") == 2.0
    assert parse_retry_after(" 0 ") == 0.0
    now = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    future = format_datetime(datetime(2026, 9, 28, 12, 0, 30, tzinfo=timezone.utc), usegmt=True)
    past = format_datetime(datetime(2026, 9, 28, 11, 0, 0, tzinfo=timezone.utc), usegmt=True)
    assert parse_retry_after(future, now_epoch=now) == 30.0
    assert parse_retry_after(past, now_epoch=now) == 0.0


@pytest.mark.parametrize("value", [None, "", "-1", "soon", "nan", "inf"])
def test_parse_retry_after_rejects_unusable_values(value) -> None:
    assert parse_retry_after(value) is None


def test_detect_origin_stack_identifies_cdn_and_server() -> None:
    assert detect_origin_stack({"Server": "cloudflare", "CF-RAY": "abc"}) == ["cloudflare"]
    assert detect_origin_stack({"X-Served-By": "cache-lhr-1 Fastly", "Server": "nginx/1.25"}) == ["fastly", "nginx"]
    assert detect_origin_stack({"Server": "AkamaiGHost"}) == ["akamai"]
    assert detect_origin_stack({}) == []


def test_calibration_measures_baseline_and_keeps_configured_concurrency_for_fast_origin() -> None:
    samples = [
        CalibrationSample(url="https://example.com/", status=200, ttfb_seconds=t, headers={"Server": "cloudflare"})
        for t in (0.05, 0.07, 0.06, 0.08, 0.30)
    ]
    result = summarize_calibration("example.com", samples, max_concurrency=4)
    assert result.ttfb_median_seconds == pytest.approx(0.07)
    assert result.ttfb_p95_seconds == pytest.approx(0.256)
    assert result.origin_stack == ["cloudflare"]
    assert result.recommended_concurrency == 4
    assert result.recommended_min_interval_seconds == 0.0


def test_calibration_recommends_lower_concurrency_for_slow_origin_never_higher() -> None:
    slow = [CalibrationSample(url="u", status=200, ttfb_seconds=1.5) for _ in range(5)]
    assert summarize_calibration("h", slow, max_concurrency=10).recommended_concurrency == 2
    # A cap below the heuristic is never raised.
    assert summarize_calibration("h", slow, max_concurrency=1).recommended_concurrency == 1


def test_calibration_honours_rate_limit_headers_and_retry_after() -> None:
    limited = [
        CalibrationSample(
            url="u",
            status=200,
            ttfb_seconds=0.05,
            headers={"RateLimit-Limit": "100", "RateLimit-Remaining": "5", "RateLimit-Reset": "10"},
        )
    ]
    result = summarize_calibration("h", limited, max_concurrency=8)
    assert result.rate_limit_headers["ratelimit-remaining"] == "5"
    assert result.recommended_concurrency == 1
    assert result.recommended_min_interval_seconds == 2.0
    assert "rate_limit_remaining_low" in result.reasons

    throttled = [CalibrationSample(url="u", status=429, ttfb_seconds=0.01, headers={"Retry-After": "7"})]
    result = summarize_calibration("h", throttled, max_concurrency=8)
    assert result.recommended_concurrency == 1
    assert result.recommended_min_interval_seconds == 7.0


# ---------------------------------------------------------------------------
# Controller on a simulated clock
# ---------------------------------------------------------------------------


def test_429_with_retry_after_pauses_and_halves_concurrency() -> None:
    clock = FakeClock()
    controller = _controller(clock)
    controller.record_response(429, 0.01, {"Retry-After": "2"})
    assert controller.pause_remaining() == 2.0
    assert controller.concurrency_limit == 4
    assert controller.throttled_seconds == 2.0
    assert controller.retry_after_count == 1

    # An overlapping 429 only adds the non-overlapping part of its pause.
    clock.now = 1.0
    controller.record_response(429, 0.01, {"Retry-After": "2"})
    assert controller.throttled_seconds == 3.0
    assert controller.concurrency_limit == 2


def test_backoff_without_retry_after_is_exponential_and_clamped() -> None:
    clock = FakeClock()
    controller = _controller(clock, max_retry_after_seconds=3.0)
    pauses = []
    for _ in range(4):
        controller.record_response(503, None, {})
        pauses.append(controller.pause_remaining())
        clock.now += controller.pause_remaining()
    assert pauses == [1.0, 2.0, 3.0, 3.0]
    assert controller.unavailable_count == 4


def test_retry_after_is_clamped_to_safe_bound() -> None:
    clock = FakeClock()
    controller = _controller(clock, max_retry_after_seconds=60.0)
    controller.record_response(429, None, {"Retry-After": "3600"})
    assert controller.pause_remaining() == 60.0
    assert controller.retry_after_max_seconds == 3600.0


def test_rising_latency_curve_throttles_before_any_server_error() -> None:
    clock = FakeClock()
    controller = _controller(clock)
    controller.apply_calibration(
        summarize_calibration(
            "example.com",
            [CalibrationSample(url="u", status=200, ttfb_seconds=0.1) for _ in range(5)],
            max_concurrency=8,
        )
    )
    # Healthy, then the origin slows down linearly: 0.1s -> 0.6s.
    curve = [0.1] * 10 + [0.1 + 0.025 * step for step in range(1, 21)]
    first_throttle_at = None
    for index, ttfb in enumerate(curve):
        controller.record_response(200, ttfb, {})
        if first_throttle_at is None and controller.throttle_events:
            first_throttle_at = index
    assert first_throttle_at is not None
    # 2.5x of a 0.1s baseline is 0.25s; the rolling median crosses it well
    # before the curve peaks and without a single 5xx.
    assert curve[first_throttle_at] < 0.6
    assert controller.unavailable_count == 0
    assert controller.concurrency_limit < 8
    snapshot = controller.snapshot()
    assert snapshot["baseline_source"] == "calibration"
    assert snapshot["ttfb_degradation_ratio"] > 2.5
    assert any(event["reason"] == "ttfb_degraded" for event in snapshot["history"])
    assert snapshot["ttfb_curve"], "degradation curve must be reported"
    assert snapshot["recommended_concurrency"] == snapshot["min_concurrency_reached"]


def test_small_loopback_baseline_is_not_throttled_by_jitter() -> None:
    clock = FakeClock()
    controller = _controller(clock)
    for ttfb in [0.002] * 5 + [0.008] * 20:
        controller.record_response(200, ttfb, {})
    assert controller.baseline_source == "runtime"
    assert controller.throttle_events == 0


def test_recovery_after_sustained_healthy_window_never_exceeds_ceiling() -> None:
    clock = FakeClock()
    controller = _controller(clock, max_concurrency=4, recovery_window=50)
    controller.record_response(429, None, {"Retry-After": "1"})
    assert controller.concurrency_limit == 2
    for _ in range(49):
        controller.record_response(200, 0.1, {})
    assert controller.concurrency_limit == 2
    controller.record_response(200, 0.1, {})
    assert controller.concurrency_limit == 3
    for _ in range(1000):
        controller.record_response(200, 0.1, {})
    assert controller.concurrency_limit == 4
    assert controller.recovery_events == 2


def test_throttle_at_single_worker_adds_spacing_then_recovers_it_first() -> None:
    clock = FakeClock()
    controller = _controller(clock, max_concurrency=1, recovery_window=5)
    controller.record_response(429, None, {})
    assert controller.concurrency_limit == 1
    assert controller.min_interval_seconds == 0.5
    for _ in range(5):
        controller.record_response(200, 0.1, {})
    assert controller.min_interval_seconds == 0.25
    for _ in range(15):
        controller.record_response(200, 0.1, {})
    assert controller.min_interval_seconds == 0.0
    assert controller.concurrency_limit == 1


@pytest.mark.asyncio
async def test_slot_waits_out_pause_and_enforces_narrowed_limit() -> None:
    clock = FakeClock()
    controller = _controller(clock, max_concurrency=4)
    controller.record_response(429, None, {"Retry-After": "2"})  # limit 4 -> 2, pause 2s

    in_flight = 0
    peak = 0
    release = asyncio.Event()

    async def worker() -> None:
        nonlocal in_flight, peak
        async with controller.slot():
            in_flight += 1
            peak = max(peak, in_flight)
            await release.wait()
            in_flight -= 1

    tasks = [asyncio.create_task(worker()) for _ in range(4)]
    for _ in range(10):
        await asyncio.sleep(0)
    assert clock.sleeps and clock.sleeps[0] == 2.0
    assert peak == 2
    release.set()
    await asyncio.gather(*tasks)
    assert peak == 2


def test_format_pressure_summary_is_none_when_disabled() -> None:
    assert format_pressure_summary(None) is None
    registry = AdaptiveRateRegistry(max_concurrency=4, clock=FakeClock())
    registry.for_host("example.com").record_response(429, 0.05, {"Retry-After": "2"})
    line = format_pressure_summary(registry.summary())
    assert line is not None
    assert "PRESSURE DETECTED" in line
    assert "1x429" in line


# ---------------------------------------------------------------------------
# Engine integration (mock origins, no network)
# ---------------------------------------------------------------------------


class RateLimitedOrigin:
    """Answers the first request for each listed URL with 429 + Retry-After: 2."""

    def __init__(self, limited: set[str], *, ttfb: float = 0.05, headers: dict[str, str] | None = None) -> None:
        self.limited = set(limited)
        self.ttfb = ttfb
        self.headers = headers or {}
        self.requests: list[str] = []

    async def fetch(self, url: str) -> FetchResponse:
        self.requests.append(url)
        if url in self.limited:
            self.limited.discard(url)
            return _response(url, 429, ttfb=0.01, headers={"Retry-After": "2", **self.headers})
        return _response(url, ttfb=self.ttfb, headers=self.headers)


def _adaptive_engine(config: CrawlConfig, clock: FakeClock, **kwargs) -> CrawlEngine:
    engine = CrawlEngine(config, **kwargs)
    assert engine._adaptive is not None
    engine._adaptive = AdaptiveRateRegistry(
        max_concurrency=engine._adaptive.max_concurrency,
        clock=clock,
        sleep=clock.sleep,
        degradation_factor=config.adaptive_ttfb_degradation_factor,
        recovery_window=config.adaptive_recovery_window,
        max_retry_after_seconds=config.adaptive_max_retry_after_seconds,
    )
    return engine


def test_adaptive_rate_is_off_by_default() -> None:
    engine = CrawlEngine(CrawlConfig())
    assert engine._adaptive is None
    job = CrawlJobResult(mode="list", seed_urls=[], results=[])
    assert "crawl_budget_pressure" not in serialize_crawl_job(job)
    assert "crawl_budget_pressure" not in serialize_job_summary_metadata(job)


def test_adaptive_ceiling_is_the_configured_per_host_cap() -> None:
    engine = CrawlEngine(CrawlConfig(adaptive_rate=True, max_concurrency=10, per_host_concurrency=2))
    assert engine._adaptive is not None
    assert engine._adaptive.for_host("example.com").configured_concurrency == 2
    engine = CrawlEngine(CrawlConfig(adaptive_rate=True, max_concurrency=3, per_host_concurrency=0))
    assert engine._adaptive is not None
    assert engine._adaptive.max_concurrency == 3


@pytest.mark.asyncio
async def test_list_crawl_429_retry_after_pauses_halves_and_drops_nothing() -> None:
    clock = FakeClock()
    urls = [f"https://example.com/p{idx}" for idx in range(6)]
    config = CrawlConfig(
        adaptive_rate=True,
        adaptive_calibration_requests=0,
        max_concurrency=4,
        per_host_concurrency=4,
        rate_limit_per_second=0,
    )
    engine = _adaptive_engine(config, clock)
    backend = RateLimitedOrigin({urls[0]})
    engine.backend = backend
    engine._robots = FakeRobots()

    job = await engine.crawl_list(urls)

    assert [result.requested_url for result in job.results] == urls
    assert all(result.status == 200 for result in job.results)
    assert backend.requests.count(urls[0]) == 2
    assert 2.0 in clock.sleeps
    assert job.retry_attempts == 1
    pressure = job.crawl_budget_pressure
    assert pressure is not None
    host = pressure["hosts"]["example.com"]
    assert host["rate_limited_429_count"] == 1
    assert host["retry_after_count"] == 1
    assert host["throttled_seconds"] == 2.0
    assert host["min_concurrency_reached"] == 2
    assert host["configured_concurrency"] == 4
    assert pressure["pressure_detected"] is True


@pytest.mark.asyncio
async def test_open_crawl_reports_pressure_in_summary_line(tmp_path) -> None:
    clock = FakeClock()
    store = FakeStore()
    config = CrawlConfig(
        adaptive_rate=True,
        adaptive_calibration_requests=2,
        max_concurrency=2,
        default_open_crawl_limit=5,
        frontier_max_retries=2,
        rate_limit_per_second=0,
    )
    engine = _adaptive_engine(config, clock, store=store)
    seed = "https://example.com/start"
    backend = RateLimitedOrigin({seed}, headers={"Server": "nginx"})
    engine.backend = backend
    engine._robots = FakeRobots()
    out = tmp_path / "crawl.jsonl"

    job = await engine.crawl_open([seed], max_urls=5, save_to=str(out))

    # Two calibration probes (root, seed) precede the crawl; the seed probe
    # hit the 429 and stopped calibration early.
    assert backend.requests[:2] == ["https://example.com/", seed]
    assert store.frontier[seed]["status"] == "done"
    assert any(result.requested_url == seed and result.status == 200 for result in job.results)
    pressure = job.crawl_budget_pressure
    assert pressure is not None
    host = pressure["hosts"]["example.com"]
    assert host["calibration"]["requests"] == 2
    assert host["calibration"]["origin_stack"] == ["nginx"]
    assert host["calibration"]["recommended_concurrency"] == 1
    assert host["rate_limited_429_count"] == 1
    assert 2.0 in clock.sleeps
    summary = json.loads(out.read_text(encoding="utf-8").splitlines()[-1])
    assert summary["__type"] == "summary"
    assert summary["crawl_budget_pressure"]["rate_limited_429_count"] == 1


@pytest.mark.asyncio
async def test_calibration_sets_initial_concurrency_from_baseline() -> None:
    clock = FakeClock()
    config = CrawlConfig(
        adaptive_rate=True,
        adaptive_calibration_requests=4,
        max_concurrency=8,
        per_host_concurrency=8,
        rate_limit_per_second=0,
    )
    engine = _adaptive_engine(config, clock)
    backend = RateLimitedOrigin(set(), ttfb=1.5, headers={"CF-RAY": "1"})
    engine.backend = backend
    engine._robots = FakeRobots()

    await engine._calibrate_adaptive_rate(["https://example.com/a"])

    assert backend.requests == [
        "https://example.com/",
        "https://example.com/a",
        "https://example.com/",
        "https://example.com/a",
    ]
    controller = engine._adaptive.for_host("example.com")
    assert controller.baseline_ttfb == 1.5
    assert controller.concurrency_limit == 2
    assert controller.calibration is not None
    assert controller.calibration.origin_stack == ["cloudflare"]
    # Idempotent per origin.
    await engine._calibrate_adaptive_rate(["https://example.com/b"])
    assert len(backend.requests) == 4


@pytest.mark.asyncio
async def test_calibration_respects_robots_disallow() -> None:
    clock = FakeClock()
    config = CrawlConfig(adaptive_rate=True, adaptive_calibration_requests=3, rate_limit_per_second=0)
    engine = _adaptive_engine(config, clock)
    backend = RateLimitedOrigin(set())
    engine.backend = backend
    engine._robots = FakeRobots(disallowed={"https://example.com/"})

    await engine._calibrate_adaptive_rate(["https://example.com/ok"])

    assert "https://example.com/" not in backend.requests
    assert backend.requests == ["https://example.com/ok"] * 3


@pytest.mark.asyncio
async def test_calibration_stops_on_destination_guard_denial() -> None:
    clock = FakeClock()
    config = CrawlConfig(adaptive_rate=True, adaptive_calibration_requests=5, rate_limit_per_second=0)
    engine = _adaptive_engine(config, clock)

    class GuardedBackend:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch(self, url: str) -> FetchResponse:
            self.calls += 1
            raise DestinationRejection("private_address", "10.0.0.1")

    backend = GuardedBackend()
    engine.backend = backend
    engine._robots = FakeRobots()

    await engine._calibrate_adaptive_rate(["https://example.com/"])

    assert backend.calls == 1
    calibration = engine._adaptive.for_host("example.com").calibration
    assert calibration is not None
    assert calibration.errors == ["DestinationRejection"]
    assert calibration.ttfb_median_seconds is None


@pytest.mark.asyncio
async def test_high_latency_origin_triggers_throttle_during_crawl() -> None:
    clock = FakeClock()
    urls = [f"https://example.com/p{idx}" for idx in range(12)]
    config = CrawlConfig(
        adaptive_rate=True,
        adaptive_calibration_requests=5,
        max_concurrency=4,
        per_host_concurrency=4,
        rate_limit_per_second=0,
    )
    engine = _adaptive_engine(config, clock)

    class DegradingOrigin:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch(self, url: str) -> FetchResponse:
            self.calls += 1
            # Calibration sees 0.1s; the crawl then sees the origin struggling.
            ttfb = 0.1 if self.calls <= 5 else 0.6
            return _response(url, ttfb=ttfb)

    engine.backend = DegradingOrigin()
    engine._robots = FakeRobots()

    job = await engine.crawl_list(urls)

    assert len(job.results) == len(urls)
    assert all(result.status == 200 for result in job.results)
    host = job.crawl_budget_pressure["hosts"]["example.com"]
    assert host["baseline_ttfb_seconds"] == 0.1
    assert host["throttle_events"] >= 1
    assert host["final_concurrency"] < 4
    assert host["rate_limited_429_count"] == 0
    assert host["unavailable_503_count"] == 0


def test_cli_flags_build_adaptive_config() -> None:
    args = _build_parser().parse_args(
        [
            "crawl",
            "https://example.com",
            "--adaptive-rate",
            "--adaptive-calibration-requests",
            "3",
            "--adaptive-ttfb-factor",
            "3",
            "--adaptive-max-retry-after",
            "30",
        ]
    )
    config = _build_config(args)
    assert config.adaptive_rate is True
    assert config.adaptive_calibration_requests == 3
    assert config.adaptive_ttfb_degradation_factor == 3.0
    assert config.adaptive_max_retry_after_seconds == 30.0
    assert _build_config(_build_parser().parse_args(["crawl", "https://example.com"])).adaptive_rate is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"adaptive_calibration_requests": 21},
        {"adaptive_calibration_requests": -1},
        {"adaptive_ttfb_degradation_factor": 1.0},
        {"adaptive_recovery_window": 0},
        {"adaptive_max_retry_after_seconds": 0.0},
    ],
)
def test_config_rejects_invalid_adaptive_settings(kwargs) -> None:
    with pytest.raises(ValueError):
        CrawlConfig(**kwargs)


@pytest.mark.asyncio
async def test_loopback_origin_429_retry_after_through_real_http_backend() -> None:
    """A real aiohttp origin on 127.0.0.1: 429 + Retry-After: 2, then 200."""
    from aiohttp import web

    hits: dict[str, int] = {}

    async def page(request: web.Request) -> web.Response:
        hits[request.path] = hits.get(request.path, 0) + 1
        if request.path == "/a" and hits[request.path] == 1:
            return web.Response(status=429, headers={"Retry-After": "2"}, text="slow down")
        return web.Response(text="<html><body>ok</body></html>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/{name}", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    base = f"http://127.0.0.1:{port}"
    clock = FakeClock()
    engine = _adaptive_engine(
        CrawlConfig(
            adaptive_rate=True,
            adaptive_calibration_requests=0,
            backend="aiohttp",
            respect_robots_txt=False,
            rate_limit_per_second=0,
            max_concurrency=2,
            per_host_concurrency=2,
            # Loopback fixture server; the ticket-149 guard has its own suite.
            destination_guard="off",
        ),
        clock,
    )
    urls = [f"{base}/a", f"{base}/b", f"{base}/c"]
    try:
        job = await engine.crawl_list(urls)
    finally:
        await engine.close()
        await runner.cleanup()

    assert [result.status for result in job.results] == [200, 200, 200]
    assert hits["/a"] == 2
    assert 2.0 in clock.sleeps
    host = job.crawl_budget_pressure["hosts"][f"127.0.0.1:{port}"]
    assert host["rate_limited_429_count"] == 1
    assert host["min_concurrency_reached"] == 1
    assert host["throttled_seconds"] == 2.0
