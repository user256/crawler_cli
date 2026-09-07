"""Built-in destination-address policy for ordinary crawls (ticket 149).

This module answers one question: may the crawler open a connection to this
IP address?  It protects the machine running the crawler and the networks that
machine can reach.  It is not a target-side SSRF scanner.

It is deliberately separate from :mod:`crawler_cli.portal_policy`, which is the
seam an external Portal deployment plugs into.  That module owns the
*mechanism* — ``PinnedConnection`` and the per-hop pinned fetch loop in
``backends`` — and delegates the *decision* to Portal.  This module supplies a
built-in decision for every crawl that has no Portal policy, so ordinary
crawling is guarded by default rather than only under a Portal deployment.

Everything here is pure apart from :func:`resolve_destination`, so the policy
can be exhaustively tested without a network.

Three rules shape the design:

* **Deny by class, then unwrap.**  Several address forms embed a forbidden
  address inside one that the standard library reports as acceptable, so the
  classifier unwraps IPv4-mapped, NAT64 and 6to4 addresses and re-classifies
  the address they carry.  ``ipaddress`` reports ``64:ff9b::7f00:1`` as
  globally routable; it is ``127.0.0.1`` behind a NAT64 gateway.
* **Fail closed on a mixed answer set.**  If any address a hostname resolves
  to is denied, the whole name is denied.  Selecting the permitted member
  would leave a DNS-rebinding primitive intact.
* **One normalization path.**  Ambiguous address literals are rejected here
  rather than being handed to the resolver and caught by luck on the far side.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

# Rejection reasons. These are stable identifiers: they are recorded in crawl
# artifacts and matched by tests, so they are part of the contract.
REASON_LOOPBACK = "loopback"
REASON_PRIVATE = "private_address"
REASON_LINK_LOCAL = "link_local"
REASON_METADATA = "metadata_address"
REASON_RESERVED = "reserved_address"
REASON_MULTICAST = "multicast_address"
REASON_UNSPECIFIED = "unspecified_address"
REASON_TRANSLATED = "translated_address"
REASON_MIXED_ANSWER = "mixed_dns_answer"
REASON_UNRESOLVABLE = "unresolvable_host"
REASON_DENIED_HOSTNAME = "denied_hostname"
REASON_UNSUPPORTED_LITERAL = "unsupported_address_literal"
REASON_UNSUPPORTED_SCHEME = "unsupported_scheme"
REASON_MALFORMED_URL = "malformed_url"

# NAT64 (RFC 6052) and 6to4 (RFC 3056) carry an IPv4 address inside an IPv6
# one. `ipaddress` classifies the outer address, which is why the well-known
# NAT64 prefix reports as globally routable while wrapping loopback.
_NAT64_PREFIXES: tuple[IPNetwork, ...] = (
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("64:ff9b:1::/48"),
)
_SIX_TO_FOUR = ipaddress.ip_network("2002::/16")

# Cloud instance-metadata endpoints. `is_link_local` already covers
# 169.254.169.254, but not the IPv6 or Alibaba endpoints, and the IPv6 one sits
# inside fc00::/7 so a private-network exception would otherwise permit it.
_METADATA_ADDRESSES: frozenset[str] = frozenset(
    {
        "169.254.169.254",  # AWS, GCP, Azure, DigitalOcean, OpenStack
        "169.254.170.2",  # AWS ECS task metadata
        "fd00:ec2::254",  # AWS IPv6 instance metadata
        "100.100.100.200",  # Alibaba Cloud
        "192.0.0.192",  # Oracle Cloud
    }
)

# The private tier that --allow-private-network widens, named explicitly.
# `is_private` is deliberately NOT used for this: it also covers documentation
# (192.0.2.0/24, 203.0.113.0/24, 2001:db8::/32), benchmarking (198.18.0.0/15)
# and reserved-for-future-use (240.0.0.0/4) ranges. Widening the exception to
# those would let an operator who wanted their own LAN reach ranges they never
# asked for, so those stay denied as reserved whatever the exception says.
_EXPLICIT_PRIVATE_NETWORKS: tuple[IPNetwork, ...] = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)

_DENIED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)

_DENIED_HOSTNAME_SUFFIXES: tuple[str, ...] = (".localhost", ".local", ".internal")

_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Longer than any hostname the crawler should follow, and short enough to keep
# a hostile redirect chain from becoming a memory problem.
_MAX_URL_LENGTH = 2048


class DestinationRejection(RuntimeError):
    """Raised when the destination policy denies an address or hostname.

    ``reason`` is one of the ``REASON_*`` identifiers. Callers record it rather
    than the message, so a denial is machine-readable in crawl artifacts.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass(frozen=True, slots=True)
