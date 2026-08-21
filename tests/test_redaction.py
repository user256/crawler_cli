"""Unit tests for the central redaction machinery (ticket 153).

These cover the policy itself: header and cookie handling, URL projection,
keyed correlation digests, bounded snippets, exception and log scrubbing, and
CSV formula-injection hygiene. The end-to-end "no known secret appears
anywhere" proof lives in ``tests/contract/test_security_proofs.py``.
"""

from __future__ import annotations

import logging

import pytest

from crawler_cli.redaction import (
    REDACTED,
    REDACTED_EMAIL,
    CorrelationDigest,
    RedactionPolicy,
    SecretRegistry,
    bounded_snippet,
    csv_safe_cell,
    csv_safe_row,
    install_log_redaction,
    missing_secret_message,
    parse_set_cookie_evidence,
    project_url,
    redact_exception,
    redact_form_fields,
    redact_header_pairs,
    redact_headers,
    redact_query_string,
    redact_traceback,
    sanitize_dsn,
    sanitize_proxy_url,
    scrub_structure,
    scrub_text,
)

DIGEST = CorrelationDigest.from_key(b"deterministic-test-key-0123456789", run_id="run-test")


@pytest.fixture
def registry() -> SecretRegistry:
    return SecretRegistry()


# --- headers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["Authorization", "authorization", "AUTHORIZATION", "Proxy-Authorization", "Cookie", "Set-Cookie", "X-API-Key"],
)
def test_known_sensitive_header_names_match_in_any_case(name: str) -> None:
    assert RedactionPolicy().is_sensitive_header(name)


def test_unknown_header_with_token_substring_is_sensitive() -> None:
    """Sites invent their own header names; the substring rule over-redacts."""
    policy = RedactionPolicy()
    assert policy.is_sensitive_header("X-Acme-Shop-Session-Token")
    assert not policy.is_sensitive_header("Content-Type")


def test_configured_extra_header_name_is_sensitive() -> None:
    policy = RedactionPolicy(extra_header_names=frozenset({"X-Internal-Ref"}))
    assert policy.is_sensitive_header("x-internal-ref")


def test_redact_headers_preserves_multi_value_shape() -> None:
    redacted = redact_headers(
        {"Set-Cookie": ["sid=one; Secure", "csrf=two"], "Content-Type": "text/html"},
    )
    assert redacted["Set-Cookie"] == [REDACTED, REDACTED]
    assert redacted["Content-Type"] == "text/html"


def test_redact_header_pairs_keeps_duplicates_and_order() -> None:
    pairs = [("Set-Cookie", "a=1"), ("Set-Cookie", "b=2"), ("Server", "nginx")]
    assert redact_header_pairs(pairs) == [
        ("Set-Cookie", REDACTED),
        ("Set-Cookie", REDACTED),
        ("Server", "nginx"),
    ]


def test_non_sensitive_header_values_are_still_scrubbed() -> None:
    """A Location header can carry a signed URL; the value is not exempt."""
    redacted = redact_headers({"Location": "https://example.com/callback?access_token=live-token-value"})
    assert "live-token-value" not in redacted["Location"]


# --- cookies ----------------------------------------------------------------------


def test_multiple_set_cookie_headers_retain_names_never_values() -> None:
    evidence = parse_set_cookie_evidence(
        [
            "SESSIONID=super-secret-session; Path=/; Secure; HttpOnly; SameSite=Lax",
            "csrftoken=another-secret; Path=/; Max-Age=3600",
        ],
        digest=DIGEST,
    )
    assert [item.name for item in evidence] == ["SESSIONID", "csrftoken"]
    rendered = repr([item.export() for item in evidence])
    assert "super-secret-session" not in rendered
    assert "another-secret" not in rendered
    assert evidence[0].secure and evidence[0].http_only and evidence[0].same_site == "Lax"
    assert evidence[1].has_expiry is True
    assert evidence[1].secure is False


def test_set_cookie_value_digest_is_keyed_and_stable() -> None:
    first = parse_set_cookie_evidence(["a=1234"], digest=DIGEST)[0]
    second = parse_set_cookie_evidence(["b=1234"], digest=DIGEST)[0]
    other_run = CorrelationDigest.from_key(b"a-different-key-0123456789abcdef", run_id="run-other")
    third = parse_set_cookie_evidence(["a=1234"], digest=other_run)[0]
    assert first.value_digest == second.value_digest
    assert first.value_digest != third.value_digest


