from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import ssl
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from curl_cffi.requests import AsyncSession

from .config import CrawlConfig
from .cookies import build_cookie_header, build_scoped_cookie_header
from .models import FetchResponse
from .proxy_pool import ProxyPool

# Content-type prefixes that are never HTML/XML and should not be fully
# downloaded. The list is intentionally conservative: only clearly binary
# or non-parseable types. Sitemaps and feeds (text/xml, application/xml,
# application/rss+xml, application/atom+xml) are NOT excluded here because
# the engine parses them. application/xhtml+xml is HTML so also kept.
_SKIP_CONTENT_TYPES = frozenset(
    [
        "image/",
        "audio/",
        "video/",
        "font/",
        "application/pdf",
        "application/zip",
        "application/x-zip",
        "application/octet-stream",
        "application/x-tar",
        "application/x-gzip",
        "application/gzip",
        "application/vnd.ms-",
        "application/vnd.openxmlformats",
    ]
)
# Sniff buffer: read only this many bytes for non-parseable types.
_SNIFF_BYTES = 256

# PerformanceObserver shim injected before page scripts run (ticket 046). It
# accumulates the latest LCP, summed CLS, and worst INP into window.__cwv so
# the backend can read lab Core Web Vitals after the page settles. LCP/CLS use
# buffered entries; INP is approximated from event-timing durations (real INP
# needs interaction — these are lab values, documented as such).
_WEB_VITALS_SHIM = """
(() => {
  if (window.__cwv) return;
  window.__cwv = { lcp: null, cls: 0, inp: null };
  try {
    new PerformanceObserver((list) => {
      const entries = list.getEntries();
      const last = entries[entries.length - 1];
      if (last) window.__cwv.lcp = last.renderTime || last.loadTime || last.startTime;
    }).observe({ type: 'largest-contentful-paint', buffered: true });
  } catch (e) {}
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) window.__cwv.cls += entry.value;
      }
    }).observe({ type: 'layout-shift', buffered: true });
  } catch (e) {}
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const d = entry.duration;
        if (window.__cwv.inp === null || d > window.__cwv.inp) window.__cwv.inp = d;
      }
    }).observe({ type: 'event', buffered: true, durationThreshold: 16 });
  } catch (e) {}
})();
"""


def _is_skippable_content_type(content_type: str | None) -> bool:
    """Return True if the content-type is clearly non-HTML/XML and need not be fully read."""
    if not content_type:
        return False
    ct_lower = content_type.lower().split(";", 1)[0].strip()
    return any(ct_lower.startswith(skip) for skip in _SKIP_CONTENT_TYPES)


def _request_headers(config: CrawlConfig, url: str) -> dict[str, str]:
    # Per-domain User-Agent override (ticket 080); falls back to config.user_agent.
    headers = {"User-Agent": config.user_agent_for(url), **config.request_headers}
    # Scoped cookies (ticket 048) take precedence and are filtered to the
    # target URL's domain/path; otherwise fall back to the flat all-hosts map
    # (ticket 028).
    cookie_value = ""
    if config.scoped_cookies:
        cookie_value = build_scoped_cookie_header(config.scoped_cookies, url)
    elif config.cookies:
        cookie_value = build_cookie_header(config.cookies)
    if cookie_value:
        existing = headers.get("Cookie")
        headers["Cookie"] = f"{existing}; {cookie_value}" if existing else cookie_value
    if config.auth and config.auth.applies_to(url):
        headers.update(config.auth.auth_headers())
    return headers


def _proxy_url(config: CrawlConfig) -> str | None:
    """Build the effective proxy URL, folding in ``proxy_auth`` if given.

    Returns None when no proxy is configured. When ``proxy_auth`` is set and the
    proxy URL has no embedded credentials, ``user:pass@`` is injected after the
    scheme.
    """
    if not config.proxy:
        return None
    proxy = config.proxy
    if config.proxy_auth and "@" not in proxy.split("://", 1)[-1]:
        scheme, _, rest = proxy.partition("://")
        if rest:
            return f"{scheme}://{config.proxy_auth}@{rest}"
        return f"{config.proxy_auth}@{proxy}"
    return proxy


def _playwright_proxy(config: CrawlConfig) -> dict[str, str] | None:
    """Playwright wants the proxy split into server + optional username/password."""
    if not config.proxy:
        return None
    proxy_setting: dict[str, str] = {"server": config.proxy}
    if config.proxy_auth and ":" in config.proxy_auth:
        user, password = config.proxy_auth.split(":", 1)
        proxy_setting["username"] = user
        proxy_setting["password"] = password
    return proxy_setting


def _basic_auth(config: CrawlConfig, url: str):
    if config.auth and config.auth.applies_to(url):
        creds = config.auth.basic_credentials()
        if creds:
            import aiohttp

            return aiohttp.BasicAuth(creds[0], creds[1])
    return None


def _decode_body(body: bytes, content_type: str | None) -> str:
    charset = "utf-8"
    if content_type and "charset=" in content_type.lower():
        charset = content_type.split("charset=", 1)[1].split(";", 1)[0].strip()
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


