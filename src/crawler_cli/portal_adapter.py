"""Fail-closed Portal Migration Manager adapter for crawler-cli 0.2.1.

This module is deliberately isolated from the general-purpose crawler
backends.  Portal requires a stronger network boundary: every connection is
resolved, authorised and pinned immediately before the socket is opened.
Native redirect handling and connection pooling are therefore disabled.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import aiohttp
from bs4 import BeautifulSoup
from defusedxml import ElementTree

DISPATCH_SCHEMA = "migration-manager/crawl-dispatch/1"
RESULT_SCHEMA = "migration-manager/run-result/1"
CRAWLER_VERSION = "0.2.1"
CRAWLER_RELEASE = "crawler-cli@v0.2.1"
CRAWLER_ARTIFACT_SCHEMA = "crawler-cli/crawl-artifact/1"
GUARD_PROTOCOL = "portal-url-policy/1"
USER_AGENT = "Portal Migration Manager/1.0 (robots.txt honoured)"
MAX_DISPATCH_BYTES = 1_048_576
MAX_RESPONSE_BYTES = 25 * 1024 * 1024
MAX_REDIRECTS = 10
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
HEX_ID = re.compile(r"^[a-f0-9]{32}$")

CAPABILITIES: dict[str, Any] = {
    "schema_version": 1,
    "crawler_version": CRAWLER_VERSION,
    "crawler_release": CRAWLER_RELEASE,
    "connection_guard_protocol": GUARD_PROTOCOL,
    "guarded_paths": {
        "http_redirect": True,
        "sitemap": True,
        "browser_navigation": True,
        "browser_subresource": True,
        "live_compare": True,
    },
    "path_enforcement": {
        "http_redirect": "resolve-validate-pin-every-hop",
        "sitemap": "resolve-validate-pin-every-connection",
        "browser_navigation": "fail-closed-no-browser-runtime",
        "browser_subresource": "fail-closed-no-browser-runtime",
        "live_compare": "fail-closed-unsupported-operation",
    },
    "capabilities": {
        "crawl_http": True,
        "crawl_browser": False,
        "crawl_embeddings": False,
    },
    "supported_dispatch_schemas": [DISPATCH_SCHEMA],
    "result_schema_version": RESULT_SCHEMA,
}


class AdapterError(Exception):
    """Base error for safe, non-secret diagnostics."""


class DispatchError(AdapterError):
    """The dispatch envelope is invalid or asks for unsupported behaviour."""


class UrlPolicyError(AdapterError):
    """A URL or DNS answer is denied by portal-url-policy/1."""


class FetchError(AdapterError):
    """A guarded HTTP request could not be completed."""


@dataclass(frozen=True)
class TargetPolicy:
    deployment_profile: str
    allow_private_network: bool
    configured_origin: str


@dataclass(frozen=True)
class ValidatedTarget:
    url: str
    hostname: str
    port: int
    origin: str
    pinned_ip: str
    credentials_allowed: bool


@dataclass(frozen=True)
class HttpResponse:
    requested_url: str
    final_url: str
    status: int
    content_type: str | None
    body: bytes
    redirect_chain: list[dict[str, Any]]


@dataclass(frozen=True)
class Dispatch:
    job_id: str
    attempt_id: str
    run_id: str
    target_url: str
    target_policy: TargetPolicy
    max_pages: int
    max_requests: int
    max_bytes: int
    timeout_seconds: int
    discover_sitemaps: bool
    bearer_env: str | None


ResolveHost = Callable[[str, int], Awaitable[list[str]]]
PinnedRequest = Callable[
    [ValidatedTarget, Mapping[str, str], float, int],
    Awaitable[tuple[int, Mapping[str, str], bytes]],
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _origin(parts: Any) -> str:
    scheme = parts.scheme.lower()
    port = parts.port or (443 if scheme == "https" else 80)
    host = parts.hostname or ""
    authority = f"[{host}]" if ":" in host else host
    return f"{scheme}://{authority}:{port}"


def _normalise_url(raw_url: Any) -> str:
    if not isinstance(raw_url, str) or not raw_url.strip() or len(raw_url) > 2048:
        raise UrlPolicyError("Target URL is required and must be at most 2048 bytes.")
    value = raw_url.strip()
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise UrlPolicyError("Target URL is malformed.") from exc
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise UrlPolicyError("Only absolute HTTP(S) URLs are supported.")
    if parts.username is not None or parts.password is not None or parts.fragment:
        raise UrlPolicyError("URL credentials and fragments are forbidden.")
    hostname = parts.hostname.lower().rstrip(".")
    if not hostname or any(char in hostname for char in "/\\"):
        raise UrlPolicyError("Target hostname is malformed.")
    if port is not None and not 1 <= port <= 65535:
        raise UrlPolicyError("Target port is invalid.")
    authority_host = f"[{hostname}]" if ":" in hostname else hostname
    authority = authority_host if port is None else f"{authority_host}:{port}"
    return urlunsplit(
        (
            parts.scheme.lower(),
            authority,
            parts.path or "/",
            parts.query,
            "",
        )
    )


def _is_explicit_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv4Address):
        return (
            ip in ipaddress.ip_network("10.0.0.0/8")
            or ip in ipaddress.ip_network("172.16.0.0/12")
            or ip in ipaddress.ip_network("192.168.0.0/16")
        )
    return ip in ipaddress.ip_network("fc00::/7")


def _ip_allowed(address: str, policy: TargetPolicy) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    # These classes stay forbidden even when an appliance explicitly allows
    # private targets.  In particular, link-local covers cloud metadata ranges.
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return False
    if ip.is_global:
        return True
    return policy.deployment_profile == "appliance" and policy.allow_private_network and _is_explicit_private(ip)


async def _system_resolve(hostname: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        records = await loop.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise UrlPolicyError("Target DNS did not return a usable address.") from exc
    return sorted({record[4][0] for record in records})


async def validate_and_pin(
    raw_url: str,
    policy: TargetPolicy,
    resolve_host: ResolveHost = _system_resolve,
) -> ValidatedTarget:
    url = _normalise_url(raw_url)
    parts = urlsplit(url)
    hostname = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UrlPolicyError("Target hostname is denied by network policy.")
    try:
        literal = ipaddress.ip_address(hostname)
        answers = [str(literal)]
    except ValueError:
        answers = await resolve_host(hostname, port)
    unique_answers = sorted(set(answers))
    if not unique_answers:
        raise UrlPolicyError("Target DNS did not return a usable address.")
    if any(not _ip_allowed(answer, policy) for answer in unique_answers):
        # Mixed public/private answers fail as a unit; selecting only the
        # public member would preserve a DNS rebinding primitive.
        raise UrlPolicyError("Target DNS returned a denied address.")
    origin = _origin(parts)
    return ValidatedTarget(
        url=url,
        hostname=hostname,
        port=port,
        origin=origin,
        pinned_ip=unique_answers[0],
        credentials_allowed=origin == policy.configured_origin,
    )


class _PinnedResolver(aiohttp.abc.AbstractResolver):
    def __init__(self, hostname: str, address: str) -> None:
        self._hostname = hostname
        self._address = address

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[aiohttp.abc.ResolveResult]:
        if host.lower().rstrip(".") != self._hostname:
            raise OSError("Pinned resolver received an unexpected hostname.")
        ip = ipaddress.ip_address(self._address)
        return [
            aiohttp.abc.ResolveResult(
                hostname=host,
                host=self._address,
                port=port,
                family=socket.AF_INET6 if ip.version == 6 else socket.AF_INET,
                proto=socket.IPPROTO_TCP,
                flags=socket.AI_NUMERICHOST,
            )
        ]

    async def close(self) -> None:
        return None


async def _aiohttp_pinned_request(
    target: ValidatedTarget,
    headers: Mapping[str, str],
    timeout_seconds: float,
    max_response_bytes: int,
) -> tuple[int, Mapping[str, str], bytes]:
    resolver = _PinnedResolver(target.hostname, target.pinned_ip)
    connector = aiohttp.TCPConnector(
        resolver=resolver,
        use_dns_cache=False,
        force_close=True,
        limit=1,
    )
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        auto_decompress=True,
    ) as session:
        async with session.get(
            target.url,
            headers=dict(headers),
            allow_redirects=False,
        ) as response:
            chunks: list[bytes] = []
            received = 0
            async for chunk in response.content.iter_chunked(64 * 1024):
                received += len(chunk)
                if received > max_response_bytes:
                    raise FetchError("Response exceeded the configured byte limit.")
                chunks.append(chunk)
            return response.status, dict(response.headers), b"".join(chunks)


class SafeHttpClient:
    def __init__(
        self,
        policy: TargetPolicy,
        *,
        resolve_host: ResolveHost = _system_resolve,
        request_pinned: PinnedRequest = _aiohttp_pinned_request,
        bearer_token: str | None = None,
        max_requests: int = 1_000,
        max_bytes: int = 100 * 1024 * 1024,
    ) -> None:
        self._policy = policy
        self._resolve_host = resolve_host
        self._request_pinned = request_pinned
        self._bearer_token = bearer_token
        self._max_requests = max_requests
        self._max_bytes = max_bytes
        self.requests_used = 0
        self.bytes_used = 0

    @property
    def budget_exhausted(self) -> bool:
        return self.requests_used >= self._max_requests or self.bytes_used >= self._max_bytes

    async def fetch(self, raw_url: str, timeout_seconds: float) -> HttpResponse:
        current = _normalise_url(raw_url)
        redirects: list[dict[str, Any]] = []
        for hop_index in range(MAX_REDIRECTS + 1):
            # A new DNS resolution, policy decision and one-address connector
            # are created for every actual connection.  No pooled socket can
            # bypass the per-hop decision.
            target = await validate_and_pin(current, self._policy, self._resolve_host)
            headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
            if self._bearer_token and target.credentials_allowed:
                headers["Authorization"] = f"Bearer {self._bearer_token}"
            if self.requests_used >= self._max_requests:
                raise FetchError("Total request budget exhausted.")
            remaining_bytes = self._max_bytes - self.bytes_used
            if remaining_bytes <= 0:
                raise FetchError("Total response-byte budget exhausted.")
            self.requests_used += 1
            try:
                status, response_headers, body = await self._request_pinned(
                    target,
                    headers,
                    timeout_seconds,
                    min(MAX_RESPONSE_BYTES, remaining_bytes),
                )
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                raise FetchError("Guarded HTTP request failed.") from exc
            if len(body) > remaining_bytes:
                raise FetchError("Total response-byte budget exceeded.")
            self.bytes_used += len(body)
            location = response_headers.get("Location") or response_headers.get("location")
            if status not in REDIRECT_STATUSES or not location:
                content_type = response_headers.get("Content-Type") or response_headers.get("content-type")
                return HttpResponse(
                    requested_url=_normalise_url(raw_url),
                    final_url=target.url,
                    status=status,
                    content_type=content_type,
                    body=body,
                    redirect_chain=redirects,
                )
            redirects.append({"url": target.url, "status": status})
            if hop_index == MAX_REDIRECTS:
                raise FetchError("Redirect limit exceeded.")
            current = _normalise_url(urljoin(target.url, location))
        raise FetchError("Redirect limit exceeded.")


def _dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DispatchError(f"{label} must be an object.")
    return value


def _hex_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX_ID.fullmatch(value):
        raise DispatchError(f"{label} must be a lowercase 32-hex identifier.")
    return value


def _bounded_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DispatchError(f"{label} must be an integer.")
    if not minimum <= value <= maximum:
        raise DispatchError(f"{label} is outside the supported range.")
    return value


def _bearer_environment(command: Any) -> str | None:
    if command is None:
        raise DispatchError("command is required.")
    if not isinstance(command, list) or any(not isinstance(item, str) for item in command):
        raise DispatchError("command must be a string list.")
    for item in command:
        lowered = item.lower()
        if lowered in {
            "--auth-token",
            "--auth-password",
            "--auth-password-env",
        } or lowered.startswith(
            (
                "--auth-token=",
                "--auth-password=",
                "--auth-password-env=",
                "--auth-token-env=",
            )
        ):
            raise DispatchError("Inline or unsupported credential switches are forbidden.")
        if lowered in {"--js", "--playwright", "--embeddings", "--intent-signatures"}:
            raise DispatchError("Browser and embedding command switches are unavailable.")
        if lowered.startswith(("http://", "https://")):
            try:
                command_url = urlsplit(item)
            except ValueError as exc:
                raise DispatchError("Command contains a malformed URL.") from exc
            if command_url.username is not None or command_url.password is not None:
                raise DispatchError("Command URL credentials are forbidden.")
    # The frozen Portal producer uses crawler-cli's non-argv secret switch.
    # The adapter consumes only the environment variable name, never a value.
    indices = [index for index, item in enumerate(command) if item == "--auth-token-env"]
    if not indices:
        return None
    if len(indices) != 1 or indices[0] + 1 >= len(command):
        raise DispatchError("Bearer secret environment declaration is malformed.")
    name = command[indices[0] + 1]
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", name):
        raise DispatchError("Bearer secret environment name is invalid.")
    return name


def parse_dispatch(payload: Any) -> Dispatch:
    envelope = _dict(payload, "Dispatch")
    if envelope.get("schema_version") != DISPATCH_SCHEMA:
        raise DispatchError("Dispatch schema version is unsupported.")
    if envelope.get("crawler_version") != CRAWLER_VERSION:
        raise DispatchError("Crawler version does not match the pinned adapter.")
    if envelope.get("crawler_release") != CRAWLER_RELEASE:
        raise DispatchError("Crawler release does not match the pinned adapter.")
    if envelope.get("connection_guard_protocol") != GUARD_PROTOCOL:
        raise DispatchError("Connection guard protocol is unsupported.")
    if envelope.get("result_schema_version") != RESULT_SCHEMA:
        raise DispatchError("Result schema version is unsupported.")
    target = _dict(envelope.get("target"), "target")
    budgets = _dict(envelope.get("budgets"), "budgets")
    if budgets.get("javascript", False) is not False:
        raise DispatchError("Browser crawling is unavailable in this HTTP-only adapter.")
    if budgets.get("embeddings", False) is not False:
        raise DispatchError("Embeddings are unavailable in this reduced adapter.")
    if envelope.get("operation", "crawl_http") != "crawl_http":
        raise DispatchError("Only the crawl_http operation is available.")
    profile = target.get("deployment_profile")
    if profile not in {"saas", "appliance"}:
        raise DispatchError("Target deployment profile is unsupported.")
    allow_private = target.get("allow_private_network")
    if not isinstance(allow_private, bool):
        raise DispatchError("allow_private_network must be boolean.")
    if profile == "saas" and allow_private:
        raise DispatchError("Private-network crawling is unavailable in SaaS.")
    credentials_origin_only = target.get("credentials_origin_only")
    if credentials_origin_only is not True:
        raise DispatchError("credentials_origin_only must be true.")
    target_url = _normalise_url(target.get("url"))
    actual_origin = _origin(urlsplit(target_url))
    configured_origin = target.get("origin")
    if not isinstance(configured_origin, str) or configured_origin != actual_origin:
        raise DispatchError("Target origin does not match target URL.")
    target_policy = TargetPolicy(
        deployment_profile=profile,
        allow_private_network=allow_private,
        configured_origin=configured_origin,
    )
    initial_pinned_ip = target.get("initial_pinned_ip")
    if not isinstance(initial_pinned_ip, str) or not _ip_allowed(initial_pinned_ip, target_policy):
        raise DispatchError("Initial pinned IP is malformed or denied.")
    lease_fence = envelope.get("lease_fence")
    _bounded_int(lease_fence, "lease_fence", 1, 9_223_372_036_854_775_807)
    max_pages = budgets.get("max_pages", 100)
    max_requests = budgets.get("max_requests", 1_000)
    max_bytes = budgets.get("max_bytes", 100 * 1024 * 1024)
    timeout = envelope.get("wall_clock_timeout_seconds", 600)
    discover_sitemaps = budgets.get("discover_sitemaps", True)
    if not isinstance(discover_sitemaps, bool):
        raise DispatchError("discover_sitemaps must be boolean.")
    return Dispatch(
        job_id=_hex_id(envelope.get("job_id"), "job_id"),
        attempt_id=_hex_id(envelope.get("attempt_id"), "attempt_id"),
        run_id=_hex_id(envelope.get("run_id"), "run_id"),
        target_url=target_url,
        target_policy=target_policy,
        max_pages=_bounded_int(max_pages, "max_pages", 1, 100_000),
        max_requests=_bounded_int(max_requests, "max_requests", 1, 1_000_000),
        max_bytes=_bounded_int(max_bytes, "max_bytes", 1_024, 10_737_418_240),
        timeout_seconds=_bounded_int(timeout, "wall_clock_timeout_seconds", 30, 86_400),
        discover_sitemaps=discover_sitemaps,
        bearer_env=_bearer_environment(envelope.get("command")),
    )


def _observation_key(index: int, requested_url: str) -> str:
    return hashlib.sha256(f"{index}\0{requested_url}".encode()).hexdigest()


def _html_fields_and_links(body: bytes, base_url: str) -> tuple[dict[str, Any], list[str]]:
    soup = BeautifulSoup(body, "html.parser")
    fields: dict[str, Any] = {}
    if soup.title and soup.title.string:
        fields["title"] = soup.title.string.strip()[:1000]
    description = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if description and description.get("content"):
        fields["meta_description"] = str(description["content"]).strip()[:4000]
    canonical = soup.find(
        "link",
        attrs={"rel": lambda value: bool(value and "canonical" in value)},
    )
    if canonical and canonical.get("href"):
        fields["canonical"] = _normalise_url(urljoin(base_url, str(canonical["href"])))
    links: list[str] = []
    for tag in soup.find_all("a", href=True):
        try:
            links.append(_normalise_url(urljoin(base_url, str(tag["href"]))))
        except UrlPolicyError:
            continue
    return fields, links


def _sitemap_urls(body: bytes, base_url: str) -> tuple[list[str], bool]:
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, ValueError):
        return [], False
    local_name = root.tag.rsplit("}", 1)[-1].lower()
    if local_name not in {"urlset", "sitemapindex"}:
        return [], False
    urls: list[str] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() != "loc" or not node.text:
            continue
        try:
            urls.append(_normalise_url(urljoin(base_url, node.text.strip())))
        except UrlPolicyError:
            continue
    return urls, local_name == "sitemapindex"


class PortalCrawler:
    def __init__(self, dispatch: Dispatch, client: SafeHttpClient) -> None:
        self.dispatch = dispatch
        self.client = client
        self._robots: dict[str, RobotFileParser] = {}
        self._sitemap_candidates: deque[tuple[str, int]] = deque()
        self.incomplete_due_to_transport_budget = False

    async def _robots_for(self, url: str) -> RobotFileParser:
        origin = _origin(urlsplit(url))
        cached = self._robots.get(origin)
        if cached is not None:
            return cached
        parser = RobotFileParser()
        # Rebuild correctly for IPv6 and explicit ports.
        parts = urlsplit(url)
        default_port = 443 if parts.scheme == "https" else 80
        authority = f"[{parts.hostname}]" if ":" in (parts.hostname or "") else parts.hostname
        if parts.port and parts.port != default_port:
            authority = f"{authority}:{parts.port}"
        robots_url = f"{parts.scheme}://{authority}/robots.txt"
        parser.set_url(robots_url)
        if not self.client.budget_exhausted:
            try:
                response = await self.client.fetch(robots_url, self.dispatch.timeout_seconds)
                if response.status == 200:
                    text = response.body.decode("utf-8", "replace")
                    parser.parse(text.splitlines())
                    for line in text.splitlines():
                        if line.lower().startswith("sitemap:"):
                            candidate = line.split(":", 1)[1].strip()
                            try:
                                self._sitemap_candidates.append((_normalise_url(candidate), 0))
                            except UrlPolicyError:
                                pass
                else:
                    parser.parse([])
            except AdapterError:
                parser.parse([])
        else:
            parser.parse([])
        self._robots[origin] = parser
        return parser

    async def crawl(self) -> list[dict[str, Any]]:
        queue: deque[str] = deque([self.dispatch.target_url])
        queued = {self.dispatch.target_url}
        observations: list[dict[str, Any]] = []
        seed_origin = self.dispatch.target_policy.configured_origin

        parts = urlsplit(self.dispatch.target_url)
        authority = f"[{parts.hostname}]" if ":" in (parts.hostname or "") else parts.hostname
        if parts.port:
            authority = f"{authority}:{parts.port}"
        if self.dispatch.discover_sitemaps:
            self._sitemap_candidates.append((f"{parts.scheme}://{authority}/sitemap.xml", 0))

        while queue and len(observations) < self.dispatch.max_pages:
            requested_url = queue.popleft()
            parser = await self._robots_for(requested_url)
            if not parser.can_fetch(USER_AGENT, requested_url):
                observations.append(
                    {
                        "observation_key": _observation_key(len(observations), requested_url),
                        "outcome_state": "skipped",
                        "requested_url": requested_url,
                        "final_url": None,
                        "http_status": None,
                        "content_type": None,
                        "fetch_backend": "portal-aiohttp-pinned",
                        "allowed_by_robots": False,
                        "skip_reason": "robots_txt_disallow",
                        "redirect_chain": [],
                        "extracted_fields": {},
                        "artifacts": [],
                    }
                )
                continue
            try:
                response = await self.client.fetch(requested_url, self.dispatch.timeout_seconds)
                fields: dict[str, Any] = {}
                links: Iterable[str] = []
                if response.content_type and "html" in response.content_type.lower():
                    fields, links = _html_fields_and_links(response.body, response.final_url)
                observation = {
                    "observation_key": _observation_key(len(observations), requested_url),
                    "outcome_state": "observed",
                    "requested_url": requested_url,
                    "final_url": response.final_url,
                    "http_status": response.status,
                    "content_type": response.content_type,
                    "fetch_backend": "portal-aiohttp-pinned",
                    "allowed_by_robots": True,
                    "skip_reason": None,
                    "content_sha256": hashlib.sha256(response.body).hexdigest(),
                    "content_hash_version": "raw-bytes/1",
                    "semantic_hash": None,
                    "semantic_hash_version": None,
                    "preprocessing_version": None,
                    "redirect_chain": response.redirect_chain,
                    "extracted_fields": fields,
                    "artifacts": [],
                }
                observations.append(observation)
                for link in links:
                    if _origin(urlsplit(link)) == seed_origin and link not in queued:
                        queued.add(link)
                        queue.append(link)
            except AdapterError:
                observations.append(
                    {
                        "observation_key": _observation_key(len(observations), requested_url),
                        "outcome_state": "error",
                        "requested_url": requested_url,
                        "final_url": None,
                        "http_status": None,
                        "content_type": None,
                        "fetch_backend": "portal-aiohttp-pinned",
                        "allowed_by_robots": True,
                        "skip_reason": "guarded_fetch_failed",
                        "redirect_chain": [],
                        "extracted_fields": {},
                        "artifacts": [],
                    }
                )

            while self.dispatch.discover_sitemaps and self._sitemap_candidates and not self.client.budget_exhausted:
                sitemap_url, depth = self._sitemap_candidates.popleft()
                if depth > 3:
                    continue
                try:
                    sitemap_response = await self.client.fetch(sitemap_url, self.dispatch.timeout_seconds)
                    if sitemap_response.status != 200:
                        continue
                    sitemap_links, is_index = _sitemap_urls(sitemap_response.body, sitemap_response.final_url)
                    for sitemap_link in sitemap_links[:100_000]:
                        if _origin(urlsplit(sitemap_link)) != seed_origin:
                            continue
                        if is_index:
                            self._sitemap_candidates.append((sitemap_link, depth + 1))
                        elif sitemap_link not in queued:
                            queued.add(sitemap_link)
                            queue.append(sitemap_link)
                except AdapterError:
                    continue
            if self.client.budget_exhausted:
                self.incomplete_due_to_transport_budget = bool(queue or self._sitemap_candidates)
                break
        return observations


def build_result(
    dispatch: Dispatch,
    observations: list[dict[str, Any]],
    started_at: str,
    completed_at: str,
    *,
    forced_partial: bool = False,
) -> dict[str, Any]:
    error_count = sum(item["outcome_state"] == "error" for item in observations)
    incomplete_count = sum(item["outcome_state"] != "observed" for item in observations)
    status = "complete" if incomplete_count == 0 and not forced_partial else "partial"
    return {
        "schema_version": RESULT_SCHEMA,
        "run_id": dispatch.run_id,
        "producer": {
            "kind": "migration_manager_crawl",
            "job_id": dispatch.job_id,
            "attempt_id": dispatch.attempt_id,
        },
        "crawler_release": CRAWLER_RELEASE,
        "crawler_schema_version": CRAWLER_ARTIFACT_SCHEMA,
        "terminal": {
            "status": status,
            "artifact_availability": "none",
            "observation_count": len(observations),
            "error_count": error_count,
            "incomplete_count": incomplete_count,
            "started_at": started_at,
            "completed_at": completed_at,
        },
        "observations": observations,
    }


def _read_dispatch_fd(fd: int) -> Any:
    if fd < 3:
        raise DispatchError("Configuration FD must be a dedicated descriptor (3 or greater).")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, min(65_536, MAX_DISPATCH_BYTES + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_DISPATCH_BYTES:
            raise DispatchError("Dispatch exceeds the maximum envelope size.")
    if total == 0:
        raise DispatchError("Dispatch envelope is empty.")
    try:
        return json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DispatchError("Dispatch is not valid UTF-8 JSON.") from exc


async def run_dispatch(dispatch: Dispatch) -> dict[str, Any]:
    started_at = _utc_now()
    bearer_token = os.environ.get(dispatch.bearer_env) if dispatch.bearer_env else None
    if dispatch.bearer_env and not bearer_token:
        observations = [
            {
                "observation_key": _observation_key(0, dispatch.target_url),
                "outcome_state": "error",
                "requested_url": dispatch.target_url,
                "final_url": None,
                "http_status": None,
                "content_type": None,
                "fetch_backend": "portal-aiohttp-pinned",
                "allowed_by_robots": None,
                "skip_reason": "credential_unavailable",
                "redirect_chain": [],
                "extracted_fields": {},
                "artifacts": [],
            }
        ]
        return build_result(dispatch, observations, started_at, _utc_now())
    client = SafeHttpClient(
        dispatch.target_policy,
        bearer_token=bearer_token,
        max_requests=dispatch.max_requests,
        max_bytes=dispatch.max_bytes,
    )
    crawler = PortalCrawler(dispatch, client)
    try:
        observations = await asyncio.wait_for(
            crawler.crawl(),
            timeout=dispatch.timeout_seconds,
        )
    except asyncio.TimeoutError:
        observations = [
            {
                "observation_key": _observation_key(0, dispatch.target_url),
                "outcome_state": "error",
                "requested_url": dispatch.target_url,
                "final_url": None,
                "http_status": None,
                "content_type": None,
                "fetch_backend": "portal-aiohttp-pinned",
                "allowed_by_robots": None,
                "skip_reason": "wall_clock_timeout",
                "redirect_chain": [],
                "extracted_fields": {},
                "artifacts": [],
            }
        ]
    return build_result(
        dispatch,
        observations,
        started_at,
        _utc_now(),
        forced_partial=crawler.incomplete_due_to_transport_budget,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="migration-manager-crawler")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--capabilities", action="store_true")
    mode.add_argument("--config-fd", type=int, metavar="N")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.capabilities:
        capabilities = {**CAPABILITIES, "generated_at": _utc_now()}
        print(json.dumps(capabilities, sort_keys=True, separators=(",", ":")))
        return 0
    try:
        dispatch = parse_dispatch(_read_dispatch_fd(args.config_fd))
        result = asyncio.run(run_dispatch(dispatch))
    except AdapterError as exc:
        print(f"migration-manager-crawler: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    terminal = result["terminal"]
    return 0 if terminal["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