def test_set_cookie_header_without_a_pair_is_skipped() -> None:
    assert parse_set_cookie_evidence(["Secure; HttpOnly"], digest=DIGEST) == ()


# --- correlation digests -------------------------------------------------------------


def test_digest_is_domain_separated() -> None:
    assert DIGEST.digest("1234", domain="url") != DIGEST.digest("1234", domain="cookie-value")


def test_digest_is_not_a_plain_sha256_of_the_value() -> None:
    """A low-entropy value must not be recoverable by hashing a guess."""
    import hashlib

    assert DIGEST.digest("1234") != f"hmac-sha256:{hashlib.sha256(b'1234').hexdigest()[:32]}"


def test_per_run_digest_keys_differ() -> None:
    assert CorrelationDigest.for_run("a").key != CorrelationDigest.for_run("b").key


def test_short_digest_keys_are_refused() -> None:
    with pytest.raises(ValueError, match="at least 16 bytes"):
        CorrelationDigest.from_key(b"short")


# --- URL projection -----------------------------------------------------------------


def test_userinfo_is_removed_unconditionally() -> None:
    projection = project_url("https://alice:hunter2@example.com/page", digest=DIGEST)
    assert projection.redacted == "https://example.com/page"
    assert projection.had_userinfo is True
    assert "hunter2" not in projection.redacted


def test_sensitive_query_values_are_redacted_and_names_kept() -> None:
    projection = project_url(
        "https://example.com/p?utm_source=news&token=abc123&page=2",
        digest=DIGEST,
    )
    assert projection.redacted == f"https://example.com/p?utm_source=news&token={REDACTED}&page=2"
    assert projection.redacted_query_keys == ("token",)


def test_repeated_sensitive_keys_are_each_redacted() -> None:
    projection = project_url("https://example.com/?code=one&code=two", digest=DIGEST)
    assert projection.redacted == f"https://example.com/?code={REDACTED}&code={REDACTED}"
    assert projection.redacted_query_keys == ("code", "code")


def test_percent_encoded_key_is_matched_after_decoding() -> None:
    redacted, keys = redact_query_string("access%5Ftoken=abc&safe=1")
    assert redacted == f"access%5Ftoken={REDACTED}&safe=1"
    assert keys == ("access_token",)


def test_non_sensitive_percent_encoding_is_preserved_byte_for_byte() -> None:
    redacted, keys = redact_query_string("q=caf%C3%A9%20noir&sort=asc")
    assert redacted == "q=caf%C3%A9%20noir&sort=asc"
    assert keys == ()


def test_unicode_query_key_and_value_survive() -> None:
    projection = project_url("https://example.com/?поиск=кофе", digest=DIGEST)
    assert projection.redacted == "https://example.com/?поиск=кофе"


def test_bare_flag_parameter_is_left_alone() -> None:
    redacted, keys = redact_query_string("debug&token=x")
    assert redacted == f"debug&token={REDACTED}"
    assert keys == ("token",)


def test_fragment_presence_is_kept_but_content_removed() -> None:
    projection = project_url("https://example.com/#access_token=live", digest=DIGEST)
    assert projection.redacted == f"https://example.com/#{REDACTED}"
    assert projection.had_fragment is True


def test_low_entropy_sensitive_value_is_removed_not_hashed_in_place() -> None:
    projection = project_url("https://example.com/?pin=1234", digest=DIGEST)
    assert "1234" not in projection.redacted


def test_ambiguous_key_names_are_not_over_redacted() -> None:
    projection = project_url("https://example.com/?postcode=SW1A&keyword=shoes", digest=DIGEST)
    assert projection.redacted == "https://example.com/?postcode=SW1A&keyword=shoes"


def test_raw_url_identity_survives_projection() -> None:
    """The projection is additive: the raw crawl identity is never rewritten."""
    raw = "https://example.com/p?token=alpha"
    projection = project_url(raw, digest=DIGEST)
    assert projection.raw == raw
    assert projection.redacted != raw


def test_urls_differing_only_in_a_secret_stay_distinct_records() -> None:
    """Redacting a frontier key in place would merge these two into one."""
    first = project_url("https://example.com/p?token=alpha", digest=DIGEST)
    second = project_url("https://example.com/p?token=beta", digest=DIGEST)
    assert first.redacted == second.redacted
    assert first.raw != second.raw
    assert first.digest != second.digest


def test_projection_repr_does_not_leak_the_raw_url() -> None:
    projection = project_url("https://example.com/?token=leaky-token-value", digest=DIGEST)
    assert "leaky-token-value" not in repr(projection)
    assert "leaky-token-value" not in repr(projection.export())


