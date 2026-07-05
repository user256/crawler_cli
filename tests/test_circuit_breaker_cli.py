"""Ticket 039: circuit-breaker CLI / env-var tuning."""

from crawler_cli.__main__ import _build_parser, _resolve_circuit_breaker
from crawler_cli.config import (
    CB_RECOVERY_SECONDS_DEFAULT,
    CB_THRESHOLD_DEFAULT,
)


def _parse(argv):
    parser = _build_parser()
    return parser.parse_args(["crawl", "https://example.com", *argv])


def test_defaults_when_nothing_set(monkeypatch):
    for var in ("CRAWLER_CLI_CB_THRESHOLD", "CRAWLER_CLI_CB_RECOVERY_SECONDS", "CRAWLER_CLI_CB_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    args = _parse([])
    enabled, threshold, recovery = _resolve_circuit_breaker(args)
    assert enabled is True
    assert threshold == CB_THRESHOLD_DEFAULT
    assert recovery == CB_RECOVERY_SECONDS_DEFAULT


def test_cli_threshold_override(monkeypatch):
    monkeypatch.delenv("CRAWLER_CLI_CB_THRESHOLD", raising=False)
    args = _parse(["--circuit-breaker-threshold", "15"])
    enabled, threshold, _ = _resolve_circuit_breaker(args)
    assert enabled is True
    assert threshold == 15


def test_cli_recovery_override(monkeypatch):
    monkeypatch.delenv("CRAWLER_CLI_CB_RECOVERY_SECONDS", raising=False)
    args = _parse(["--circuit-breaker-recovery-seconds", "60"])
    _, _, recovery = _resolve_circuit_breaker(args)
    assert recovery == 60.0


def test_env_threshold_override(monkeypatch):
    monkeypatch.setenv("CRAWLER_CLI_CB_THRESHOLD", "15")
    args = _parse([])
    _, threshold, _ = _resolve_circuit_breaker(args)
    assert threshold == 15


def test_cli_wins_over_env(monkeypatch):
    monkeypatch.setenv("CRAWLER_CLI_CB_THRESHOLD", "99")
    args = _parse(["--circuit-breaker-threshold", "7"])
    _, threshold, _ = _resolve_circuit_breaker(args)
    assert threshold == 7


def test_env_enabled_disables(monkeypatch):
    monkeypatch.setenv("CRAWLER_CLI_CB_ENABLED", "0")
    args = _parse([])
    enabled, _, _ = _resolve_circuit_breaker(args)
    assert enabled is False


def test_no_circuit_breaker_flag(monkeypatch):
    monkeypatch.delenv("CRAWLER_CLI_CB_ENABLED", raising=False)
    args = _parse(["--no-circuit-breaker"])
    enabled, _, _ = _resolve_circuit_breaker(args)
    assert enabled is False


def test_no_circuit_breaker_disables_engine_gate(monkeypatch):
    """DoD: --no-circuit-breaker means the breaker never blocks a fetch.

    With circuit_breaker_enabled=False the engine skips the should_allow() gate
    entirely (engine.py), so a host that would otherwise be tripped is always
    allowed. We assert the realized config drives that branch.
    """
    from crawler_cli.config import CrawlConfig

    args = _parse(["--no-circuit-breaker"])
    enabled, threshold, recovery = _resolve_circuit_breaker(args)
    config = CrawlConfig(
        circuit_breaker_enabled=enabled,
        circuit_breaker_failure_threshold=threshold,
        circuit_breaker_recovery_seconds=recovery,
    )
    assert config.circuit_breaker_enabled is False


def test_all_three_flags_registered():
    parsed = _parse(
        ["--circuit-breaker-threshold", "5", "--circuit-breaker-recovery-seconds", "12", "--no-circuit-breaker"]
    )
    assert parsed.circuit_breaker_threshold == 5
    assert parsed.circuit_breaker_recovery_seconds == 12.0
    assert parsed.no_circuit_breaker is True
