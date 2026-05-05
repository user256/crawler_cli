from __future__ import annotations

import asyncio
import ssl
from abc import ABC, abstractmethod

import aiohttp
from curl_cffi.requests import AsyncSession

from .config import CrawlConfig
from .models import FetchResponse


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


class AiohttpBackend(FetchBackend):
    async def fetch(self, url: str) -> FetchResponse:
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        ssl_context = None
        if not self.config.verify_ssl:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        headers = {"User-Agent": self.config.user_agent, **self.config.request_headers}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=self.config.follow_redirects, ssl=ssl_context) as response:
                body = await response.read()
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
                )


class CurlCffiBackend(FetchBackend):
    async def fetch(self, url: str) -> FetchResponse:
        headers = {"User-Agent": self.config.user_agent, **self.config.request_headers}
        async with AsyncSession() as session:
            response = await session.get(
                url,
                headers=headers,
                timeout=self.config.timeout_seconds,
                allow_redirects=self.config.follow_redirects,
                verify=self.config.verify_ssl,
            )
        body = response.content[: self.config.max_response_bytes]
        header_map = dict(response.headers)
        return FetchResponse(
            url=str(response.url),
            requested_url=url,
            status=response.status_code,
            headers=header_map,
            body=body,
            text=_decode_body(body, header_map.get("Content-Type")),
        )


class PlaywrightBackend(FetchBackend):
    async def fetch(self, url: str) -> FetchResponse:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("playwright backend requested but playwright is not installed") from exc

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=self.config.user_agent,
                ignore_https_errors=not self.config.verify_ssl,
                extra_http_headers=self.config.request_headers,
            )
            page = await context.new_page()
            try:
                response = await page.goto(
                    url,
                    timeout=int(self.config.timeout_seconds * 1000),
                    wait_until="networkidle",
                )
                html = await page.content()
                header_map = dict(response.headers) if response else {}
                body = html.encode("utf-8")[: self.config.max_response_bytes]
                return FetchResponse(
                    url=page.url,
                    requested_url=url,
                    status=response.status if response else 0,
                    headers=header_map,
                    body=body,
                    text=html,
                )
            finally:
                await context.close()
                await browser.close()


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
