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

from .portal_policy import PinnedConnection

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
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)

_DENIED_HOSTNAME_SUFFIXES: tuple[str, ...] = ()

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
    Link-local, metadata, multicast, reserved and unspecified addresses stay
    denied whatever else is set. ``allow_private_network`` widens the private
    tier; an exact CIDR may additionally authorize loopback for local crawling.
    """

    allow_private_network: bool = False
    allow_networks: tuple[IPNetwork, ...] = field(default_factory=tuple)

    def permits_network(self, ip: IPAddress) -> bool:
        """Return whether an operator explicitly allowlisted *ip*."""
        return any(ip in network for network in self.allow_networks if ip.version == network.version)


@dataclass(frozen=True, slots=True)
class DestinationCapabilities:
    """What the destination guard actually covers for one run.

    Every field states what is enforced, never what is intended. A caller that
    needs a guarantee reads this and fails closed; ticket 149 forbids printing
    a warning and proceeding.
    """

    guard: str
    initial_url: bool = False
    http_redirect: bool = False
    robots: bool = False
    sitemap: bool = False
    probes: bool = False
    browser_navigation: bool = False
    browser_subresources: bool = False
    connection_pinning: bool = False
    dns_rebinding_safe: bool = False
    remote_dns: bool = False
    browser_url_interception: bool = False
    limitations: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "destination_guard": self.guard,
            "guarded_paths": {
                "initial_url": self.initial_url,
                "http_redirect": self.http_redirect,
                "robots": self.robots,
                "sitemap": self.sitemap,
                "probes": self.probes,
                "browser_navigation": self.browser_navigation,
                "browser_subresources": self.browser_subresources,
            },
            "connection_pinning": self.connection_pinning,
            "dns_rebinding_safe": self.dns_rebinding_safe,
            "remote_dns": self.remote_dns,
            "browser_url_interception": self.browser_url_interception,
            "limitations": list(self.limitations),
        }


def destination_capabilities(
    *, guard: str, backend: str, proxy_configured: bool, portal_policy: bool
) -> DestinationCapabilities:
    """Describe the guard's real coverage, never its intended coverage.

    Three cases deliberately report no coverage rather than partial coverage:

    * a non-aiohttp backend, because the guard is wired only into the aiohttp
      fetch path;
    * a configured proxy, because the proxy resolves the target hostname and
      the crawler's resolver only ever sees the proxy's own address, so a
      hostname target is never classified (a literal-IP target still is);
    * an external Portal policy, which owns the decision instead.

    ``connection_pinning`` is true only for ``pinned``, which re-authorizes and
    pins one approved address per hop through the same one-shot connector the
    Portal path uses. ``resolver`` validates inside resolution instead: that
    closes the check/connect gap without pinning, so it is reported honestly as
    rebinding-safe but not pinning.
    """
    if portal_policy:
        return DestinationCapabilities(guard="portal", limitations=("an external Portal policy owns the decision",))
    if guard == "off":
        return DestinationCapabilities(guard="off", limitations=("the destination guard is disabled",))
    if backend != "aiohttp":
        # A browser rejects disallowed URLs before dispatch, which is real but
        # is not the same guarantee: Chromium resolves DNS in its own process,
        # so a permitted hostname can still reach a denied address. Ticket 149
        # forbids presenting interception as rebinding safety, so the guarded
        # paths stay false and the interception is recorded on its own.
        interception = backend == "playwright"
        limitation = (
            "browser URL interception rejects disallowed URLs before dispatch, but Chromium "
            "resolves DNS itself, so a permitted hostname may still reach a denied address"
            if interception
            else f"the {backend} backend does not implement the destination guard"
        )
        return DestinationCapabilities(
            guard=guard,
            browser_url_interception=interception,
            limitations=(limitation,),
        )
    if proxy_configured:
        return DestinationCapabilities(
            guard=guard,
            remote_dns=True,
            limitations=("a proxy resolves the target hostname, so only literal-IP targets are classified",),
        )
    return DestinationCapabilities(
        guard=guard,
        initial_url=True,
        http_redirect=True,
        robots=True,
        sitemap=True,
        probes=True,
        connection_pinning=guard == "pinned",
        # Both tiers close the check/connect gap: `pinned` fixes the approved
        # address to the socket, and `resolver` validates inside resolution
        # with the DNS cache disabled, so no re-resolution can intervene.
        dns_rebinding_safe=True,
    )


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
        # Judge the address that traffic actually reaches. The allowlist is
        # deliberately limited to direct private/local destinations: allowing
        # the outer translated range would let NAT64 or 6to4 reopen a forbidden
        # inner address unexpectedly.
        inner = _classify_plain(embedded)
        if inner is not None:
            return REASON_TRANSLATED if not isinstance(ip, ipaddress.IPv4Address) else inner
        return None

    reason = _classify_plain(ip)
    if reason is None:
        return None
    # An exact operator allowlist may reopen private and loopback destinations
    # (notably a local fixture/service), but never infrastructure-sensitive or
    # non-unicast classes.
    if reason in {REASON_PRIVATE, REASON_LOOPBACK} and policy.permits_network(ip):
        return None
    if reason == REASON_PRIVATE and policy.allow_private_network and not policy.allow_networks:
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


class DefaultDestinationPolicy:
    """The built-in guard, shaped as a ``PortalConnectionPolicy`` (ticket 149).

    Satisfying that protocol is the whole point: the aiohttp backend already
    re-authorizes and pins every redirect hop for a Portal deployment, so the
    strict tier reuses that loop rather than growing a second one. This class
    supplies only the decision.
    """

    def __init__(self, policy: DestinationPolicy) -> None:
        self._policy = policy

    async def authorize(self, url: str, purpose: str) -> PinnedConnection:
        """Resolve, validate, and return the one address this hop may use."""
        _url, hostname, port = normalize_destination_url(url)
        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            answers = await resolve_destination(hostname, port)
        else:
            # A literal-IP URL is never resolved, so it is its own answer set.
            answers = [str(literal)]
        address = select_permitted_address(answers, self._policy)
        return PinnedConnection(hostname=hostname, port=port, address=address)