class DestinationPolicy:
    """Which address classes this crawl may connect to.

    The default denies every address that is not globally routable. Loopback,
    link-local, metadata, multicast, reserved and unspecified addresses stay
    denied whatever else is set: ``allow_private_network`` widens the private
    tier only, and never reopens the always-denied tier.
    """

    allow_private_network: bool = False
    allow_networks: tuple[IPNetwork, ...] = field(default_factory=tuple)

    def permits_network(self, ip: IPAddress) -> bool:
        """Return whether an operator explicitly allowlisted *ip*."""
        return any(ip in network for network in self.allow_networks if ip.version == network.version)


def _unwrap_embedded(ip: IPAddress) -> IPAddress | None:
    """Return the IPv4 address embedded in *ip*, if it carries one.

    IPv4-mapped, NAT64 and 6to4 addresses all wrap an IPv4 address that the
    outer address's own classification ignores.
    """
    if not isinstance(ip, ipaddress.IPv6Address):
        return None
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    for prefix in _NAT64_PREFIXES:
        if ip in prefix:
            # The IPv4 address occupies the final 32 bits of the /96 form.
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if ip in _SIX_TO_FOUR:
        # 2002:V4ADDR::/48 — the address sits in bits 16..48.
        return ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF)
    return None


def _classify_plain(ip: IPAddress) -> str | None:
    """Classify one address that is known to embed no other address."""
    if ip.is_unspecified:
        return REASON_UNSPECIFIED
    if ip.is_loopback:
        return REASON_LOOPBACK
    if str(ip) in _METADATA_ADDRESSES:
        return REASON_METADATA
    if ip.is_link_local:
        return REASON_LINK_LOCAL
    if ip.is_multicast:
        return REASON_MULTICAST
    if any(ip in network for network in _EXPLICIT_PRIVATE_NETWORKS if ip.version == network.version):
        return REASON_PRIVATE
    if ip.is_reserved:
        return REASON_RESERVED
    if ip.is_global:
        return None
    # Anything the standard library will not call globally routable and that
    # matched no class above (carrier-grade NAT, for one) stays denied.
    return REASON_RESERVED


def classify_address(address: str | IPAddress, policy: DestinationPolicy) -> str | None:
    """Return the reason *address* is denied, or ``None`` when it is permitted.

    Pure and synchronous, so the whole address matrix is unit-testable.
    """
    if isinstance(address, str):
        try:
            ip: IPAddress = ipaddress.ip_address(address)
        except ValueError:
            return REASON_UNSUPPORTED_LITERAL
    else:
        ip = address

    embedded = _unwrap_embedded(ip)
    if embedded is not None:
        # Judge the address that traffic actually reaches. An explicit operator
        # allowlist still applies to the literal address as written.
        if policy.permits_network(ip):
            return None
        inner = _classify_plain(embedded)
        if inner is not None:
            return REASON_TRANSLATED if not isinstance(ip, ipaddress.IPv4Address) else inner
        return None

    reason = _classify_plain(ip)
    if reason is None:
        return None
    if policy.permits_network(ip):
        return None
    if reason == REASON_PRIVATE and policy.allow_private_network:
        return None
    return reason


