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
from types import SimpleNamespace

import pytest

from crawler_cli import CrawlConfig
from crawler_cli.backends import AiohttpBackend, _GuardedResolver
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


def test_embedded_addresses_are_denied_whatever_the_stdlib_says_about_them():
    """The contract holds regardless of the interpreter's own classification.

    Do not assert fixed ``ipaddress`` values here. ``::ffff:127.0.0.1`` reports
    ``is_loopback`` False on CPython 3.12.3 and True on later patch releases,
    so an assertion on the stdlib's answer fails on some interpreters while the
    behaviour this module guarantees is unchanged. Unwrapping makes the outcome
    independent of which way the interpreter classifies the outer address.
    """
    assert classify_address("64:ff9b::7f00:1", DEFAULT) == REASON_TRANSLATED
    assert classify_address("::ffff:127.0.0.1", DEFAULT) is not None


def test_naive_is_global_check_would_admit_the_nat64_wrapped_loopback():
    """Show why the unwrapping exists, without asserting a stdlib constant."""
    nat64 = ipaddress.ip_address("64:ff9b::7f00:1")
    if nat64.is_global:
        # The interpreter considers it publicly routable; the guard must not.
        assert classify_address(nat64, DEFAULT) == REASON_TRANSLATED


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


def test_private_exception_does_not_reach_documentation_or_reserved_ranges():
    """Why the private tier is an explicit list rather than `is_private`.

    Every address below is reported as private by ``ipaddress`` on the
    interpreters checked, so defining the exception against that attribute
    would quietly grant reach into documentation, benchmarking and
    reserved-for-future-use space.
    """
    for address in ("240.0.0.1", "192.0.2.5", "203.0.113.5", "198.18.0.1", "2001:db8::1"):
        assert classify_address(address, PRIVATE_ALLOWED) == REASON_RESERVED, address


def test_ipv6_instance_metadata_is_denied_despite_the_private_exception():
    """fd00:ec2::254 sits inside fc00::/7, so the exception would reach it."""
    assert ipaddress.ip_address("fd00:ec2::254") in ipaddress.ip_network("fc00::/7")
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


@pytest.mark.parametrize("hostname", ["metadata", "metadata.google.internal", "instance-data"])
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


# ---------------------------------------------------------------------------
# Config surface (ticket 149 step 2)
# ---------------------------------------------------------------------------


def test_guard_is_enabled_by_default():
    config = CrawlConfig()
    assert config.destination_guard == "resolver"
    assert config.allow_private_network is False
    assert config.allow_network_cidrs == ()


def test_enabling_the_resolver_tier_activates_the_policy():
    backend = AiohttpBackend(CrawlConfig(destination_guard="resolver"))
    assert backend._destination_policy() is not None


def test_unknown_guard_tier_is_rejected():
    with pytest.raises(ValueError, match="destination_guard must be"):
        CrawlConfig(destination_guard="strict")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"backend": "playwright", "challenge_escalate_to_browser": False}, "requires the aiohttp backend"),
        (
            {"proxy": "http://proxy.example:8080", "challenge_escalate_to_browser": False},
            "cannot be combined with a proxy",
        ),
        ({"obscura_enabled": True, "challenge_escalate_to_browser": False}, "Obscura backend"),
        ({}, "challenge_escalate_to_browser=False"),
    ],
)
def test_strict_pinned_mode_fails_closed_on_paths_it_cannot_guard(kwargs, match):
    """Strict mode must refuse, not warn, on a path whose sockets it cannot reach."""
    with pytest.raises(ValueError, match=match):
        CrawlConfig(destination_guard="pinned", **kwargs)


def test_strict_pinned_mode_accepts_the_guardable_aiohttp_path():
    config = CrawlConfig(destination_guard="pinned", challenge_escalate_to_browser=False)
    assert config.destination_guard == "pinned"


def test_malformed_allowlist_cidr_is_rejected():
    with pytest.raises(ValueError, match="not a valid network"):
        CrawlConfig(allow_network_cidrs=("10.0.0.0/999",))


@pytest.mark.parametrize("cidr", ["169.254.0.0/16", "224.0.0.0/4"])
def test_allowlist_cannot_reopen_the_always_denied_tier(cidr):
    """The allowlist never reopens infrastructure-sensitive address classes."""
    with pytest.raises(ValueError, match="link-local or multicast"):
        CrawlConfig(allow_network_cidrs=(cidr,))


def test_exact_allowlist_can_authorise_loopback_for_local_crawling():
    config = CrawlConfig(allow_private_network=True, allow_network_cidrs=("127.0.0.0/8",))
    policy = AiohttpBackend(config)._destination_policy()
    assert policy is not None
    assert classify_address("127.0.0.1", policy) is None
    assert normalize_destination_url("http://localhost:3000/")[1] == "localhost"


