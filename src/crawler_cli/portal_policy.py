"""Opt-in, Portal-owned connection policy seam.

The crawler deliberately does not decide whether an origin is safe for a
Portal-managed Migration Manager job.  A Portal policy authorizes every HTTP
connection and returns the single IP address that connection may use.  The
aiohttp backend then uses a one-shot connector with that address pinned, so a
DNS re-resolution or pooled connection cannot bypass the decision.

This hook is intentionally HTTP-only.  Browser navigation, browser
subresources and live comparisons do not implement it and must remain
disabled by callers that require this guard.
"""

from __future__ import annotations

import importlib
import inspect
import ipaddress
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable
from urllib.parse import urlparse


ConnectionPurpose = Literal["initial", "redirect", "sitemap"]


class PortalPolicyError(RuntimeError):
    """Raised when a Portal connection policy denies or misdescribes a URL."""


@dataclass(frozen=True, slots=True)
class PinnedConnection:
    """A policy-approved destination for exactly one HTTP connection.

    ``hostname`` and ``port`` must match the requested URL.  ``address`` must
    be a literal IP address; the crawler uses it instead of resolving the host.
    """

    hostname: str
    port: int
    address: str


@runtime_checkable
class PortalConnectionPolicy(Protocol):
    """Portal-controlled authorization boundary for outbound HTTP connections."""

    async def authorize(self, url: str, purpose: ConnectionPurpose) -> PinnedConnection:
        """Authorize *url* and return its policy-pinned connection target."""


@dataclass(frozen=True, slots=True)
class PortalPolicyCapabilities:
    """Explicit coverage declaration for callers that need the policy hook."""

    connection_guard_protocol: str | None
    initial_url: bool
    http_redirect: bool
    sitemap: bool
    browser_navigation: bool = False
    browser_subresources: bool = False
    live_compare: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "connection_guard_protocol": self.connection_guard_protocol,
            "guarded_paths": {
                "initial_url": self.initial_url,
                "http_redirect": self.http_redirect,
                "sitemap": self.sitemap,
                "browser_navigation": self.browser_navigation,
                "browser_subresources": self.browser_subresources,
                "live_compare": self.live_compare,
            },
        }


def policy_capabilities(policy: PortalConnectionPolicy | None) -> PortalPolicyCapabilities:
    """Return the actual policy coverage, never implied coverage.

    A configured policy covers only the manually followed aiohttp paths.  The
    false browser/live values are deliberate: a caller can fail closed rather
    than accidentally treat an HTTP-only guard as browser protection.
    """

    enabled = policy is not None
    return PortalPolicyCapabilities(
        connection_guard_protocol="portal-url-policy/1" if enabled else None,
        initial_url=enabled,
        http_redirect=enabled,
        sitemap=enabled,
    )


def validate_pinned_connection(url: str, pinned: PinnedConnection) -> None:
    """Reject a policy response that cannot safely represent *url*."""

    if not isinstance(pinned, PinnedConnection):
        raise PortalPolicyError("Policy must return PinnedConnection")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise PortalPolicyError(f"Policy requested for invalid HTTP URL: {url!r}")
    if parsed.username is not None or parsed.password is not None:
        raise PortalPolicyError("Policy does not permit credential-bearing URLs")
    expected_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if pinned.hostname.lower().rstrip(".") != parsed.hostname.lower().rstrip("."):
        raise PortalPolicyError("Policy hostname does not match the requested URL")
    if pinned.port != expected_port:
        raise PortalPolicyError("Policy port does not match the requested URL")
    try:
        approved_address = ipaddress.ip_address(pinned.address)
    except ValueError as exc:
        raise PortalPolicyError("Policy address must be a literal IP address") from exc
    try:
        requested_address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return
    if approved_address != requested_address:
        # aiohttp connects to a literal-IP URL directly and does not invoke its
        # resolver, so accepting a different address here would falsely claim
        # that the connection had been pinned.
        raise PortalPolicyError("Policy address does not match the literal-IP requested URL")


def load_connection_policy(spec: str) -> PortalConnectionPolicy:
    """Load a local ``module:factory`` policy for the normal ``crawl`` command.

    The module is deliberately an operator-installed local integration, not a
    remote callback or a file-descriptor protocol.  Its zero-argument factory
    must return an object implementing the async ``authorize`` method.
    """

    module_name, separator, factory_name = spec.partition(":")
    if not separator or not module_name or not factory_name:
        raise PortalPolicyError("--portal-url-policy must be MODULE:FACTORY")
    try:
        factory = getattr(importlib.import_module(module_name), factory_name)
    except (ImportError, AttributeError) as exc:
        raise PortalPolicyError(f"Unable to load Portal policy {spec!r}") from exc
    if not callable(factory):
        raise PortalPolicyError(f"Portal policy factory {spec!r} is not callable")
    policy = factory()
    authorize = getattr(policy, "authorize", None)
    if not callable(authorize) or not inspect.iscoroutinefunction(authorize):
        raise PortalPolicyError("Portal policy must provide async authorize(url, purpose)")
    return policy
