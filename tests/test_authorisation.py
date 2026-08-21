"""Ticket 148: authorisation and scope-manifest schema, model, CLI, and predicate.

Every test in this module runs under the ``no_network`` fixture, which fails the
test if any code path attempts a DNS lookup or opens a socket. That is the
ticket's central acceptance gate: manifest validation failures and out-of-scope
inputs must be decided entirely before a single request is made.
"""

from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from crawler_cli.authorisation import (
    ATTESTATION_NOTICE,
    SCOPE_MANIFEST_SCHEMA_VERSION,
    SCOPE_SNAPSHOT_SCHEMA_VERSION,
    SECURITY_ADJACENT_COMMANDS,
    ScopeManifestDenied,
    ScopeManifestError,
    ScopePredicate,
    assert_cli_narrows_scope,
    assert_inputs_in_scope,
    compile_scope_predicate,
    describe_manifest,
    load_scope_manifest,
    normalize_origin,
    parse_scope_manifest,
    run_capabilities,
)

NOW = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if anything in it resolves a hostname or opens a socket.

    This is the proof, rather than an assertion about intent, that manifest
    validation and scope refusal happen before any network activity.
    """

    def _forbidden(*args: object, **kwargs: object):
        raise AssertionError("network activity attempted during a scope-manifest test")

    monkeypatch.setattr(socket, "getaddrinfo", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbidden)


def manifest_document(**overrides: object) -> dict[str, object]:
    """Return a valid version 1 manifest document with optional overrides."""
    document: dict[str, object] = {
        "schema_version": SCOPE_MANIFEST_SCHEMA_VERSION,
        "authorization_reference": "CHANGE-1234",
        "operator": "team-evidence",
        "valid_from": "2026-08-21T09:00:00Z",
        "valid_until": "2026-08-21T17:00:00Z",
        "allowed_origins": ["https://www.example.com:443"],
        "allowed_path_prefixes": ["/"],
        "excluded_path_prefixes": ["/customer/export"],
        "allowed_methods": ["GET", "HEAD"],
        "allow_private_network": False,
        "allow_ignore_robots": False,
        "notes": "Authorised pre-release exposure review",
    }
    document.update(overrides)
    return document


def build_predicate(**overrides: object) -> ScopePredicate:
    """Compile a predicate whose window brackets the real clock.

    Tests about origin, path, and method must not depend on when the suite runs,
    so the default window is generated around the current time. The tests that
    are specifically about the validity window override it with fixed
    timestamps and pass an explicit ``now``.
    """
    live = datetime.now(timezone.utc)
    window = {
        "valid_from": (live - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valid_until": (live + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return ScopePredicate(parse_scope_manifest(manifest_document(**{**window, **overrides})))


def write_manifest(tmp_path: Path, **overrides: object) -> Path:
    path = tmp_path / "scope.json"
    path.write_text(json.dumps(manifest_document(**overrides)), encoding="utf-8")
    return path


# --- Schema and model ---------------------------------------------------------


def test_valid_manifest_parses_and_normalises() -> None:
    manifest = parse_scope_manifest(manifest_document())
    assert manifest.authorization_reference == "CHANGE-1234"
    assert manifest.operator == "team-evidence"
    assert manifest.allowed_origins == ("https://www.example.com:443",)
    assert manifest.allowed_methods == ("GET", "HEAD")
    assert manifest.notes == "Authorised pre-release exposure review"


def test_default_and_explicit_ports_normalise_to_the_same_origin() -> None:
    assert normalize_origin("https://www.example.com") == "https://www.example.com:443"
    assert normalize_origin("https://www.example.com:443") == "https://www.example.com:443"
    assert normalize_origin("http://www.example.com") == "http://www.example.com:80"
    assert normalize_origin("http://www.example.com:80/") == "http://www.example.com:80"


def test_unicode_trailing_dot_and_case_cannot_disagree_about_scope() -> None:
    predicate = build_predicate(allowed_origins=["https://WWW.Example.COM."])
    assert predicate.is_allowed("https://www.example.com/a")
    assert predicate.is_allowed("https://WWW.EXAMPLE.COM./a")
    assert predicate.is_allowed("https://www.example.com.:443/a")


def test_internationalised_hostname_matches_its_idna_form() -> None:
    predicate = build_predicate(allowed_origins=["https://münchen.example"])
    assert predicate.is_allowed("https://xn--mnchen-3ya.example/a")
    assert predicate.is_allowed("https://MÜNCHEN.example/a")


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"schema_version": "crawler-cli/scope-manifest/2"}, "unsupported scope manifest schema_version"),
        ({"allowed_origins": ["https://*.example.com"]}, "does not support wildcards"),
        ({"allowed_origins": ["https://user:pw@www.example.com"]}, "must not carry userinfo"),
        ({"allowed_origins": ["ftp://www.example.com"]}, "must use http or https"),
        ({"allowed_origins": ["https://www.example.com/shop"]}, "are origins, not URLs"),
        ({"allowed_origins": []}, "must list at least one entry"),
        ({"allowed_methods": ["POST"]}, "may list only methods this crawler implements"),
        ({"valid_from": "2026-08-21 09:00:00"}, "UTC RFC 3339 timestamp"),
        ({"valid_from": "2026-08-21T09:00:00+02:00"}, "UTC RFC 3339 timestamp"),
        ({"valid_until": "2026-08-21T08:00:00Z"}, "valid_until must be after valid_from"),
        ({"authorization_reference": ""}, "must be a non-empty string"),
        ({"operator": "   "}, "must be a non-empty string"),
        ({"allowed_path_prefixes": ["shop"]}, "must start with '/'"),
    ],
)
def test_invalid_manifests_are_rejected(overrides: dict[str, object], fragment: str) -> None:
    with pytest.raises(ScopeManifestError) as excinfo:
        parse_scope_manifest(manifest_document(**overrides))
    assert fragment in str(excinfo.value)


def test_missing_validity_window_is_rejected() -> None:
    document = manifest_document()
    del document["valid_until"]
    with pytest.raises(ScopeManifestError) as excinfo:
        parse_scope_manifest(document)
    assert "missing required field(s): valid_until" in str(excinfo.value)


def test_unknown_fields_are_rejected_rather_than_ignored() -> None:
    with pytest.raises(ScopeManifestError) as excinfo:
        parse_scope_manifest({**manifest_document(), "allow_exploit": True})
    assert "unknown scope manifest field(s): allow_exploit" in str(excinfo.value)


def test_expired_window_is_rejected_at_load_time(tmp_path: Path) -> None:
    path = write_manifest(tmp_path)
    with pytest.raises(ScopeManifestError) as excinfo:
        load_scope_manifest(path, now=NOW + timedelta(days=1))
    assert "expired at 2026-08-21T17:00:00Z" in str(excinfo.value)


def test_not_yet_valid_window_is_rejected_at_load_time(tmp_path: Path) -> None:
    path = write_manifest(tmp_path)
    with pytest.raises(ScopeManifestError) as excinfo:
        load_scope_manifest(path, now=NOW - timedelta(days=1))
    assert "is not valid until 2026-08-21T09:00:00Z" in str(excinfo.value)


def test_load_accepts_a_manifest_inside_its_window(tmp_path: Path) -> None:
    manifest = load_scope_manifest(write_manifest(tmp_path), now=NOW)
    assert manifest.authorization_reference == "CHANGE-1234"


def test_malformed_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "scope.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ScopeManifestError) as excinfo:
        load_scope_manifest(path, now=NOW)
    assert "is not valid JSON" in str(excinfo.value)


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScopeManifestError) as excinfo:
        load_scope_manifest(tmp_path / "absent.json", now=NOW)
    assert "Unable to read scope manifest" in str(excinfo.value)


# --- Origin and path predicate -------------------------------------------------


def test_parent_domain_does_not_authorise_an_undeclared_subdomain() -> None:
    predicate = build_predicate(allowed_origins=["https://example.com"])
    assert predicate.is_allowed("https://example.com/a")
    decision = predicate.decide("https://shop.example.com/a")
    assert not decision.allowed
    assert decision.reason == "origin"


def test_scheme_and_port_are_part_of_the_origin() -> None:
    predicate = build_predicate(allowed_origins=["https://www.example.com:443"])
    assert predicate.decide("http://www.example.com/a").reason == "origin"
    assert predicate.decide("https://www.example.com:8443/a").reason == "origin"


@pytest.mark.parametrize(
    "url, reason",
    [
        ("https://user:pw@www.example.com/a", "userinfo"),
        ("ftp://www.example.com/a", "scheme"),
        ("javascript:alert(1)", "scheme"),
        ("/relative/path", "malformed_url"),
        ("https:///nohost", "malformed_url"),
    ],
)
def test_malformed_and_credential_urls_are_refused(url: str, reason: str) -> None:
    predicate = build_predicate()
    decision = predicate.decide(url)
    assert not decision.allowed
    assert decision.reason == reason


def test_allowed_path_prefix_boundary_is_a_path_segment() -> None:
    predicate = build_predicate(allowed_path_prefixes=["/shop"], excluded_path_prefixes=[])
    assert predicate.is_allowed("https://www.example.com/shop")
    assert predicate.is_allowed("https://www.example.com/shop/")
    assert predicate.is_allowed("https://www.example.com/shop/socks")
    assert predicate.decide("https://www.example.com/shopping").reason == "path"
    assert predicate.decide("https://www.example.com/").reason == "path"


def test_excluded_path_prefix_wins_over_an_allowed_prefix() -> None:
    predicate = build_predicate(
        allowed_path_prefixes=["/"],
        excluded_path_prefixes=["/customer/export"],
    )
    assert predicate.is_allowed("https://www.example.com/customer/profile")
    assert predicate.decide("https://www.example.com/customer/export").reason == "path"
    assert predicate.decide("https://www.example.com/customer/export/2026").reason == "path"


def test_query_and_fragment_do_not_affect_the_path_decision() -> None:
    predicate = build_predicate(allowed_path_prefixes=["/shop"], excluded_path_prefixes=[])
    assert predicate.is_allowed("https://www.example.com/shop?utm=1#top")
    assert predicate.decide("https://www.example.com/other?path=/shop").reason == "path"


def test_dot_segments_cannot_walk_out_of_an_allowed_prefix() -> None:
    predicate = build_predicate(allowed_path_prefixes=["/shop"], excluded_path_prefixes=[])
    assert predicate.decide("https://www.example.com/shop/../admin").reason == "path"


def test_percent_encoded_spellings_are_only_ever_more_restrictive() -> None:
    predicate = build_predicate(
        allowed_path_prefixes=["/"],
        excluded_path_prefixes=["/customer/export"],
    )
    # The decoded form lands inside the exclusion, so the encoded spelling is
    # refused rather than slipping past a raw-string comparison.
    assert predicate.decide("https://www.example.com/customer/%65xport").reason == "path"


def test_robots_txt_is_admitted_for_a_narrow_path_manifest() -> None:
    predicate = build_predicate(allowed_path_prefixes=["/shop"], excluded_path_prefixes=[])
    assert predicate.is_allowed("https://www.example.com/robots.txt", purpose="robots")
    # The relaxation is limited to the exact well-known document.
    assert not predicate.is_allowed("https://www.example.com/secrets.txt", purpose="robots")
    # And it never relaxes the origin check.
    assert predicate.decide("https://other.example/robots.txt", purpose="robots").reason == "origin"


def test_time_window_is_checked_on_every_decision() -> None:
    predicate = ScopePredicate(parse_scope_manifest(manifest_document()))
    assert predicate.decide("https://www.example.com/a", now=NOW).allowed
    assert predicate.decide("https://www.example.com/a", now=NOW + timedelta(days=1)).reason == "time_window"
    assert predicate.decide("https://www.example.com/a", now=NOW - timedelta(days=1)).reason == "time_window"


def test_unimplemented_method_is_refused_by_the_predicate() -> None:
    predicate = build_predicate()
    assert predicate.decide("https://www.example.com/a", method="POST").reason == "method"


def test_manifest_listing_only_get_refuses_head() -> None:
    predicate = build_predicate(allowed_methods=["GET"])
    assert predicate.is_allowed("https://www.example.com/a", method="GET")
    assert predicate.decide("https://www.example.com/a", method="HEAD").reason == "method"


def test_require_raises_a_distinct_denial_exception() -> None:
    predicate = build_predicate()
    with pytest.raises(ScopeManifestDenied) as excinfo:
        predicate.require("https://other.example/a")
    assert excinfo.value.reason == "origin"
    assert "scope_manifest_denied" not in str(excinfo.value)


def test_skip_reason_carries_the_structured_reason() -> None:
    predicate = build_predicate()
    assert predicate.decide("https://other.example/a").skip_reason == "scope_manifest_denied:origin"
    assert predicate.decide("https://www.example.com/a").skip_reason is None


def test_compile_returns_none_without_a_manifest() -> None:
    assert compile_scope_predicate(None) is None


# --- Input sets ----------------------------------------------------------------


def test_mixed_input_set_fails_as_a_whole() -> None:
    predicate = build_predicate()
    with pytest.raises(ScopeManifestError) as excinfo:
        assert_inputs_in_scope(
            predicate,
            ["https://www.example.com/a", "https://other.example/b"],
            label="seed",
        )
    message = str(excinfo.value)
    assert "1 seed URL(s) fall outside scope manifest CHANGE-1234" in message
    assert "https://other.example/b (origin)" in message
    assert "No request was made" in message


def test_fully_in_scope_input_set_is_accepted() -> None:
    predicate = build_predicate()
    assert_inputs_in_scope(predicate, ["https://www.example.com/a", "https://www.example.com/b"])


def test_input_check_is_a_no_op_without_a_manifest() -> None:
    assert_inputs_in_scope(None, ["https://anywhere.example/a"])


def test_partition_reports_each_rejection_reason() -> None:
    predicate = build_predicate(allowed_path_prefixes=["/shop"], excluded_path_prefixes=[])
    accepted, rejected = predicate.partition(
        ["https://www.example.com/shop/a", "https://www.example.com/admin", "https://other.example/shop"]
    )
    assert accepted == ["https://www.example.com/shop/a"]
    assert rejected == [("https://www.example.com/admin", "path"), ("https://other.example/shop", "origin")]


# --- CLI narrowing -------------------------------------------------------------


def test_allowed_hosts_may_narrow_the_manifest() -> None:
    predicate = build_predicate(
        allowed_origins=["https://www.example.com", "https://cdn.example.com"],
    )
    # Naming a declared host is narrowing, which is always permitted.
    assert_cli_narrows_scope(predicate, allowed_hosts=["cdn.example.com"])


def test_allowed_hosts_cannot_widen_the_manifest() -> None:
    predicate = build_predicate()
    with pytest.raises(ScopeManifestError) as excinfo:
        assert_cli_narrows_scope(predicate, allowed_hosts=["cdn.other.example"])
    assert "may only narrow the scope manifest" in str(excinfo.value)
    assert "cdn.other.example" in str(excinfo.value)


def test_offsite_is_refused_with_a_manifest() -> None:
    with pytest.raises(ScopeManifestError) as excinfo:
        assert_cli_narrows_scope(build_predicate(), offsite=True)
    assert "--offsite cannot be combined with --scope-manifest" in str(excinfo.value)


def test_ignore_robots_needs_manifest_permission() -> None:
    with pytest.raises(ScopeManifestError) as excinfo:
        assert_cli_narrows_scope(build_predicate(), ignore_robots=True, ignore_robots_confirmed=True)
    assert "allow_ignore_robots to false" in str(excinfo.value)


def test_ignore_robots_needs_explicit_confirmation_as_well() -> None:
    predicate = build_predicate(allow_ignore_robots=True)
    with pytest.raises(ScopeManifestError) as excinfo:
        assert_cli_narrows_scope(predicate, ignore_robots=True, ignore_robots_confirmed=False)
    assert "requires the explicit robots-override confirmation" in str(excinfo.value)
    # With both the manifest permission and the confirmation it is accepted.
    assert_cli_narrows_scope(predicate, ignore_robots=True, ignore_robots_confirmed=True)


def test_archive_seeding_requires_the_archive_origin_in_the_manifest() -> None:
    with pytest.raises(ScopeManifestError) as excinfo:
        assert_cli_narrows_scope(build_predicate(), seed_from_archive=True)
    assert "web.archive.org" in str(excinfo.value)
    permitted = build_predicate(allowed_origins=["https://www.example.com", "https://web.archive.org"])
    assert_cli_narrows_scope(permitted, seed_from_archive=True)


def test_narrowing_checks_are_a_no_op_without_a_manifest() -> None:
    assert_cli_narrows_scope(None, allowed_hosts=["anything.example"], offsite=True, ignore_robots=True)


# --- Snapshot, digest, and capabilities ----------------------------------------


def test_snapshot_is_secret_free_and_versioned() -> None:
    manifest = parse_scope_manifest(manifest_document(notes="internal customer AcmeCorp, ticket body"))
    snapshot = manifest.snapshot()
    assert snapshot["schema_version"] == SCOPE_SNAPSHOT_SCHEMA_VERSION
    assert snapshot["attestation_notice"] == ATTESTATION_NOTICE
    assert "notes" not in snapshot
    assert "AcmeCorp" not in json.dumps(snapshot)


def test_digest_ignores_notes_but_tracks_material_scope() -> None:
    base = parse_scope_manifest(manifest_document())
    reworded = parse_scope_manifest(manifest_document(notes="different prose entirely"))
    widened = parse_scope_manifest(
        manifest_document(allowed_origins=["https://www.example.com", "https://cdn.example.com"])
    )
    moved_window = parse_scope_manifest(manifest_document(valid_until="2026-08-21T18:00:00Z"))
    assert base.digest == reworded.digest
    assert base.digest != widened.digest
    assert base.digest != moved_window.digest


def test_digest_is_stable_across_equivalent_spellings() -> None:
    a = parse_scope_manifest(manifest_document(allowed_origins=["https://WWW.Example.COM.:443"]))
    b = parse_scope_manifest(manifest_document(allowed_origins=["https://www.example.com"]))
    assert a.digest == b.digest


def test_describe_manifest_names_the_reference_and_digest_not_the_body() -> None:
    manifest = parse_scope_manifest(manifest_document(notes="do not print me"))
    description = describe_manifest(manifest)
    assert "CHANGE-1234" in description
    assert manifest.digest[:16] in description
    assert "do not print me" not in description
    assert ATTESTATION_NOTICE in description


def test_capability_object_distinguishes_intent_scope_from_pinning() -> None:
    predicate = build_predicate()
    intent_only = run_capabilities(predicate)
    assert intent_only.intent_scope is True
    assert intent_only.connection_pinning is False
    assert intent_only.unguarded_browser_paths is False
    assert intent_only.scope_manifest_digest == predicate.digest

    pinned_browser = run_capabilities(predicate, connection_pinning=True, browser_backend=True)
    assert pinned_browser.connection_pinning is True
    assert pinned_browser.unguarded_browser_paths is True

    unguarded = run_capabilities(None)
    assert unguarded.as_dict() == {
        "intent_scope": False,
        "connection_pinning": False,
        "unguarded_browser_paths": False,
        "scope_manifest_digest": None,
        "attestation_notice": ATTESTATION_NOTICE,
    }


def test_no_security_adjacent_commands_exist_yet() -> None:
    """Tickets 145-152 and 154 add their command names to this set.

    The assertion documents the current state honestly: the manifest, loader,
    validation, predicate, and enforcement hook exist, but no command in this
    build is classified as security-adjacent, so none is gated on a manifest.
    """
    assert SECURITY_ADJACENT_COMMANDS == frozenset()