async def _playwright_redirect_chain(response: object) -> list[dict[str, object]]:
    """Reconstruct the redirect chain for a Playwright navigation (ticket 122).

    Playwright has no ``history`` list; it links each request to the one it was
    ``redirected_from``. Walk that backwards, reading each hop's response status
    where available, and return the hops in request order. Best-effort — a hop
    whose response isn't retrievable is recorded with ``status=None``."""
    if response is None:
        return []
    chain: list[dict[str, object]] = []
    request = getattr(response, "request", None)
    request = getattr(request, "redirected_from", None) if request is not None else None
    while request is not None:
        status: int | None = None
        try:
            hop_response = await request.response()
            if hop_response is not None:
                status = hop_response.status
        except Exception:
            status = None
        chain.append({"url": request.url, "status": status})
        request = getattr(request, "redirected_from", None)
    chain.reverse()
    return chain


def build_proxy_pool(config: CrawlConfig) -> "ProxyPool | None":
    """Build a ProxyPool from config, honouring gateway vs list mode.

    Gateway mode (ticket 072): the single ``proxy`` endpoint (with ``proxy_auth``
    folded in) is the one rotating-gateway URL. List mode (ticket 045): the
    ``proxies`` list. Returns None when no proxy is configured.
    """
    if config.proxy_mode == "gateway":
        endpoint = _proxy_url(config)
        if not endpoint:
            return None
        return ProxyPool(proxies=[endpoint], mode="gateway")
    if config.proxies:
        return ProxyPool(
            proxies=list(config.proxies),
            mode="list",
            rotation=config.proxy_rotation,
            max_failures=config.proxy_max_failures,
            cooldown_seconds=config.proxy_cooldown_seconds,
        )
    return None


class FetchBackend(ABC):
    def __init__(self, config: CrawlConfig) -> None:
        self.config = config
        self._proxy_pool: ProxyPool | None = build_proxy_pool(config)

    def _select_proxy(self, url: str) -> str | None:
        """Pick a proxy for *url*: from the pool if configured, else the single
        ``proxy`` (ticket 027/045)."""
        if self._proxy_pool is not None:
            return self._proxy_pool.select(url)
        return _proxy_url(self.config)

    def _report_proxy(self, proxy: str | None, *, ok: bool) -> None:
        if self._proxy_pool is None or proxy is None:
            return
        if ok:
            self._proxy_pool.report_success(proxy)
        else:
            self._proxy_pool.report_failure(proxy)

    @abstractmethod
    async def fetch(self, url: str) -> FetchResponse:
        raise NotImplementedError

    async def fetch_resilient(self, url: str) -> FetchResponse:
        """fetch() with gateway retry-on-failure (ticket 072).

        In gateway mode a failed fetch (status 0, i.e. connection/proxy error)
        is retried through the same endpoint up to ``proxy_gateway_max_retries``
        times — each retry gets a fresh server-side exit IP. In list mode (or no
        proxy) this is a plain single fetch; the list pool's own eviction handles
        bad proxies. Non-zero HTTP statuses (incl. 403/blocks) are returned as-is
        for the engine's challenge handling (ticket 074), not retried here.
        """
        if self._proxy_pool is None or not self._proxy_pool.is_gateway:
            return await self.fetch(url)
        attempts = max(1, self.config.proxy_gateway_max_retries + 1)
        result = await self.fetch(url)
        for _ in range(attempts - 1):
            if result.status != 0:
                return result
            result = await self.fetch(url)
        return result

    async def close(self) -> None:
        return None


class AiohttpBackend(FetchBackend):
    def __init__(self, config: CrawlConfig) -> None:
        super().__init__(config)
        self._session: aiohttp.ClientSession | None = None
        self._ssl_context: ssl.SSLContext | None = None

    def _get_ssl_context(self) -> ssl.SSLContext | None:
        if not self.config.verify_ssl:
            if self._ssl_context is None:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                self._ssl_context = ctx
            return self._ssl_context
        return None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
            connector = aiohttp.TCPConnector(
                limit=max(self.config.max_concurrency, 10),
                ssl=self._get_ssl_context(),
            )
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
            )
        return self._session

    async def fetch(self, url: str) -> FetchResponse:
        session = await self._get_session()
        headers = _request_headers(self.config, url)
        auth = _basic_auth(self.config, url)
        proxy = self._select_proxy(url)
        started = time.monotonic()
        try:
            response_cm = session.get(
                url,
                headers=headers,
                allow_redirects=self.config.follow_redirects,
                ssl=self._get_ssl_context(),
                auth=auth,
                proxy=proxy,
            )
            response = await response_cm.__aenter__()
        except Exception:
            self._report_proxy(proxy, ok=False)
            raise
        try:
            # Response headers are available here, before the body is read,
            # so this is a good proxy for time-to-first-byte.
            ttfb = time.monotonic() - started
            header_map = dict(response.headers)
            ct = header_map.get("Content-Type")
            cap = self.config.max_response_bytes
            truncated = False

            if _is_skippable_content_type(ct):
                # Non-parseable type: read only a small sniff buffer.
                body = await response.content.read(_SNIFF_BYTES)
            else:
                # Stream in chunks, stopping as soon as we hit the cap.
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.content.iter_chunked(65536):
                    remaining = cap - total
                    if len(chunk) >= remaining:
                        chunks.append(chunk[:remaining])
                        total += remaining
                        truncated = True
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                body = b"".join(chunks)

            elapsed = time.monotonic() - started
            # aiohttp keeps each redirect response in ``history`` (ticket 122).
            redirect_chain = [{"url": str(hop.url), "status": hop.status} for hop in response.history]
            result = FetchResponse(
                url=str(response.url),
                requested_url=url,
                status=response.status,
                headers=header_map,
                body=body,
                text=_decode_body(body, ct),
                ttfb_seconds=ttfb,
                elapsed_seconds=elapsed,
                body_truncated=truncated,
                redirect_chain=redirect_chain,
            )
        except Exception:
            await response_cm.__aexit__(*sys.exc_info())
            self._report_proxy(proxy, ok=False)
            raise
        else:
            await response_cm.__aexit__(None, None, None)
            self._report_proxy(proxy, ok=True)
            return result

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None