def test_malformed_url_projects_to_the_redaction_marker() -> None:
    projection = project_url("http://[::1", digest=DIGEST)
    assert projection.redacted == REDACTED


# --- free text ------------------------------------------------------------------------


def test_registered_secret_is_removed_verbatim(registry: SecretRegistry) -> None:
    registry.register("s3cr3t-value-from-env", label="auth-token")
    assert "s3cr3t" not in scrub_text("token was s3cr3t-value-from-env", registry=registry)
    assert registry.labels() == ("auth-token",)


def test_registry_never_exposes_values(registry: SecretRegistry) -> None:
    registry.register("s3cr3t-value-from-env", label="auth-token")
    assert "s3cr3t" not in repr(registry)
    assert "s3cr3t" not in str(registry.labels())


def test_registry_ignores_trivially_short_values(registry: SecretRegistry) -> None:
    registry.register("ab")
    assert len(registry) == 0


def test_registry_covers_url_encoded_and_base64_forms(registry: SecretRegistry) -> None:
    registry.register_basic_credentials("alice", "p@ssword-value")
    assert "p@ssword-value" not in scrub_text("url is https://x/?p=p%40ssword-value", registry=registry)
    assert REDACTED in scrub_text("Authorization: Basic YWxpY2U6cEBzc3dvcmQtdmFsdWU=", registry=registry)