def test_allowlist_accepts_an_ordinary_private_range():
    config = CrawlConfig(allow_private_network=True, allow_network_cidrs=("10.1.0.0/16",))
    assert config.allow_network_cidrs == ("10.1.0.0/16",)


# ---------------------------------------------------------------------------
# aiohttp resolver tier (ticket 149 step 3)
# ---------------------------------------------------------------------------


class _StubResolver:
    """Stand-in for aiohttp's DefaultResolver returning fixed answers."""

    def __init__(self, addresses: list[str]) -> None:
        self.addresses = addresses
        self.closed = False

    async def resolve(self, host: str, port: int = 0, family: int = 0) -> list[dict[str, object]]:
        return [
            {"hostname": host, "host": address, "port": port, "family": 0, "proto": 0, "flags": 0}
            for address in self.addresses
        ]

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_guarded_resolver_passes_a_wholly_public_answer_through():
    resolver = _GuardedResolver(DEFAULT, _StubResolver(["93.184.216.34"]))
    hosts = await resolver.resolve("example.com", 80)
    assert [entry["host"] for entry in hosts] == ["93.184.216.34"]


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.8", "169.254.169.254", "64:ff9b::7f00:1"])
async def test_guarded_resolver_denies_a_forbidden_answer(address):
    resolver = _GuardedResolver(DEFAULT, _StubResolver([address]))
    with pytest.raises(DestinationRejection):
        await resolver.resolve("evil.example", 80)


@pytest.mark.asyncio
async def test_guarded_resolver_denies_a_rebinding_answer_set_as_a_unit():
    """A name answering with both a public and a private address is denied."""
    resolver = _GuardedResolver(DEFAULT, _StubResolver(["93.184.216.34", "10.0.0.8"]))
    with pytest.raises(DestinationRejection) as excinfo:
        await resolver.resolve("rebind.example", 80)
    assert excinfo.value.reason == REASON_MIXED_ANSWER


@pytest.mark.asyncio
async def test_guarded_resolver_closes_the_resolver_it_wraps():
    inner = _StubResolver(["93.184.216.34"])
    await _GuardedResolver(DEFAULT, inner).close()
    assert inner.closed is True


@pytest.mark.parametrize("url", ["http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:8000/", "http://[::1]/"])
def test_literal_ip_urls_are_rejected_before_the_request(url):
    """aiohttp connects to a literal-IP URL without consulting a resolver.

    Without this pre-request check the resolver guard never sees these, so the
    metadata endpoint would be reachable despite the guard being active.
    """
    backend = AiohttpBackend(CrawlConfig(destination_guard="resolver"))
    with pytest.raises(DestinationRejection):
        backend._guard_request_url(url)


def test_public_literal_ip_url_is_allowed():
    AiohttpBackend(CrawlConfig(destination_guard="resolver"))._guard_request_url("http://93.184.216.34/")


@pytest.mark.asyncio
async def test_literal_redirect_is_rejected_before_aiohttp_opens_the_next_hop():
    backend = AiohttpBackend(CrawlConfig())
    params = SimpleNamespace(
        response=SimpleNamespace(
            url="https://public.example/start",
            headers={"Location": "http://127.0.0.1/admin"},
        )
    )
    with pytest.raises(DestinationRejection) as excinfo:
        await backend._guard_redirect(None, None, params)  # type: ignore[arg-type]
    assert excinfo.value.reason == REASON_LOOPBACK


def test_guard_stands_down_when_an_external_portal_policy_owns_the_decision():
    class _Policy:
        async def authorize(self, url: str, purpose: str) -> None: ...

    backend = AiohttpBackend(
        CrawlConfig(
            destination_guard="resolver",
            portal_connection_policy=_Policy(),
            challenge_escalate_to_browser=False,
        )
    )
    assert backend._destination_policy() is None
    # The portal policy, not this guard, decides -- so no rejection here.
    backend._guard_request_url("http://127.0.0.1/")


def test_guard_is_absent_when_explicitly_turned_off():
    backend = AiohttpBackend(CrawlConfig(destination_guard="off"))
    assert backend._destination_policy() is None
    backend._guard_request_url("http://127.0.0.1/")


def test_guard_carries_the_operator_allowlist_into_the_policy():
    backend = AiohttpBackend(
        CrawlConfig(
            destination_guard="resolver",
            allow_network_cidrs=("10.1.0.0/16",),
            allow_private_network=True,
        )
    )
    policy = backend._destination_policy()
    assert policy is not None
    assert policy.allow_private_network is True
    assert classify_address("10.1.2.3", policy) is None
    assert classify_address("10.2.2.3", policy) == REASON_PRIVATE
