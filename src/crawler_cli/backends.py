from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import ssl
import time
from abc import ABC, abstractmethod
from pathlib import Path

import aiohttp
from curl_cffi.requests import AsyncSession

from .config import CrawlConfig
from .cookies import build_cookie_header
from .models import FetchResponse


def _request_headers(config: CrawlConfig, url: str) -> dict[str, str]:
    headers = {"User-Agent": config.user_agent, **config.request_headers}
    if config.cookies:
        existing = headers.get("Cookie")
        cookie_value = build_cookie_header(config.cookies)
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

    @abstractmethod
    async def fetch(self, url: str) -> FetchResponse:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class AiohttpBackend(FetchBackend):
    async def fetch(self, url: str) -> FetchResponse:
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        ssl_context = None
        if not self.config.verify_ssl:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        headers = _request_headers(self.config, url)
        auth = _basic_auth(self.config, url)
        proxy = _proxy_url(self.config)
        started = time.monotonic()
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(
                url,
                allow_redirects=self.config.follow_redirects,
                ssl=ssl_context,
                auth=auth,
                proxy=proxy,
            ) as response:
                # Response headers are available here, before the body is read,
                # so this is a good proxy for time-to-first-byte.
                ttfb = time.monotonic() - started
                body = await response.read()
                elapsed = time.monotonic() - started
                if len(body) > self.config.max_response_bytes:
                    body = body[: self.config.max_response_bytes]
                header_map = dict(response.headers)
                return FetchResponse(
                    url=str(response.url),
                    requested_url=url,
                    status=response.status,
                    headers=header_map,
                    body=body,
                    text=_decode_body(body, header_map.get("Content-Type")),
                    ttfb_seconds=ttfb,
                    elapsed_seconds=elapsed,
                )


class CurlCffiBackend(FetchBackend):
    async def fetch(self, url: str) -> FetchResponse:
        headers = _request_headers(self.config, url)
        auth = None
        if self.config.auth and self.config.auth.applies_to(url):
            auth = self.config.auth.basic_credentials()
        get_kwargs: dict[str, object] = {}
        if self.config.proxy:
            get_kwargs["proxy"] = self.config.proxy
            if self.config.proxy_auth:
                get_kwargs["proxy_auth"] = tuple(self.config.proxy_auth.split(":", 1))
        started = time.monotonic()
        async with AsyncSession() as session:
            response = await session.get(
                url,
                headers=headers,
                auth=auth,
                timeout=self.config.timeout_seconds,
                allow_redirects=self.config.follow_redirects,
                verify=self.config.verify_ssl,
                **get_kwargs,
            )
        elapsed = time.monotonic() - started
        body = response.content[: self.config.max_response_bytes]
        header_map = dict(response.headers)
        # curl_cffi's AsyncSession returns only after the full body is read, and
        # its pooled curl handle makes a precise STARTTRANSFER_TIME (TTFB) lookup
        # unreliable across versions, so we record total duration only and leave
        # ttfb_seconds None. See DECISIONS-2026-06-07.md (ticket 029).
        return FetchResponse(
            url=str(response.url),
            requested_url=url,
            status=response.status_code,
            headers=header_map,
            body=body,
            text=_decode_body(body, header_map.get("Content-Type")),
            ttfb_seconds=None,
            elapsed_seconds=elapsed,
        )


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
        if self.config.cookies:
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

    async def _create_context_locked(self) -> None:
        assert self._browser is not None
        self._context = await self._browser.new_context(**self._context_kwargs())
        self._context_request_count = 0
        self._context_recycle_requested = False

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
