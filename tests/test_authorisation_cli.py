"""Ticket 148: ``--scope-manifest`` loading, preflight, and no-network proof.

Every test runs under the ``no_network`` fixture. A failure to reject an invalid
manifest, an expired window, a widening flag, or an out-of-scope seed would show
up here as an attempted DNS lookup or socket connection, which fails the test.
"""

from __future__ import annotations

import asyncio
import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from crawler_cli.__main__ import _build_config, _build_parser, _run_crawl
from crawler_cli.authorisation import SCOPE_MANIFEST_SCHEMA_VERSION, ScopeManifestError
from crawler_cli.exit_codes import EXIT_VALIDATION


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object):
        raise AssertionError("network activity attempted during a scope-manifest CLI test")

    monkeypatch.setattr(socket, "getaddrinfo", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbidden)


@pytest.fixture(autouse=True)
def no_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if a fetch backend is constructed.

    A startup rejection must happen before the engine exists, so building a
    backend at all means the rejection came too late.
    """
    from crawler_cli import engine as engine_module

    def _forbidden(*args: object, **kwargs: object):
        raise AssertionError("a fetch backend was constructed despite a scope validation failure")

    monkeypatch.setattr(engine_module, "build_backend", _forbidden)


def manifest_path(tmp_path: Path, **overrides: object) -> str:
    now = datetime.now(timezone.utc)
    document: dict[str, object] = {
        "schema_version": SCOPE_MANIFEST_SCHEMA_VERSION,
        "authorization_reference": "CHANGE-1234",
        "operator": "team-evidence",
        "valid_from": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valid_until": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "allowed_origins": ["https://www.example.com"],
        "allowed_path_prefixes": ["/"],
    }
    document.update(overrides)
    path = tmp_path / "scope.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def parse_args(*argv: str):
    return _build_parser().parse_args(["crawl", "https://www.example.com/", *argv])


def run_crawl(args) -> int:
    return asyncio.run(_run_crawl(args))


# --- Flag wiring ---------------------------------------------------------------


def test_manifest_free_crawl_has_no_predicate() -> None:
    config = _build_config(parse_args())
    assert config.scope_predicate is None


def test_manifest_is_compiled_into_the_config(tmp_path: Path) -> None:
    config = _build_config(parse_args("--scope-manifest", manifest_path(tmp_path)))
    assert config.scope_predicate is not None
    assert config.scope_predicate.manifest.authorization_reference == "CHANGE-1234"
    assert config.scope_predicate.is_allowed("https://www.example.com/a")


def test_manifest_contents_are_not_placed_on_argv(tmp_path: Path) -> None:
    """Only the path is a command-line value; the document is read from disk."""
    args = parse_args("--scope-manifest", manifest_path(tmp_path))
    assert args.scope_manifest.endswith("scope.json")
    assert "authorization_reference" not in json.dumps(vars(args), default=str)


def test_help_states_the_attestation_limitation() -> None:
    crawl_help = _build_parser()._subparsers._group_actions[0].choices["crawl"].format_help()
    # argparse re-wraps help text, so compare against a whitespace-normalised
    # rendering rather than against the wrapped lines.
    flattened = " ".join(crawl_help.split())
    assert "--scope-manifest" in flattened
    assert "ATTESTATION" in flattened
    assert "not proof of legal permission" in flattened
    assert "Ordinary technical-SEO crawling does not require it." in flattened


# --- Validation failures make no network calls ----------------------------------


def test_expired_manifest_is_rejected_before_any_network_activity(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    path = manifest_path(
        tmp_path,
        valid_from=(now - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        valid_until=(now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    with pytest.raises(ScopeManifestError) as excinfo:
        _build_config(parse_args("--scope-manifest", path))
    assert "expired at" in str(excinfo.value)


def test_not_yet_valid_manifest_is_rejected_before_any_network_activity(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    path = manifest_path(
        tmp_path,
        valid_from=(now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        valid_until=(now + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    with pytest.raises(ScopeManifestError) as excinfo:
        _build_config(parse_args("--scope-manifest", path))
    assert "is not valid until" in str(excinfo.value)


def test_unknown_schema_version_is_rejected(tmp_path: Path) -> None:
    path = manifest_path(tmp_path, schema_version="crawler-cli/scope-manifest/99")
    with pytest.raises(ScopeManifestError):
        _build_config(parse_args("--scope-manifest", path))


def test_wildcard_origin_is_rejected(tmp_path: Path) -> None:
    path = manifest_path(tmp_path, allowed_origins=["https://*.example.com"])
    with pytest.raises(ScopeManifestError):
        _build_config(parse_args("--scope-manifest", path))


def test_run_crawl_exits_validation_on_an_expired_manifest(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    path = manifest_path(
        tmp_path,
        valid_from=(now - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        valid_until=(now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert run_crawl(parse_args("--scope-manifest", path)) == EXIT_VALIDATION


# --- Narrowing versus widening ---------------------------------------------------


def test_allowed_hosts_may_narrow(tmp_path: Path) -> None:
    path = manifest_path(tmp_path, allowed_origins=["https://www.example.com", "https://cdn.example.com"])
    config = _build_config(parse_args("--scope-manifest", path, "--allowed-hosts", "cdn.example.com"))
    assert config.allowed_hosts == ["cdn.example.com"]


def test_allowed_hosts_cannot_widen(tmp_path: Path) -> None:
    path = manifest_path(tmp_path)
    with pytest.raises(ScopeManifestError) as excinfo:
        _build_config(parse_args("--scope-manifest", path, "--allowed-hosts", "cdn.other.example"))
    assert "may only narrow the scope manifest" in str(excinfo.value)


def test_offsite_is_rejected_with_a_manifest(tmp_path: Path) -> None:
    with pytest.raises(ScopeManifestError) as excinfo:
        _build_config(parse_args("--scope-manifest", manifest_path(tmp_path), "--offsite"))
    assert "--offsite cannot be combined with --scope-manifest" in str(excinfo.value)


def test_path_flags_narrow_without_complaint(tmp_path: Path) -> None:
    config = _build_config(
        parse_args(
            "--scope-manifest",
            manifest_path(tmp_path),
            "--path-restriction",
            "/shop",
            "--path-exclude",
            "/admin/",
        )
    )
    assert config.should_crawl_url("https://www.example.com/shop/socks")
    assert not config.should_crawl_url("https://www.example.com/news")
    assert not config.should_crawl_url("https://www.example.com/admin/panel")
    # The manifest still governs the origin regardless of the local flags.
    assert not config.should_crawl_url("https://other.example/shop/socks")


def test_ignore_robots_requires_manifest_permission_and_confirmation(tmp_path: Path) -> None:
    denied = manifest_path(tmp_path)
    with pytest.raises(ScopeManifestError) as excinfo:
        _build_config(parse_args("--scope-manifest", denied, "--ignore-robots", "--confirm-ignore-robots"))
    assert "allow_ignore_robots to false" in str(excinfo.value)

    permitted = manifest_path(tmp_path, allow_ignore_robots=True)
    with pytest.raises(ScopeManifestError) as excinfo:
        _build_config(parse_args("--scope-manifest", permitted, "--ignore-robots"))
    assert "requires the explicit robots-override confirmation" in str(excinfo.value)

    config = _build_config(parse_args("--scope-manifest", permitted, "--ignore-robots", "--confirm-ignore-robots"))
    assert config.respect_robots_txt is False


def test_ignore_robots_without_a_manifest_is_unchanged() -> None:
    config = _build_config(parse_args("--ignore-robots"))
    assert config.respect_robots_txt is False


# --- Input-set preflight ----------------------------------------------------------


def test_out_of_scope_seed_exits_validation_without_a_request(tmp_path: Path, capsys) -> None:
    args = _build_parser().parse_args(
        [
            "crawl",
            "https://www.example.com/",
            "--seed-url",
            "https://other.example/b",
            "--scope-manifest",
            manifest_path(tmp_path),
        ]
    )
    assert run_crawl(args) == EXIT_VALIDATION
    captured = capsys.readouterr()
    assert "fall outside scope manifest CHANGE-1234" in captured.err
    assert "https://other.example/b (origin)" in captured.err
    assert "No request was made" in captured.err


def test_in_scope_seeds_print_the_attestation_notice(tmp_path: Path, capsys, monkeypatch) -> None:
    """A valid preflight announces the manifest and its non-proof status.

    The crawl itself is stopped immediately afterwards by the no-backend
    fixture, which is what keeps this test free of network activity.
    """
    args = parse_args("--scope-manifest", manifest_path(tmp_path))
    with pytest.raises(AssertionError, match="a fetch backend was constructed"):
        run_crawl(args)
    captured = capsys.readouterr()
    assert "Scope manifest CHANGE-1234" in captured.out
    assert "not proof of legal permission" in captured.out
