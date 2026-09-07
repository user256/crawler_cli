"""Address-class policy tests (ticket 149).

The cases that unwrap an embedded address are the point of this suite. Several
address forms are reported as acceptable by ``ipaddress`` while carrying a
forbidden address, so a classifier written against ``is_global`` /
``is_loopback`` / ``is_private`` alone passes a naive review and still lets
loopback through.
"""

from __future__ import annotations

import ipaddress
import socket

import pytest

from crawler_cli.destination_policy import (
    REASON_DENIED_HOSTNAME,
    REASON_LINK_LOCAL,
    REASON_LOOPBACK,
    REASON_METADATA,
    REASON_MIXED_ANSWER,
    REASON_MULTICAST,
    REASON_PRIVATE,
    REASON_RESERVED,
    REASON_TRANSLATED,
    REASON_UNSPECIFIED,
    REASON_UNSUPPORTED_LITERAL,
    REASON_UNSUPPORTED_SCHEME,
    DestinationPolicy,
    DestinationRejection,
    classify_address,
    normalize_destination_url,
    resolve_destination,
    select_permitted_address,
)

DEFAULT = DestinationPolicy()
PRIVATE_ALLOWED = DestinationPolicy(allow_private_network=True)


@pytest.mark.parametrize(
    ("address", "reason"),
    [
        # Plain forbidden classes.
        ("127.0.0.1", REASON_LOOPBACK),
        ("::1", REASON_LOOPBACK),
        ("0.0.0.0", REASON_UNSPECIFIED),
        ("::", REASON_UNSPECIFIED),
        ("10.0.0.8", REASON_PRIVATE),
        ("172.16.0.1", REASON_PRIVATE),
        ("192.168.1.1", REASON_PRIVATE),
        ("fd00::1", REASON_PRIVATE),
        ("fe80::1", REASON_LINK_LOCAL),
        ("224.0.0.1", REASON_MULTICAST),
        ("ff02::1", REASON_MULTICAST),
        # Ranges ipaddress calls "private" that the private exception must not
        # widen to: reserved-for-future-use, CGNAT, documentation, benchmarking.
        ("240.0.0.1", REASON_RESERVED),
        ("100.64.0.1", REASON_RESERVED),
        ("192.0.2.5", REASON_RESERVED),
        ("203.0.113.5", REASON_RESERVED),
        ("198.18.0.1", REASON_RESERVED),
        ("2001:db8::1", REASON_RESERVED),
        # Metadata endpoints, which need naming rather than inferring.
        ("169.254.169.254", REASON_METADATA),
        ("169.254.170.2", REASON_METADATA),
        ("100.100.100.200", REASON_METADATA),
        ("192.0.0.192", REASON_METADATA),
    ],
)
def test_forbidden_classes_are_denied_with_their_specific_reason(address, reason):
    assert classify_address(address, DEFAULT) == reason


@pytest.mark.parametrize("address", ["93.184.216.34", "1.1.1.1", "2606:4700:4700::1111"])
def test_globally_routable_addresses_are_permitted(address):
    assert classify_address(address, DEFAULT) is None


@pytest.mark.parametrize(
    ("address", "note"),
    [
        ("::ffff:127.0.0.1", "IPv4-mapped loopback: ipaddress reports is_loopback False"),
        ("::ffff:10.0.0.1", "IPv4-mapped private"),
        ("::ffff:169.254.169.254", "IPv4-mapped metadata"),
        ("64:ff9b::7f00:1", "NAT64 loopback: ipaddress reports is_global True"),
        ("64:ff9b::a00:1", "NAT64 private"),
        ("2002:7f00:1::1", "6to4 loopback"),
    ],
)
def test_embedded_addresses_are_unwrapped_and_denied(address, note):
    assert classify_address(address, DEFAULT) is not None, note


def test_nat64_wrapping_loopback_is_reported_as_globally_routable_by_the_stdlib():
    """Guard the assumption this module exists to defeat.

    If a future Python starts classifying the NAT64 prefix correctly this test
    fails loudly, which is the moment to revisit the unwrapping code — not to
    silently keep a redundant check.
    """
    assert ipaddress.ip_address("64:ff9b::7f00:1").is_global is True
    assert ipaddress.ip_address("::ffff:127.0.0.1").is_loopback is False
    assert classify_address("64:ff9b::7f00:1", DEFAULT) == REASON_TRANSLATED


def test_private_exception_widens_only_the_private_tier():
    assert classify_address("10.0.0.8", PRIVATE_ALLOWED) is None
    assert classify_address("fd00::1", PRIVATE_ALLOWED) is None
    # Everything else stays denied even with the exception in force. The
    # documentation, benchmarking, CGNAT and reserved ranges matter here:
    # ipaddress reports several of them as private, so an exception written
    # against is_private would quietly reach all of them.
    for address in (
        "127.0.0.1",
        "169.254.169.254",
        "fd00:ec2::254",
        "224.0.0.1",
        "0.0.0.0",
        "240.0.0.1",
        "100.64.0.1",
        "192.0.2.5",
        "203.0.113.5",
        "2001:db8::1",
    ):
        assert classify_address(address, PRIVATE_ALLOWED) is not None, address