@pytest.mark.parametrize(
    "text,forbidden",
    [
        ("Authorization: Bearer eyJhbGciOi.payload123.signature456", "signature456"),
        ("Set-Cookie: sid=very-secret-session; Path=/", "very-secret-session"),
        ("Cookie: sid=very-secret-session; other=1", "very-secret-session"),
        ("postgresql://crawler:dbpassword@db:5432/crawl", "dbpassword"),
        ("http://proxyuser:proxypass@proxy.example:8080", "proxypass"),
        ("password=hunter2000", "hunter2000"),
        ("csrf_token=abc123def", "abc123def"),
        ("AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
        (
            "-----BEGIN RSA PRIVATE KEY-----\nMIIkeymaterial\n-----END RSA PRIVATE KEY-----",
            "MIIkeymaterial",
        ),
    ],
)
def test_pattern_scrubbing_removes_credential_shapes(text: str, forbidden: str) -> None:
    assert forbidden not in scrub_text(text)


def test_email_addresses_are_redacted_in_text() -> None:
    assert scrub_text("contact person@example.org") == f"contact {REDACTED_EMAIL}"


def test_email_redaction_can_be_disabled_by_policy() -> None:
    policy = RedactionPolicy(redact_emails_in_text=False)
    assert "person@example.org" in scrub_text("contact person@example.org", policy=policy)


def test_scrub_structure_redacts_by_key_and_recurses() -> None:
    payload = {
        "headers": {"Authorization": "Bearer live", "Server": "nginx"},
        "items": [{"session": "abc"}, "password=zzz123"],
        "count": 3,
    }
    scrubbed = scrub_structure(payload)
    assert scrubbed["headers"]["Authorization"] == REDACTED
    assert scrubbed["headers"]["Server"] == "nginx"
    assert scrubbed["items"][0]["session"] == REDACTED
    assert "zzz123" not in scrubbed["items"][1]
    assert scrubbed["count"] == 3


# --- connection strings --------------------------------------------------------------


def test_sanitize_dsn_removes_credentials() -> None:
    assert sanitize_dsn("postgresql://user:pw@host:5432/db") == f"postgresql://{REDACTED}@host:5432/db"


def test_sanitize_dsn_leaves_credential_free_dsn_alone() -> None:
    assert sanitize_dsn("postgresql://host:5432/db") == "postgresql://host:5432/db"


def test_sanitize_proxy_url_removes_credentials() -> None:
    assert sanitize_proxy_url("http://u:p@proxy:8080") == f"http://{REDACTED}@proxy:8080"


# --- form fields ------------------------------------------------------------------------


def test_form_fields_keep_names_and_drop_values() -> None:
    rendered = redact_form_fields({"csrf": "token-value-here", "empty": ""})
    assert rendered[0] == {"name": "csrf", "has_value": True, "value_length": 16}
    assert rendered[1]["has_value"] is False
    assert "token-value-here" not in repr(rendered)


# --- snippets ----------------------------------------------------------------------------


def test_snippet_respects_the_line_cap() -> None:
    snippet = bounded_snippet("one\ntwo\nthree\nfour", max_lines=2)
    assert snippet.text == "one\ntwo"
    assert snippet.truncated is True


def test_snippet_respects_the_byte_cap() -> None:
    snippet = bounded_snippet("x" * 500, max_bytes=32)
    assert len(snippet.text.encode("utf-8")) <= 32
    assert snippet.truncated is True
    assert snippet.source_bytes == 500


def test_snippet_byte_cap_does_not_split_a_multibyte_character() -> None:
    snippet = bounded_snippet("é" * 100, max_bytes=15)
    assert snippet.text == "é" * 7


def test_snippet_normalises_whitespace_and_scrubs() -> None:
    snippet = bounded_snippet("  token   =   abc123xyz   ")
    assert "abc123xyz" not in snippet.text
    assert "   " not in snippet.text


def test_snippet_falls_back_to_a_digest_when_a_known_secret_is_present(registry: SecretRegistry) -> None:
    registry.register("known-secret-material", label="auth-token")
    snippet = bounded_snippet("page said known-secret-material here", registry=registry)
    assert snippet.text == ""
    assert snippet.reason == "registered_secret_present"
    assert len(snippet.source_sha256) == 64


# --- exceptions ----------------------------------------------------------------------------


def test_redact_exception_names_the_type_and_scrubs_the_message() -> None:
    exc = ValueError("failed for token=live-token-value")
    rendered = redact_exception(exc)
    assert rendered.startswith("ValueError: ")
    assert "live-token-value" not in rendered


def test_redact_traceback_scrubs_every_frame(registry: SecretRegistry) -> None:
    registry.register("frame-local-secret", label="test")

    def inner() -> None:
        raise RuntimeError("boom with postgresql://u:frame-local-secret@db/x")

    try:
        inner()
    except RuntimeError as exc:
        rendered = redact_traceback(exc)
    assert "Traceback" in rendered
    assert "frame-local-secret" not in rendered


def test_missing_secret_message_names_the_source_not_the_value() -> None:
    message = missing_secret_message("auth-token", source="CRAWLER_TEST_TOKEN")
    assert "CRAWLER_TEST_TOKEN" in message
    assert "auth-token" in message


# --- structured logging ----------------------------------------------------------------------


def test_log_filter_scrubs_message_arguments_and_extras(caplog) -> None:
    logger = logging.getLogger("crawler_cli.tests.redaction.records")
    install_log_redaction(logger)
    caplog.set_level(logging.DEBUG)
    logger.warning(
        "fetch failed for %s",
        "https://example.com/?token=argv-free-secret",
        extra={"dsn": "postgresql://u:dbsecret@host/db", "headers": {"Authorization": "Bearer live-token"}},
    )
    record = caplog.records[-1]
    assert "argv-free-secret" not in caplog.text
    assert "dbsecret" not in str(record.dsn)
    assert record.headers["Authorization"] == REDACTED


def test_log_filter_scrubs_exception_tracebacks(caplog) -> None:
    logger = logging.getLogger("crawler_cli.tests.redaction.exceptions")
    install_log_redaction(logger)
    caplog.set_level(logging.DEBUG)
    try:
        raise RuntimeError("connect failed: postgresql://u:log-dsn-secret@db/x")
    except RuntimeError:
        logger.exception("backend startup failed")
    assert "log-dsn-secret" not in caplog.text
    assert caplog.records[-1].exc_info is None


# --- CSV hygiene ---------------------------------------------------------------------------------


@pytest.mark.parametrize("payload", ["=1+1", "+1+1", "-1+1", "@SUM(A1)", "\tformula"])
def test_csv_formula_prefixes_are_neutralised(payload: str) -> None:
    assert csv_safe_cell(payload) == "'" + payload


def test_csv_cell_folds_embedded_carriage_returns() -> None:
    assert csv_safe_cell("a\r\nb\rc\nd") == "a b c d"


def test_csv_cell_neutralises_a_formula_hidden_behind_a_carriage_return() -> None:
    assert csv_safe_cell("\r=cmd|'/c calc'!A1") == "' =cmd|'/c calc'!A1"


def test_csv_cell_leaves_numbers_and_plain_text_alone() -> None:
    assert csv_safe_cell(-3) == -3
    assert csv_safe_cell(2.5) == 2.5
    assert csv_safe_cell("https://example.com/") == "https://example.com/"
    assert csv_safe_cell("") == ""


def test_csv_safe_row_applies_to_every_value() -> None:
    row = csv_safe_row({"title": "=HYPERLINK(1)", "count": 4})
    assert row == {"title": "'=HYPERLINK(1)", "count": 4}