class CurlCffiBackend(FetchBackend):
    def __init__(self, config: CrawlConfig) -> None:
        super().__init__(config)
        self._session: AsyncSession | None = None

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            session_kwargs: dict[str, object] = {
                "verify": self.config.verify_ssl,
            }
            # When a proxy pool is active the proxy is chosen per request, so
            # don't bind a session-level proxy (ticket 045).
            if self.config.proxy and self._proxy_pool is None:
                session_kwargs["proxy"] = self.config.proxy
                if self.config.proxy_auth:
                    session_kwargs["proxy_auth"] = tuple(self.config.proxy_auth.split(":", 1))
            if self.config.curl_impersonate and self.config.curl_impersonate != "none":
                session_kwargs["impersonate"] = self.config.curl_impersonate
            self._session = AsyncSession(**session_kwargs)
        return self._session

    async def fetch(self, url: str) -> FetchResponse:
        session = await self._get_session()
        headers = _request_headers(self.config, url)
        auth = None
        if self.config.auth and self.config.auth.applies_to(url):
            auth = self.config.auth.basic_credentials()
        cap = self.config.max_response_bytes
        # Per-request proxy only when a pool is active; otherwise the session's
        # single proxy is already bound in _get_session.
        request_proxy = self._proxy_pool.select(url) if self._proxy_pool is not None else None
        get_kwargs: dict[str, object] = {}
        if request_proxy is not None:
            get_kwargs["proxy"] = request_proxy
        started = time.monotonic()
        # Stream the response so we can record time-to-first-byte (the moment
        # the first body chunk arrives) without relying on curl's
        # STARTTRANSFER_TIME handle lookup, which is version-fragile on the
        # pooled AsyncSession handle (ticket 047). This also lets us honour the
        # byte cap and content-type gate the same way the aiohttp backend does.
        try:
            response = await session.get(
                url,
                headers=headers,
                auth=auth,
                timeout=self.config.timeout_seconds,
                allow_redirects=self.config.follow_redirects,
                stream=True,
                **get_kwargs,
            )
        except Exception:
            self._report_proxy(request_proxy, ok=False)
            raise
        try:
            header_map = dict(response.headers)
            ct = header_map.get("Content-Type")
            ttfb: float | None = None
            truncated = False
            chunks: list[bytes] = []
            total = 0
            skippable = _is_skippable_content_type(ct)
            async for chunk in response.aiter_content():
                if ttfb is None:
                    ttfb = time.monotonic() - started
                if not chunk:
                    continue
                if skippable:
                    # Non-parseable type: keep only a small sniff buffer, then
                    # stop pulling the rest of the payload.
                    chunks.append(chunk[:_SNIFF_BYTES])
                    truncated = total + len(chunk) > _SNIFF_BYTES
                    break
                remaining = cap - total
                if len(chunk) >= remaining:
                    chunks.append(chunk[:remaining])
                    total += remaining
                    truncated = True
                    break
                chunks.append(chunk)
                total += len(chunk)
            body = b"".join(chunks)
        except Exception:
            self._report_proxy(request_proxy, ok=False)
            raise
        finally:
            with contextlib.suppress(Exception):
                await response.aclose()
        self._report_proxy(request_proxy, ok=True)
        elapsed = time.monotonic() - started
        # curl_cffi exposes prior redirect responses via ``history`` (ticket 122).
        redirect_chain = [
            {"url": str(hop.url), "status": hop.status_code} for hop in getattr(response, "history", []) or []
        ]
        return FetchResponse(
            url=str(response.url),
            requested_url=url,
            status=response.status_code,
            headers=header_map,
            body=body,
            text=_decode_body(body, ct),
            ttfb_seconds=ttfb,
            elapsed_seconds=elapsed,
            body_truncated=truncated,
            redirect_chain=redirect_chain,
        )

    async def close(self) -> None:
        if self._session is not None:
            with contextlib.suppress(Exception):
                await self._session.close()
            self._session = None


