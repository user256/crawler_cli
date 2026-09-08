"""The exposure-inventory command (ticket 146).

The command exists to inventory hosts an operator has declared. Its first
obligation is therefore to refuse to run without that declaration — and to
refuse before anything touches the network, since deriving and resolving extra
hostnames is what widens the target set in the first place.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from crawler_cli.__main__ import _build_parser, _run_exposure_inventory
from crawler_cli.authorisation import SCOPE_MANIFEST_SCHEMA_VERSION


def manifest_path(tmp_path: Path, **overrides: object) -> str:
    now = datetime.now(timezone.utc)
    document: dict[str, object] = {
        "schema_version": SCOPE_MANIFEST_SCHEMA_VERSION,
        "authorization_reference": "CHANGE-1234",
        "operator": "team-evidence",
        "valid_from": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valid_until": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "allowed_origins": ["https://www.example.com", "https://dev.example.com"],
        "allowed_path_prefixes": ["/"],
    }
    document.update(overrides)
    path = tmp_path / "scope.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def _args(*argv: str):
    return _build_parser().parse_args(["exposure-inventory", *argv])


def _run(args) -> int:
    return asyncio.run(_run_exposure_inventory(args))


def test_the_command_is_registered_with_its_own_options():
    args = _args("https://www.example.com/", "--label", "sandbox", "--candidate-path", "/health")
    assert args.command == "exposure-inventory"
    assert args.label == ["sandbox"]
    assert args.candidate_path == "/health"


def test_without_a_manifest_it_refuses_before_touching_the_network(capsys, monkeypatch):
    """Deriving hostnames widens the target set, so declaration comes first."""

    def _no_engine(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("the command must not construct an engine without a manifest")

    monkeypatch.setattr("crawler_cli.__main__.CrawlEngine", _no_engine)

    assert _run(_args("https://www.example.com/")) == 2
    assert "requires --scope-manifest" in capsys.readouterr().err


def test_an_invalid_manifest_is_rejected_before_any_engine_is_built(tmp_path, capsys, monkeypatch):
    def _no_engine(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("the command must not construct an engine for an invalid manifest")

    monkeypatch.setattr("crawler_cli.__main__.CrawlEngine", _no_engine)
    expired = manifest_path(
        tmp_path,
        valid_until=(datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    assert _run(_args("https://www.example.com/", "--scope-manifest", expired)) == 2
    assert "Error" in capsys.readouterr().err


def test_a_wildcard_label_is_rejected(tmp_path, capsys):
    args = _args("https://www.example.com/", "--scope-manifest", manifest_path(tmp_path), "--label", "*")
    assert _run(args) == 2
    assert "wildcard" in capsys.readouterr().err


def test_seeds_are_required_to_derive_candidates_from(tmp_path, capsys):
    assert _run(_args("--scope-manifest", manifest_path(tmp_path))) == 2
    assert "at least one crawled URL" in capsys.readouterr().err