def normalize_destination_url(raw_url: str) -> tuple[str, str, int]:
    """Return ``(url, hostname, port)`` for a URL the crawler may attempt.

    Rejects everything the address classifier could not later judge reliably:
    non-HTTP schemes, userinfo, absent hosts, out-of-range ports, denied
    hostnames, and ambiguous IP literal spellings such as ``0177.0.0.1`` or
    ``2130706433``, both of which resolve to ``127.0.0.1``.
    """
    if len(raw_url) > _MAX_URL_LENGTH:
        raise DestinationRejection(REASON_MALFORMED_URL, "URL exceeds the maximum length")
    try:
        parts = urlsplit(raw_url)
    except ValueError as exc:
        raise DestinationRejection(REASON_MALFORMED_URL, str(exc)) from exc

    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise DestinationRejection(REASON_UNSUPPORTED_SCHEME, scheme or "missing")
    if parts.username or parts.password:
        raise DestinationRejection(REASON_MALFORMED_URL, "URL carries userinfo")

    try:
        hostname = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise DestinationRejection(REASON_MALFORMED_URL, str(exc)) from exc
    if not hostname:
        raise DestinationRejection(REASON_MALFORMED_URL, "URL has no host")

    hostname = hostname.rstrip(".").lower()
    if not hostname:
        raise DestinationRejection(REASON_MALFORMED_URL, "URL has no host")
    if "%" in hostname:
        raise DestinationRejection(REASON_UNSUPPORTED_LITERAL, "zone-qualified host")
    if hostname in _DENIED_HOSTNAMES or hostname.endswith(_DENIED_HOSTNAME_SUFFIXES):
        raise DestinationRejection(REASON_DENIED_HOSTNAME, hostname)

    _reject_ambiguous_literal(hostname)
    port = port or (443 if scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise DestinationRejection(REASON_MALFORMED_URL, "port out of range")
    return raw_url, hostname, port


def _reject_ambiguous_literal(hostname: str) -> None:
    """Reject IP literals written in a form ``ipaddress`` will not parse.

    ``getaddrinfo`` accepts octal, decimal and hexadecimal spellings that all
    reach ``127.0.0.1``. Only the canonical dotted-quad and bracketed IPv6
    forms are allowed through, so exactly one parser decides what an address is.
    """
    if hostname.startswith("["):
        return
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        return
    # Not a canonical literal. Anything made only of digits, dots and a hex
    # prefix is an alternate IPv4 spelling rather than a real hostname.
    stripped = hostname.replace(".", "")
    if stripped.isdigit():
        raise DestinationRejection(REASON_UNSUPPORTED_LITERAL, hostname)
    if hostname.startswith("0x") or ".0x" in hostname:
        raise DestinationRejection(REASON_UNSUPPORTED_LITERAL, hostname)


async def resolve_destination(hostname: str, port: int) -> list[str]:
    """Resolve *hostname* to every address it currently answers with.

    The complete answer set is returned so the caller can fail closed on a
    mixed one. This is the only network call in this module.
    """
    loop = asyncio.get_running_loop()
    try:
        records = await loop.getaddrinfo(hostname, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise DestinationRejection(REASON_UNRESOLVABLE, hostname) from exc
    return sorted({str(record[4][0]) for record in records})


def select_permitted_address(answers: list[str], policy: DestinationPolicy) -> str:
    """Return the address to pin, or reject the whole answer set.

    A mixed answer set is denied as a unit. Narrowing it to the permitted
    member would leave the rebinding primitive the guard exists to remove.
    """
    if not answers:
        raise DestinationRejection(REASON_UNRESOLVABLE, "empty answer set")
    reasons = {answer: classify_address(answer, policy) for answer in answers}
    denied = {answer: reason for answer, reason in reasons.items() if reason is not None}
    if denied:
        if len(denied) < len(answers):
            raise DestinationRejection(REASON_MIXED_ANSWER, ", ".join(sorted(denied.values())))
        raise DestinationRejection(sorted(denied.values())[0], "")
    return answers[0]