def _linux_descendant_pids(root_pid: int) -> set[int]:
    children_path = Path(f"/proc/{root_pid}/task/{root_pid}/children")
    if not children_path.exists():
        return set()

    descendants: set[int] = set()
    stack = [root_pid]
    while stack:
        pid = stack.pop()
        path = Path(f"/proc/{pid}/task/{pid}/children")
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        for part in raw.split():
            if not part.isdigit():
                continue
            child_pid = int(part)
            if child_pid in descendants:
                continue
            descendants.add(child_pid)
            stack.append(child_pid)
    return descendants


def _browser_like_descendants(root_pid: int) -> set[int]:
    matches: set[int] = set()
    for pid in _linux_descendant_pids(root_pid):
        try:
            cmdline = (
                Path(f"/proc/{pid}/cmdline")
                .read_bytes()
                .replace(b"\x00", b" ")
                .decode(
                    "utf-8",
                    errors="ignore",
                )
            )
        except OSError:
            continue
        lowered = cmdline.lower()
        if any(token in lowered for token in ("chromium", "chrome", "playwright")):
            matches.add(pid)
    return matches


class PlaywrightBackend(FetchBackend):
    """Playwright backend with bounded context reuse and explicit shutdown."""

    def __init__(self, config: CrawlConfig) -> None:
        super().__init__(config)
        self._playwright = None
        self._browser = None
        self._context = None
        self._persistent_context = False
        # True when we connected to an external CDP browser (Obscura or an
        # explicit CDP endpoint) rather than launching Chromium ourselves. CDP
        # servers like Obscura expose a single default BrowserContext and do not
        # fully back additional contexts created via new_context(), so we must
        # reuse contexts()[0] and never close it (see Obscura's Use-with-
        # Playwright guide). _owns_context tracks whether we may close it.
        self._cdp_connected = False
        self._owns_context = True
        self._lock = asyncio.Lock()
        self._context_request_count = 0
        self._context_recycle_requested = False
        self._active_pages = 0
        self._baseline_browser_pids: set[int] = set()
        self._tracked_browser_pids: set[int] = set()
        self._managed_obscura_proc: asyncio.subprocess.Process | None = None
        self._obscura_stderr: list[str] = []

    @staticmethod
    def _timeout_ms(seconds: float) -> int:
        return max(1, int(seconds * 1000))

    def _playwright_proxy_setting(self) -> dict[str, str] | None:
        """Build Playwright's proxy dict (server + optional user/pass) from the
        pool (gateway or list) or the single configured proxy (ticket 073).

        Playwright wants credentials split out, so embedded ``user:pass@`` in a
        pooled URL is parsed into username/password.
        """
        if self._proxy_pool is not None:
            selected = self._proxy_pool.select("")
            if not selected:
                return None
            parsed = urlparse(selected)
            setting: dict[str, str] = {
                "server": f"{parsed.scheme}://{parsed.hostname}" + (f":{parsed.port}" if parsed.port else "")
            }
            if parsed.username:
                setting["username"] = parsed.username
            if parsed.password:
                setting["password"] = parsed.password
            return setting
        return _playwright_proxy(self.config)

    def _uses_persistent_profile(self) -> bool:
        return bool(self.config.playwright_user_data_dir)

    def _persistent_context_launch_kwargs(self) -> dict[str, object]:
        launch_kwargs = self._context_kwargs()
        launch_kwargs["headless"] = self.config.playwright_headless
        if self.config.playwright_browser_channel:
            launch_kwargs["channel"] = self.config.playwright_browser_channel
        if self.config.playwright_executable_path:
            launch_kwargs["executable_path"] = self.config.playwright_executable_path
        if self.config.playwright_profile_directory:
            launch_kwargs["args"] = [f"--profile-directory={self.config.playwright_profile_directory}"]
        return launch_kwargs

    def _context_kwargs(self) -> dict[str, object]:
        extra_headers: dict[str, str] = dict(self.config.request_headers)
        # Scoped cookies (ticket 048) are added to the browser's cookie jar via
        # context.add_cookies (see _create_context_locked) so Chromium enforces
        # domain/path matching itself. Only the legacy flat map is injected as a
        # blanket Cookie header here (ticket 028).
        if not self.config.scoped_cookies and self.config.cookies:
            existing = extra_headers.get("Cookie")
            cookie_value = build_cookie_header(self.config.cookies)
            extra_headers["Cookie"] = f"{existing}; {cookie_value}" if existing else cookie_value
        context_kwargs: dict[str, object] = {
            "user_agent": self.config.user_agent,
            "ignore_https_errors": not self.config.verify_ssl,
            "extra_http_headers": extra_headers,
        }
        # Obscura handles its own proxy via the obscura binary's --proxy flag;
        # only apply the generic proxy to plain Playwright contexts (ticket 027).
        if not self.config.obscura_enabled:
            # Proxy is a per-context setting in Playwright. In GATEWAY mode this
            # is fine — the single endpoint goes on the context and the gateway
            # rotates the exit IP server-side per request, so a reused context
            # still gets rotating IPs (ticket 073). In LIST mode rotation is at
            # context granularity (one proxy per context, re-picked on recycle).
            proxy_setting = self._playwright_proxy_setting()
            if proxy_setting is not None:
                context_kwargs["proxy"] = proxy_setting
        # Auth is applied per-page in fetch() via page.route so it can be safely
        # origin-scoped (ticket 129).
        return context_kwargs

    def _playwright_cookie_payload(self) -> list[dict[str, object]]:
        """Convert scoped Cookie objects to Playwright add_cookies entries.

        Playwright requires either a ``url`` or an explicit ``domain``+``path``.
        Cookies without a domain (the ``--cookie name=value`` form) are skipped
        here because Chromium cannot scope them; those callers should use the
        flat-map header path instead.
        """
        payload: list[dict[str, object]] = []
        for cookie in self.config.scoped_cookies:
            if not cookie.domain:
                continue
            payload.append(
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path or "/",
                    "secure": cookie.secure,
                    "httpOnly": cookie.httponly,
                }
            )
        return payload

    async def _initialize_context_locked(self) -> None:
        assert self._context is not None
        self._context_request_count = 0
        self._context_recycle_requested = False
        cookie_payload = self._playwright_cookie_payload()
        if cookie_payload:
            with contextlib.suppress(Exception):
                await self._context.add_cookies(cookie_payload)
        if self.config.collect_web_vitals:
            # Inject before any page script so the observers capture from load
            # (ticket 046). Suppressed: a CDP browser may reject init scripts.
            with contextlib.suppress(Exception):
                await self._context.add_init_script(_WEB_VITALS_SHIM)

    async def _create_context_locked(self) -> None:
        assert self._browser is not None
        if self._cdp_connected:
            # Reuse the CDP server's default context rather than allocating a new
            # one. Obscura's docs prescribe `browser.contexts()[0] || newContext()`;
            # calling new_context() against Obscura yields a context whose pages
            # never navigate, which surfaces as "0 crawled" / connect wedges.
            existing = self._browser.contexts
            if existing:
                self._context = existing[0]
                self._owns_context = False
            else:
                self._context = await self._browser.new_context(**self._context_kwargs())
                self._owns_context = True
        else:
            self._context = await self._browser.new_context(**self._context_kwargs())
            self._owns_context = True
        await self._initialize_context_locked()

    async def _read_web_vitals(self, page) -> tuple[float | None, float | None, float | None]:
        """Read accumulated lab CWV from the injected shim (ticket 046)."""
        try:
            data = await page.evaluate("() => window.__cwv || null")
        except Exception:
            return None, None, None
        if not isinstance(data, dict):
            return None, None, None
        lcp = data.get("lcp")
        cls = data.get("cls")
        inp = data.get("inp")
        return (
            float(lcp) if isinstance(lcp, (int, float)) else None,
            float(cls) if isinstance(cls, (int, float)) else None,
            float(inp) if isinstance(inp, (int, float)) else None,
        )

    async def _recycle_context_locked(self) -> None:
        if self._persistent_context:
            self._context_request_count = 0
            self._context_recycle_requested = False
            return
        old_context = self._context
        owned = self._owns_context
        self._context = None
        self._context_request_count = 0
        self._context_recycle_requested = False
        # Never close a context we borrowed from a CDP server (Obscura's single
        # default context) — closing it would tear down the only context the
        # server has. Only close contexts we created ourselves.
        if old_context is not None and owned:
            with contextlib.suppress(Exception):
                await old_context.close()
        if self._browser is not None:
            await self._create_context_locked()

    def _obscura_cdp_endpoint(self) -> str:
        return f"http://{self.config.obscura_host}:{self.config.obscura_port}"

    async def _start_managed_obscura(self) -> None:
        """Spawn obscura serve and wait for CDP readiness."""
        assert self._playwright is not None
        argv = [
            self.config.obscura_binary,
            "serve",
            "--port",
            str(self.config.obscura_port),
            "--workers",
            str(self.config.obscura_workers),
        ]
        # Prefer the explicit obscura_proxy; otherwise fall back to the general
        # proxy pool/gateway so `--proxy <gateway>` works with --obscura too
        # (ticket 073). Gateway rotates the IP server-side per request.
        obscura_proxy = self.config.obscura_proxy
        if not obscura_proxy and self._proxy_pool is not None:
            obscura_proxy = self._proxy_pool.select("") or ""
        if obscura_proxy:
            argv.extend(["--proxy", obscura_proxy])
        effective_stealth = self.config.obscura_stealth
        if effective_stealth is None and not self.config.analytics_detection:
            effective_stealth = True
        if effective_stealth:
            argv.append("--stealth")

        self._managed_obscura_proc = await asyncio.create_subprocess_exec(
            *argv,
            stderr=asyncio.subprocess.PIPE,
        )

        deadline = asyncio.get_running_loop().time() + 10.0
        last_err = ""
        while asyncio.get_running_loop().time() < deadline:
            try:
                browser = await self._playwright.chromium.connect_over_cdp(self._obscura_cdp_endpoint())
                await browser.close()
                return
            except Exception as exc:
                last_err = str(exc)
                # Collect any stderr for diagnostics
                if self._managed_obscura_proc.stderr is not None and self._managed_obscura_proc.returncode is None:
                    with contextlib.suppress(Exception):
                        data = await asyncio.wait_for(self._managed_obscura_proc.stderr.read(4096), timeout=0.2)
                        if data:
                            self._obscura_stderr.append(data.decode("utf-8", errors="replace"))
                await asyncio.sleep(0.3)

        # Startup failed — terminate subprocess and raise
        await self._terminate_managed_obscura()
        stderr_snippet = "".join(self._obscura_stderr)[-800:]
        raise RuntimeError(
            f"Managed Obscura failed to start within 10s: {' '.join(argv)}\n"
            f"Last error: {last_err}\n"
            f"Stderr snippet: {stderr_snippet or '(none captured)'}"
        )

    async def _terminate_managed_obscura(self) -> None:
        proc = self._managed_obscura_proc
        if proc is None:
            return
        if proc.returncode is not None:
            self._managed_obscura_proc = None
            return
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            with contextlib.suppress(Exception):
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
        except Exception:
            pass
        finally:
            self._managed_obscura_proc = None

    async def _ensure_started(self) -> None:
        if self._browser is not None or self._context is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("playwright backend requested but playwright is not installed") from exc
        self._baseline_browser_pids = _browser_like_descendants(os.getpid())
        self._playwright = await async_playwright().start()
        try:
            if self.config.obscura_enabled:
                if self.config.obscura_managed:
                    await self._start_managed_obscura()
                self._browser = await self._playwright.chromium.connect_over_cdp(self._obscura_cdp_endpoint())
                self._cdp_connected = True
                self._persistent_context = False
                self._tracked_browser_pids = set()
            elif self.config.playwright_cdp_endpoint:
                self._browser = await self._playwright.chromium.connect_over_cdp(self.config.playwright_cdp_endpoint)
                self._cdp_connected = True
                self._persistent_context = False
                self._tracked_browser_pids = set()
            elif self._uses_persistent_profile():
                self._context = await self._playwright.chromium.launch_persistent_context(
                    self.config.playwright_user_data_dir,
                    **self._persistent_context_launch_kwargs(),
                )
                self._browser = None
                self._cdp_connected = False
                self._persistent_context = True
                self._owns_context = True
                self._tracked_browser_pids = _browser_like_descendants(os.getpid()) - self._baseline_browser_pids
                await self._initialize_context_locked()
            else:
                launch_kwargs: dict[str, object] = {"headless": self.config.playwright_headless}
                if self.config.playwright_browser_channel:
                    launch_kwargs["channel"] = self.config.playwright_browser_channel
                if self.config.playwright_executable_path:
                    launch_kwargs["executable_path"] = self.config.playwright_executable_path
                self._browser = await self._playwright.chromium.launch(**launch_kwargs)
                self._cdp_connected = False
                self._persistent_context = False
                self._tracked_browser_pids = _browser_like_descendants(os.getpid()) - self._baseline_browser_pids
            if not self._persistent_context:
                await self._create_context_locked()
        except Exception:
            if self._context is not None:
                with contextlib.suppress(Exception):
                    await self._context.close()
                self._context = None
            if self._browser is not None:
                with contextlib.suppress(Exception):
                    await self._browser.close()
                self._browser = None
            if self._playwright is not None:
                with contextlib.suppress(Exception):
                    await self._playwright.stop()
                self._playwright = None
            await self._terminate_managed_obscura()
            self._tracked_browser_pids.clear()
            self._baseline_browser_pids.clear()
            self._persistent_context = False
            raise

    async def fetch(self, url: str) -> FetchResponse:
        async with self._lock:
            await self._ensure_started()
            if self._context_recycle_requested and self._active_pages == 0:
                await self._recycle_context_locked()
            context = self._context
            assert context is not None
            self._active_pages += 1
            self._context_request_count += 1
            if (
                not self._persistent_context
                and self.config.max_requests_per_context > 0
                and self._context_request_count >= self.config.max_requests_per_context
            ):
                self._context_recycle_requested = True

        page = None
        try:
            page = await context.new_page()

            auth = self.config.auth
            if auth and auth.enabled:
                from urllib.parse import urlparse
                allowed_netloc = auth.domain.lower() if auth.domain else urlparse(url).netloc.lower()
                auth_headers = auth.auth_headers()
                if auth.auth_type == "basic" and auth.username and auth.password:
                    import base64
                    encoded = base64.b64encode(f"{auth.username}:{auth.password}".encode()).decode("utf-8")
                    auth_headers["Authorization"] = f"Basic {encoded}"

                def _auth_match(request_url: str) -> bool:
                    return urlparse(request_url).netloc.lower() == allowed_netloc

                async def _auth_route(route, request):
                    headers = request.headers.copy()
                    headers.update(auth_headers)
                    try:
                        # route.fetch automatically follows redirects and natively
                        # strips custom headers (like Authorization) on cross-origin
                        # hops, while preserving them for same-origin (ticket 129).
                        response = await route.fetch(headers=headers)
                        await route.fulfill(response=response)
                    except Exception:
                        await route.continue_(headers=headers)

                with contextlib.suppress(Exception):
                    await page.route(_auth_match, _auth_route)

            # Per-domain User-Agent override (ticket 080). The context carries the
            # default UA; a per-page extra header swaps the sent User-Agent for
            # this domain without recycling the shared context.
            if self.config.ua_map:
                await page.set_extra_http_headers({"User-Agent": self.config.user_agent_for(url)})
            timeout_ms = self._timeout_ms(self.config.timeout_seconds)
            page.set_default_timeout(timeout_ms)
            page.set_default_navigation_timeout(timeout_ms)
            started = time.monotonic()
            response = await asyncio.wait_for(
                page.goto(
                    url,
                    timeout=timeout_ms,
                    wait_until="domcontentloaded",
                ),
                timeout=self.config.timeout_seconds + 1.0,
            )
            ttfb = time.monotonic() - started
            if self.config.playwright_network_idle_timeout_seconds > 0:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(
                        page.wait_for_load_state(
                            "networkidle",
                            timeout=self._timeout_ms(self.config.playwright_network_idle_timeout_seconds),
                        ),
                        timeout=self.config.playwright_network_idle_timeout_seconds + 1.0,
                    )
            # Ticket 031: wait for a specific selector on SPAs that hydrate
            # content asynchronously. Times out gracefully (suppressed) so a
            # missing selector degrades to "snapshot what we have" rather than
            # failing the fetch.
            selector = self.config.playwright_wait_for_selector
            if selector:
                sel_timeout = self.config.playwright_wait_for_selector_timeout_seconds
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(
                        page.wait_for_selector(selector, timeout=self._timeout_ms(sel_timeout)),
                        timeout=sel_timeout + 1.0,
                    )
            html = await asyncio.wait_for(page.content(), timeout=self.config.timeout_seconds + 1.0)
            lcp_ms = cls = inp_ms = None
            if self.config.collect_web_vitals:
                lcp_ms, cls, inp_ms = await self._read_web_vitals(page)
            elapsed = time.monotonic() - started
            header_map = dict(response.headers) if response else {}
            body = html.encode("utf-8")[: self.config.max_response_bytes]
            redirect_chain = await _playwright_redirect_chain(response)
            return FetchResponse(
                url=page.url,
                requested_url=url,
                status=response.status if response else 0,
                headers=header_map,
                body=body,
                text=html,
                ttfb_seconds=ttfb,
                elapsed_seconds=elapsed,
                lcp_ms=lcp_ms,
                cls=cls,
                inp_ms=inp_ms,
                redirect_chain=redirect_chain,
            )
        finally:
            if page is not None:
                with contextlib.suppress(Exception):
                    await page.close()
            async with self._lock:
                self._active_pages = max(0, self._active_pages - 1)
                if self._context_recycle_requested and self._active_pages == 0:
                    await self._recycle_context_locked()

    async def _kill_tracked_browser_processes(self) -> None:
        candidate_pids = set(self._tracked_browser_pids)
        if self._baseline_browser_pids:
            candidate_pids |= _browser_like_descendants(os.getpid()) - self._baseline_browser_pids
        if not candidate_pids:
            return

        signals = [signal.SIGTERM]
        if hasattr(signal, "SIGKILL"):
            signals.append(signal.SIGKILL)

        for sig in signals:
            survivors: set[int] = set()
            for pid in sorted(candidate_pids):
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    continue
                except PermissionError:
                    survivors.add(pid)
                else:
                    survivors.add(pid)
            if not survivors:
                break
            await asyncio.sleep(0.2)
            candidate_pids = {pid for pid in survivors if Path(f"/proc/{pid}").exists()}

    async def close(self) -> None:
        try:
            if self._context:
                # Don't close a context borrowed from a CDP server (Obscura's
                # single default context); just drop our reference. browser.close()
                # below detaches the CDP connection and leaves the server intact.
                if self._owns_context:
                    with contextlib.suppress(Exception):
                        await self._context.close()
                self._context = None
            if self._browser:
                with contextlib.suppress(Exception):
                    await self._browser.close()
                self._browser = None
            if self._playwright:
                with contextlib.suppress(Exception):
                    await self._playwright.stop()
                self._playwright = None
        finally:
            await self._terminate_managed_obscura()
            await self._kill_tracked_browser_processes()
            self._tracked_browser_pids.clear()
            self._baseline_browser_pids.clear()
            self._context_request_count = 0
            self._context_recycle_requested = False
            self._active_pages = 0
            self._persistent_context = False
            self._obscura_stderr.clear()


