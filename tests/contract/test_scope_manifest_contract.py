"""Golden contract: the authorisation scope snapshot (ticket 148).

Freezes ``crawler-cli/scope-snapshot/1`` — the exact, secret-free projection of
a scope manifest that is written into run metadata and into saved crawl
artifacts — and the ``crawler-cli/crawl-artifact/5`` envelope that carries it.

Two properties matter to downstream consumers and are asserted here rather than
described: every artifact declares v5 and has an ``authorization_scope`` field;
it is ``null`` for a manifest-free crawl. A manifest-backed artifact carries the
snapshot, opaque authorisation reference, and attestation notice, but never the
manifest's free-text notes.
"""

from __future__ import annotations

import json

from contract_fixtures import assert_matches_golden

from crawler_cli.authorisation import (
    ATTESTATION_NOTICE,
    SCOPE_MANIFEST_SCHEMA_VERSION,
    SCOPE_SNAPSHOT_SCHEMA_VERSION,
    parse_scope_manifest,
)
from crawler_cli.models import CrawlJobResult
from crawler_cli.serialization import CRAWL_ARTIFACT_SCHEMA_VERSION, serialize_crawl_job

EXPECTED_SNAPSHOT_KEYS = {
    "schema_version",
    "manifest_schema_version",
    "authorization_reference",
    "operator",
    "valid_from",
    "valid_until",
    "allowed_origins",
    "allowed_path_prefixes",
    "excluded_path_prefixes",
    "allowed_methods",
    "allow_private_network",
    "allow_ignore_robots",
    "attestation_notice",
}

# A deliberately secret-looking string. It must never reach the snapshot, the
# artifact, or the digest input.
TEST_SECRET = "s3cret-customer-AcmeCorp-token"

MANIFEST_DOCUMENT = {
    "schema_version": SCOPE_MANIFEST_SCHEMA_VERSION,
    "authorization_reference": "CHANGE-1234",
    "operator": "team-evidence",
    "valid_from": "2026-08-21T09:00:00Z",
    "valid_until": "2026-08-21T17:00:00Z",
    "allowed_origins": ["https://WWW.Example.COM.", "http://staging.example.com:8080"],
    "allowed_path_prefixes": ["/shop/", "/help"],
    "excluded_path_prefixes": ["/customer/export"],
    "allowed_methods": ["GET", "HEAD"],
    "allow_private_network": False,
    "allow_ignore_robots": False,
    "notes": f"Authorised pre-release exposure review {TEST_SECRET}",
}


def _manifest():
    return parse_scope_manifest(MANIFEST_DOCUMENT)


def test_scope_snapshot_matches_golden() -> None:
    snapshot = _manifest().snapshot()
    assert snapshot["schema_version"] == SCOPE_SNAPSHOT_SCHEMA_VERSION == "crawler-cli/scope-snapshot/1"
    assert set(snapshot.keys()) == EXPECTED_SNAPSHOT_KEYS
    assert_matches_golden("scope_snapshot.json", json.dumps(snapshot, indent=2) + "\n")


def test_snapshot_normalises_origins_and_path_prefixes() -> None:
    snapshot = _manifest().snapshot()
    assert snapshot["allowed_origins"] == ["https://www.example.com:443", "http://staging.example.com:8080"]
    assert snapshot["allowed_path_prefixes"] == ["/shop", "/help"]


def test_digest_is_frozen_for_the_golden_manifest() -> None:
    """The digest is a stable identity, so it is pinned like any other contract."""
    assert _manifest().digest == "bac3e42a7c8edea580eaf538cf11159474f49f775697ec6498e0a06ae3a4d8c8"


def test_snapshot_and_artifact_never_carry_the_manifest_notes() -> None:
    manifest = _manifest()
    job = CrawlJobResult(
        mode="open",
        seed_urls=["https://www.example.com/shop"],
        results=[],
        run_id="run-148",
        authorization_scope=manifest.snapshot(),
    )
    payload = serialize_crawl_job(job)
    rendered = json.dumps(payload)
    assert TEST_SECRET not in rendered
    assert "notes" not in rendered
    # The notes are not merely absent from the artifact; they never entered the
    # digest input either, so re-wording them cannot invalidate a resumable run.
    assert manifest.digest == parse_scope_manifest({**MANIFEST_DOCUMENT, "notes": "entirely different"}).digest


def test_manifest_backed_artifact_declares_the_current_schema_version() -> None:
    job = CrawlJobResult(
        mode="open",
        seed_urls=["https://www.example.com/shop"],
        results=[],
        run_id="run-148",
        authorization_scope=_manifest().snapshot(),
    )
    payload = serialize_crawl_job(job)
    assert payload["schema_version"] == CRAWL_ARTIFACT_SCHEMA_VERSION == "crawler-cli/crawl-artifact/5"
    scope = payload["authorization_scope"]
    assert scope["authorization_reference"] == "CHANGE-1234"
    assert scope["attestation_notice"] == ATTESTATION_NOTICE


def test_manifest_free_artifact_has_a_null_scope_projection() -> None:
    payload = serialize_crawl_job(CrawlJobResult(mode="open", seed_urls=[], results=[], run_id="run-148"))
    assert payload["schema_version"] == CRAWL_ARTIFACT_SCHEMA_VERSION == "crawler-cli/crawl-artifact/5"
    assert payload["authorization_scope"] is None
