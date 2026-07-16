"""Ticket 093: CLI / library numeric configuration validation."""

from __future__ import annotations

import math

import pytest

from crawler_cli.__main__ import (
    _build_config,
    _build_parser,
    _run_crawl,
    _run_intent_overlap,
    _validate_intent_overlap_numeric_args,
)
from crawler_cli.config import CrawlConfig
from crawler_cli.validators import (
    non_negative_float,
    non_negative_int,
    percentage,
    positive_float,
    positive_int,
    probability,
)


def _parse(argv: list[str]):
    return _build_parser().parse_args(argv)


def _parse_crawl(*flags: str):
    return _parse(["crawl", "https://example.com", *flags])


# ---------------------------------------------------------------------------
# argparse type helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn,ok,bad",
    [
        (positive_int, "3", "0"),
        (positive_int, "1", "-1"),
        (non_negative_int, "0", "-1"),
        (positive_float, "0.1", "0"),
        (positive_float, "1.5", "-0.1"),
        (non_negative_float, "0", "-0.01"),
        (percentage, "0", "-1"),
        (percentage, "100", "100.1"),
        (probability, "0", "-0.01"),
        (probability, "1", "1.01"),
    ],
)
def test_argparse_types_accept_and_reject(fn, ok, bad):
    assert fn(ok) == type(fn(ok))(ok)  # noqa: PLC2801 - round-trip type
    with pytest.raises(Exception):
        fn(bad)


@pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-inf", "+inf"])
@pytest.mark.parametrize("fn", [positive_float, non_negative_float, percentage, probability])
def test_argparse_float_types_reject_nan_inf(fn, raw):
    with pytest.raises(Exception):
        fn(raw)


# ---------------------------------------------------------------------------
# CLI boundary: negative / zero / nonsense rejected at parse time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flags",
    [
        ["--max-workers", "-2"],
        ["--concurrency", "0"],
        ["--timeout", "-1"],
        ["--timeout", "0"],
        ["--timeout", "nan"],
        ["--timeout", "inf"],
        ["--max-response-bytes", "0"],
        ["--max-response-bytes", "-10"],
        ["--max-pages", "-1"],
        ["--per-host-concurrency", "-3"],
        ["--refresh-days", "-1"],
        ["--memory-high-watermark", "101"],
        ["--memory-high-watermark", "nan"],
        ["--memory-recovery-watermark", "-5"],
        ["--circuit-breaker-threshold", "0"],
        ["--circuit-breaker-recovery-seconds", "-1"],
        ["--proxy-gateway-max-retries", "-1"],
        ["--proxy-cooldown", "-1"],
    ],
)
def test_cli_rejects_invalid_numeric_flags(flags):
    with pytest.raises(SystemExit) as exc:
        _parse_crawl(*flags)
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "flags",
    [
        ["--max-workers", "1"],
        ["--concurrency", "2"],
        ["--max-pages", "0"],
        ["--per-host-concurrency", "0"],
        ["--refresh-days", "0"],
        ["--max-requests-per-context", "0"],
        ["--wait-for-network-idle", "0"],
        ["--timeout", "0.001"],
        ["--memory-high-watermark", "100"],
        ["--memory-recovery-watermark", "0"],
    ],
)
def test_cli_accepts_boundary_and_sentinel_values(flags):
    # recovery=0 requires high > 0; when only recovery is set, defaults keep high=85.
    args = _parse_crawl(*flags)
    if "--memory-recovery-watermark" in flags and "--memory-high-watermark" not in flags:
        _build_config(args)  # defaults: recovery 0 < high 85
    elif "--memory-high-watermark" in flags and "--memory-recovery-watermark" not in flags:
        # high=100 with default recovery 70 is fine
        _build_config(args)
    else:
        _build_config(args)


def test_cli_rejects_memory_recovery_not_below_high():
    args = _parse_crawl("--memory-high-watermark", "70", "--memory-recovery-watermark", "70")
    with pytest.raises(ValueError, match="must be below"):
        _build_config(args)


def test_cli_rejects_memory_recovery_above_high():
    args = _parse_crawl("--memory-high-watermark", "50", "--memory-recovery-watermark", "80")
    with pytest.raises(ValueError, match="must be below"):
        _build_config(args)


def test_negative_max_workers_never_reaches_engine(monkeypatch):
    """Reproduction from ticket 093: --max-workers=-2 must exit 2 at argparse."""
    created = []

    class Boom:
        def __init__(self, *a, **k):
            created.append(True)
            raise AssertionError("CrawlEngine must not be constructed")

    monkeypatch.setattr("crawler_cli.__main__.CrawlEngine", Boom)
    with pytest.raises(SystemExit) as exc:
        _parse_crawl("--max-workers", "-2")
    assert exc.value.code == 2
    assert created == []