# Eval expression run on the rendered page to return the final URL and full
# serialized DOM in one JSON payload, so a single `obscura fetch` yields both.
_OBSCURA_FETCH_EVAL = "JSON.stringify({u:location.href,h:document.documentElement.outerHTML})"
# URL suffixes / markers that should be fetched as the raw HTTP body (sitemaps,
# feeds, plain text) rather than a rendered DOM. `obscura fetch --dump original`
# streams the verbatim response body, which is what the sitemap parser expects.
_OBSCURA_RAW_SUFFIXES = (".xml", ".xml.gz", ".gz", ".txt", ".rss", ".atom")


class ObscuraFetchBackend(FetchBackend):
    """Fetch via Obscura's one-shot ``obscura fetch`` subprocess (no CDP).

    Each request spawns the ``obscura`` binary, which renders the page in a
    stealth browser and prints the result. This trades per-request process
    spawn cost for robustness: it sidesteps the persistent CDP session
    (``connect_over_cdp``/``page.goto``) that can hang indefinitely in some
    sandboxes. Honours ``obscura_stealth`` and ``obscura_proxy``.
    """

    def __init__(self, config: CrawlConfig) -> None:
        super().__init__(config)
        self._binary = config.obscura_binary or "obscura"
        # Stealth defaults on for resilience unless explicitly disabled.
        self._stealth = config.obscura_stealth is not False

    def _is_raw_url(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        if any(path.endswith(suffix) for suffix in _OBSCURA_RAW_SUFFIXES):
            return True
        return "sitemap" in path

    def _build_argv(self, url: str, *, raw: bool) -> list[str]:
        argv = [self._binary, "fetch"]
        if self._stealth:
            argv.append("--stealth")
        if self.config.obscura_proxy:
            argv.extend(["--proxy", self.config.obscura_proxy])
        elif self._proxy_pool is not None:
            proxy = self._proxy_pool.select(url)
            if proxy:
                argv.extend(["--proxy", proxy])
        ua = self.config.user_agent_for(url)
        if ua:
            argv.extend(["--user-agent", ua])
        # Per-fetch timeout (whole-page) — keep below our own wait_for budget.
        argv.extend(["--timeout", str(max(5, int(self.config.timeout_seconds)))])
        if raw:
            argv.extend(["--dump", "original", url])
        else:
            argv.extend(["--eval", _OBSCURA_FETCH_EVAL, url])
        return argv

    async def fetch(self, url: str) -> FetchResponse:
        raw = self._is_raw_url(url)
        argv = self._build_argv(url, raw=raw)
        started = time.monotonic()
        # Hard cap so a stuck subprocess can't wedge the crawl. The binary also
        # has its own --timeout; this is a belt-and-braces parent-side bound.
        deadline = self.config.timeout_seconds + 15.0
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=deadline)
        except asyncio.TimeoutError:
            if proc is not None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                with contextlib.suppress(Exception):
                    await proc.wait()
            return self._error_response(url, started, "obscura fetch timed out")
        except Exception as exc:  # noqa: BLE001 - surface as a status-0 fetch
            return self._error_response(url, started, f"{type(exc).__name__}: {exc}")

        elapsed = time.monotonic() - started
        if proc.returncode != 0 or not stdout:
            detail = (stderr or b"").decode("utf-8", "replace")[:200]
            return self._error_response(url, started, f"exit {proc.returncode}: {detail}")

        cap = self.config.max_response_bytes
        if raw:
            body = stdout[:cap]
            final_url = url
            content_type = (
                "application/xml"
                if url.lower().rstrip("/").endswith((".xml", ".gz", ".rss", ".atom"))
                else "text/plain"
            )
            text = _decode_body(body, content_type)
        else:
            try:
                payload = json.loads(stdout.decode("utf-8", "replace"))
                html = payload.get("h") or ""
                final_url = payload.get("u") or url
            except (ValueError, AttributeError):
                # Fall back to treating stdout as raw HTML if eval JSON parsing fails.
                html = stdout.decode("utf-8", "replace")
                final_url = url
            text = html[:cap]
            body = text.encode("utf-8")
            content_type = "text/html; charset=utf-8"

        return FetchResponse(
            url=final_url,
            requested_url=url,
            status=200,
            headers={"content-type": content_type},
            body=body,
            text=text,
            ttfb_seconds=elapsed,
            elapsed_seconds=elapsed,
            body_truncated=len(body) >= cap,
        )

    @staticmethod
    def _error_response(url: str, started: float, _detail: str) -> FetchResponse:
        elapsed = time.monotonic() - started
        return FetchResponse(
            url=url,
            requested_url=url,
            status=0,
            headers={},
            body=b"",
            text="",
            ttfb_seconds=elapsed,
            elapsed_seconds=elapsed,
        )


def build_backend(config: CrawlConfig) -> FetchBackend:
    if config.obscura_enabled and config.obscura_fetch_subprocess:
        return ObscuraFetchBackend(config)
    if config.backend == "aiohttp":
        return AiohttpBackend(config)
    if config.backend == "curl_cffi":
        return CurlCffiBackend(config)
    if config.backend == "playwright":
        return PlaywrightBackend(config)
    raise ValueError(f"Unsupported backend: {config.backend}")


class RateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval_seconds = min_interval_seconds
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def wait(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait_for = self.min_interval_seconds - (now - self._last_request_at)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
                now = loop.time()
            self._last_request_at = now
