from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import ssl
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path

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
    headers = {"User-Agent": config.user_agent, **config.request_headers}
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


class FetchBackend(ABC):
    def __init__(self, config: CrawlConfig) -> None:
        self.config = config
        self._proxy_pool: ProxyPool | None = None
        if config.proxies:
            self._proxy_pool = ProxyPool(
                proxies=list(config.proxies),
                rotation=config.proxy_rotation,
                max_failures=config.proxy_max_failures,
                cooldown_seconds=config.proxy_cooldown_seconds,
            )

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
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode(
                "utf-8",
                errors="ignore",
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
            # Proxy is a per-context setting in Playwright, so pool rotation is
            # at context granularity, not per request (ticket 045): one proxy is
            # picked when a context is created and reused until it recycles.
            if self._proxy_pool is not None:
                pooled = self._proxy_pool.select("")
                if pooled is not None:
                    context_kwargs["proxy"] = {"server": pooled}
            else:
                proxy_setting = _playwright_proxy(self.config)
                if proxy_setting is not None:
                    context_kwargs["proxy"] = proxy_setting
        auth = self.config.auth
        if auth and auth.enabled and auth.basic_credentials():
            user, password = auth.basic_credentials()  # type: ignore[misc]
            context_kwargs["http_credentials"] = {"username": user, "password": password}
        if auth and auth.enabled:
            context_kwargs["extra_http_headers"] = {
                **extra_headers,
                **auth.auth_headers(),
            }
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

    async def _create_context_locked(self) -> None:
        assert self._browser is not None
        self._context = await self._browser.new_context(**self._context_kwargs())
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
        old_context = self._context
        self._context = None
        self._context_request_count = 0
        self._context_recycle_requested = False
        if old_context is not None:
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
        if self.config.obscura_proxy:
            argv.extend(["--proxy", self.config.obscura_proxy])
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
                if (
                    self._managed_obscura_proc.stderr is not None
                    and self._managed_obscura_proc.returncode is None
                ):
                    with contextlib.suppress(Exception):
                        data = await asyncio.wait_for(
                            self._managed_obscura_proc.stderr.read(4096), timeout=0.2
                        )
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
        if self._browser is not None:
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
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    self._obscura_cdp_endpoint()
                )
                self._tracked_browser_pids = set()
            elif self.config.playwright_cdp_endpoint:
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    self.config.playwright_cdp_endpoint
                )
                self._tracked_browser_pids = set()
            else:
                self._browser = await self._playwright.chromium.launch(headless=True)
                self._tracked_browser_pids = _browser_like_descendants(os.getpid()) - self._baseline_browser_pids
            await self._create_context_locked()
        except Exception:
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
                self.config.max_requests_per_context > 0
                and self._context_request_count >= self.config.max_requests_per_context
            ):
                self._context_recycle_requested = True

        page = None
        try:
            page = await context.new_page()
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
            self._obscura_stderr.clear()


def build_backend(config: CrawlConfig) -> FetchBackend:
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