@pytest.mark.asyncio
async def test_run_crawl_returns_2_for_disagreeing_aliases(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "crawler_cli.__main__.CrawlEngine",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("engine")),
    )
    args = _parse_crawl("--max-workers", "3", "--concurrency", "9", "--output-dir", str(tmp_path / "out"))
    code = await _run_crawl(args)
    assert code == 2
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------------------
# CrawlConfig library validation
# ---------------------------------------------------------------------------


def test_crawl_config_defaults_validate():
    cfg = CrawlConfig()
    cfg.validate()  # idempotent


def test_crawl_config_rejects_negative_concurrency():
    with pytest.raises(ValueError, match="max_concurrency"):
        CrawlConfig(max_concurrency=-2)


def test_crawl_config_rejects_zero_concurrency():
    with pytest.raises(ValueError, match="max_concurrency"):
        CrawlConfig(max_concurrency=0)


def test_crawl_config_rejects_non_positive_response_cap():
    with pytest.raises(ValueError, match="max_response_bytes"):
        CrawlConfig(max_response_bytes=0)


def test_crawl_config_rejects_negative_timeout():
    with pytest.raises(ValueError, match="timeout_seconds"):
        CrawlConfig(timeout_seconds=-1.0)


def test_crawl_config_rejects_nan_timeout():
    with pytest.raises(ValueError, match="finite"):
        CrawlConfig(timeout_seconds=math.nan)


def test_crawl_config_rejects_inf_timeout():
    with pytest.raises(ValueError, match="finite"):
        CrawlConfig(timeout_seconds=math.inf)


def test_crawl_config_allows_zero_sentinels():
    cfg = CrawlConfig(
        max_pages=0,
        refresh_days=0,
        per_host_concurrency=0,
        max_requests_per_context=0,
        playwright_network_idle_timeout_seconds=0.0,
        rate_limit_per_second=0.0,
        frontier_max_retries=0,
        frontier_retry_base_delay_seconds=0.0,
    )
    assert cfg.max_pages == 0
    assert cfg.per_host_concurrency == 0


def test_crawl_config_rejects_memory_recovery_not_below_high():
    with pytest.raises(ValueError, match="memory_recovery_watermark_percent"):
        CrawlConfig(memory_high_watermark_percent=80.0, memory_recovery_watermark_percent=80.0)


def test_crawl_config_rejects_negative_retries():
    with pytest.raises(ValueError, match="frontier_max_retries"):
        CrawlConfig(frontier_max_retries=-1)


def test_crawl_config_rejects_negative_retry_delay():
    with pytest.raises(ValueError, match="frontier_retry_base_delay_seconds"):
        CrawlConfig(frontier_retry_base_delay_seconds=-0.5)


# ---------------------------------------------------------------------------
# intent-overlap thresholds / ANN
# ---------------------------------------------------------------------------


def test_intent_overlap_rejects_threshold_above_one():
    with pytest.raises(SystemExit) as exc:
        _parse(["intent-overlap", "--threshold", "1.5"])
    assert exc.value.code == 2


def test_intent_overlap_rejects_nan_threshold():
    with pytest.raises(SystemExit) as exc:
        _parse(["intent-overlap", "--threshold", "nan"])
    assert exc.value.code == 2


def test_intent_overlap_rejects_dup_below_threshold():
    args = _parse(["intent-overlap", "--threshold", "0.9", "--dup-threshold", "0.8"])
    with pytest.raises(ValueError, match="dup-threshold"):
        _validate_intent_overlap_numeric_args(args)


def test_intent_overlap_rejects_non_positive_ann_k():
    with pytest.raises(SystemExit) as exc:
        _parse(["intent-overlap", "--ann-k", "0"])
    assert exc.value.code == 2


@pytest.mark.asyncio
async def test_intent_overlap_validation_before_output_dir(monkeypatch, tmp_path):
    out = tmp_path / "overlap-out"
    monkeypatch.setattr(
        "crawler_cli.__main__._store_from_args",
        lambda args: (_ for _ in ()).throw(AssertionError("store must not open")),
    )
    args = _parse(
        [
            "intent-overlap",
            "--threshold",
            "0.9",
            "--dup-threshold",
            "0.8",
            "--out",
            str(out),
        ]
    )
    code = await _run_intent_overlap(args)
    assert code == 2
    assert not out.exists()


def test_intent_overlap_accepts_equal_thresholds():
    args = _parse(["intent-overlap", "--threshold", "0.9", "--dup-threshold", "0.9"])
    _validate_intent_overlap_numeric_args(args)