def test_stdlib_is_private_is_broader_than_the_exception_this_module_grants():
    """Document why the private tier is an explicit list, not `is_private`."""
    for address in ("240.0.0.1", "192.0.2.5", "203.0.113.5", "198.18.0.1", "2001:db8::1"):
        assert ipaddress.ip_address(address).is_private is True, address
        assert classify_address(address, PRIVATE_ALLOWED) == REASON_RESERVED, address


def test_ipv6_instance_metadata_is_denied_despite_the_private_exception():
    """fd00:ec2::254 sits inside fc00::/7 and is not link-local."""
    assert ipaddress.ip_address("fd00:ec2::254").is_private is True
    assert ipaddress.ip_address("fd00:ec2::254").is_link_local is False
    assert classify_address("fd00:ec2::254", PRIVATE_ALLOWED) == REASON_METADATA


def test_explicit_cidr_allowlist_permits_only_the_named_range():
    policy = DestinationPolicy(allow_networks=(ipaddress.ip_network("10.1.0.0/16"),))
    assert classify_address("10.1.2.3", policy) is None
    assert classify_address("10.2.2.3", policy) == REASON_PRIVATE


def test_unparseable_address_is_denied_rather_than_assumed_safe():
    assert classify_address("not-an-address", DEFAULT) == REASON_UNSUPPORTED_LITERAL


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hostname", ["0177.0.0.1", "2130706433", "0x7f.1"])
def test_alternate_ip_literal_spellings_are_rejected(hostname):
    """Each of these resolves to 127.0.0.1 through getaddrinfo."""
    assert socket.getaddrinfo(hostname, 80)[0][4][0] == "127.0.0.1"
    with pytest.raises(DestinationRejection) as excinfo:
        normalize_destination_url(f"http://{hostname}/")
    assert excinfo.value.reason == REASON_UNSUPPORTED_LITERAL


@pytest.mark.parametrize("hostname", ["localhost", "foo.localhost", "metadata.google.internal", "box.internal"])
def test_denied_hostnames_are_rejected_before_any_resolution(hostname):
    with pytest.raises(DestinationRejection) as excinfo:
        normalize_destination_url(f"http://{hostname}/")
    assert excinfo.value.reason == REASON_DENIED_HOSTNAME


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://example.com/", "ftp://example.com/"])
def test_non_http_schemes_are_rejected(url):
    with pytest.raises(DestinationRejection) as excinfo:
        normalize_destination_url(url)
    assert excinfo.value.reason == REASON_UNSUPPORTED_SCHEME


def test_userinfo_is_rejected():
    with pytest.raises(DestinationRejection):
        normalize_destination_url("http://user:pass@example.com/")


def test_trailing_dot_and_case_are_normalized():
    _url, hostname, port = normalize_destination_url("https://Example.COM./path")
    assert hostname == "example.com"
    assert port == 443


def test_default_ports_follow_the_scheme():
    assert normalize_destination_url("http://example.com/")[2] == 80
    assert normalize_destination_url("https://example.com/")[2] == 443
    assert normalize_destination_url("http://example.com:8080/")[2] == 8080


def test_canonical_literals_are_still_accepted():
    assert normalize_destination_url("http://93.184.216.34/")[1] == "93.184.216.34"


# ---------------------------------------------------------------------------
# Answer-set selection — the DNS rebinding boundary
# ---------------------------------------------------------------------------


def test_all_public_answer_set_pins_the_first_address():
    assert select_permitted_address(["93.184.216.34", "1.1.1.1"], DEFAULT) == "93.184.216.34"


def test_mixed_answer_set_fails_closed_as_a_unit():
    """Carried from tests/test_portal_adapter.py on feature/3350.

    Narrowing a mixed set to its public member would leave the rebinding
    primitive the guard exists to remove.
    """
    with pytest.raises(DestinationRejection) as excinfo:
        select_permitted_address(["93.184.216.34", "10.0.0.8"], DEFAULT)
    assert excinfo.value.reason == REASON_MIXED_ANSWER


def test_wholly_denied_answer_set_reports_the_underlying_reason():
    with pytest.raises(DestinationRejection) as excinfo:
        select_permitted_address(["127.0.0.1"], DEFAULT)
    assert excinfo.value.reason == REASON_LOOPBACK


def test_empty_answer_set_is_denied():
    with pytest.raises(DestinationRejection):
        select_permitted_address([], DEFAULT)


@pytest.mark.asyncio
async def test_resolution_failure_is_a_typed_rejection(monkeypatch):
    async def fail(*_args, **_kwargs):
        raise socket.gaierror("no such host")

    monkeypatch.setattr("asyncio.get_running_loop", lambda: type("L", (), {"getaddrinfo": staticmethod(fail)})())
    with pytest.raises(DestinationRejection) as excinfo:
        await resolve_destination("nonexistent.invalid", 80)
    assert excinfo.value.reason == "unresolvable_host"


@pytest.mark.asyncio
async def test_resolution_returns_the_complete_deduplicated_answer_set(monkeypatch):
    async def resolve(*_args, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 80)),
        ]

    monkeypatch.setattr("asyncio.get_running_loop", lambda: type("L", (), {"getaddrinfo": staticmethod(resolve)})())
    assert await resolve_destination("example.com", 80) == ["10.0.0.8", "93.184.216.34"]
