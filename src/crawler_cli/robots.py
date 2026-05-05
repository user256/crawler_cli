from __future__ import annotations

import asyncio
import time
import urllib.robotparser
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urlparse

import aiohttp

from .config import CrawlConfig


def calculate_cache_ttl(headers: dict[str, str], default_ttl: int = 3600) -> int:
    """Lifted from PostgreSQLCrawlerWIP: derive TTL from response headers when possible."""
    try:
        headers_lower = {key.lower(): value for key, value in headers.items()}

        cache_control = headers_lower.get("cache-control", "").lower()
        if cache_control:
            if "max-age=" in cache_control:
                max_age_str = cache_control.split("max-age=")[1].split(",")[0].strip()
                try:
                    return int(max_age_str)
                except ValueError:
                    pass
            if "no-cache" in cache_control or "no-store" in cache_control:
                return 0

        expires = headers_lower.get("expires")
        if expires:
            try:
                expires_dt = parsedate_to_datetime(expires)
                ttl = int(expires_dt.timestamp() - time.time())
                return max(0, ttl)
            except (ValueError, TypeError):
                pass

        last_modified = headers_lower.get("last-modified")
        if last_modified:
            try:
                last_modified_dt = parsedate_to_datetime(last_modified)
                age = time.time() - last_modified_dt.timestamp()
                heuristic_ttl = int(age * 0.1)
                return max(0, min(heuristic_ttl, default_ttl))
            except (ValueError, TypeError):
                pass

        return default_ttl
    except Exception:
        return default_ttl


class RobotsCache:
    """Lifted and adapted from PostgreSQLCrawlerWIP."""

    def __init__(self, default_ttl: int = 86400) -> None:
        self._cache: dict[str, tuple[urllib.robotparser.RobotFileParser, float, dict[str, float], dict[str, str]]] = {}
        self._failed_domains: set[str] = set()
        self._default_ttl = default_ttl

    def get_robots_parser(self, domain: str) -> Optional[urllib.robotparser.RobotFileParser]:
        if domain not in self._cache:
            return None

        parser, cached_time, _, headers = self._cache[domain]
        server_ttl = calculate_cache_ttl(headers, self._default_ttl)
        if time.time() - cached_time > server_ttl:
            del self._cache[domain]
            return None
        return parser

    def get_crawl_delay(self, domain: str, user_agent: str = "*") -> Optional[float]:
        if domain not in self._cache:
            return None

        _, cached_time, crawl_delays, headers = self._cache[domain]
        server_ttl = calculate_cache_ttl(headers, self._default_ttl)
        if time.time() - cached_time > server_ttl:
            del self._cache[domain]
            return None
        return crawl_delays.get(user_agent) or crawl_delays.get("*")

    def set_robots_parser(
        self,
        domain: str,
        parser: urllib.robotparser.RobotFileParser,
        crawl_delays: dict[str, float] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._cache[domain] = (parser, time.time(), crawl_delays or {}, headers or {})

    def mark_failed(self, domain: str) -> None:
        self._failed_domains.add(domain)

    def is_failed(self, domain: str) -> bool:
        return domain in self._failed_domains


class RobotsPolicyCache:
    def __init__(self, config: CrawlConfig) -> None:
        self.config = config
        self.cache = RobotsCache(default_ttl=int(config.robots_cache_ttl_seconds))
        self._locks: dict[str, asyncio.Lock] = {}

    async def get_policy(self, url: str) -> Optional[urllib.robotparser.RobotFileParser]:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        if self.cache.is_failed(domain):
            return None

        cached = self.cache.get_robots_parser(domain)
        if cached is not None:
            return cached

        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock:
            cached = self.cache.get_robots_parser(domain)
            if cached is not None:
                return cached
            return await self._parse_robots_txt(domain)

    async def is_allowed(self, url: str) -> bool:
        domain = urlparse(url).netloc.lower()
        if self.cache.is_failed(domain):
            return True

        parser = await self.get_policy(url)
        if parser is None:
            return True

        entries = getattr(parser, "_entries", {}).get(self.config.user_agent, []) + getattr(parser, "_entries", {}).get("*", [])
        if not entries:
            return True

        path = urlparse(url).path or "/"
        allowed = True
        for rule_type, rule_path in entries:
            matches = False
            if rule_path == "/":
                matches = True
            elif rule_path.endswith("*"):
                matches = path.startswith(rule_path[:-1])
            else:
                matches = path.startswith(rule_path)

            if not matches:
                continue
            if rule_type == "allow":
                allowed = True
            elif rule_type == "disallow":
                allowed = False
        return allowed

    async def get_crawl_delay(self, url: str) -> Optional[float]:
        domain = urlparse(url).netloc.lower()
        await self.get_policy(url)
        return self.cache.get_crawl_delay(domain, self.config.user_agent)

    async def _fetch_robots_txt(self, domain: str) -> tuple[str | None, dict[str, str]]:
        robots_url = f"https://{domain}/robots.txt"
        try:
            timeout = aiohttp.ClientTimeout(total=min(self.config.timeout_seconds, 10.0))
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    robots_url,
                    headers={"User-Agent": self.config.user_agent, **self.config.request_headers},
                    ssl=self.config.verify_ssl,
                ) as response:
                    headers = dict(response.headers)
                    if response.status == 200:
                        return await response.text(errors="ignore"), headers
                    if response.status >= 500:
                        return None, headers
                    return None, headers
        except Exception:
            return None, {}

    async def _parse_robots_txt(self, domain: str) -> Optional[urllib.robotparser.RobotFileParser]:
        robots_content, headers = await self._fetch_robots_txt(domain)
        if robots_content is None:
            self.cache.mark_failed(domain)
            return None

        try:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(f"https://{domain}/robots.txt")
            parser._user_agents = []
            parser._entries = {}

            current_user_agent = None
            crawl_delays: dict[str, float] = {}
            for line in robots_content.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip().lower()
                value = value.strip()

                if key == "user-agent":
                    current_user_agent = value
                    if current_user_agent not in parser._user_agents:
                        parser._user_agents.append(current_user_agent)
                elif key in {"disallow", "allow"} and current_user_agent:
                    parser._entries.setdefault(current_user_agent, []).append((key, value))
                elif key == "crawl-delay" and current_user_agent:
                    try:
                        crawl_delays[current_user_agent] = float(value)
                    except ValueError:
                        pass

            if not parser._user_agents:
                parser._user_agents = ["*"]
                parser._entries.setdefault("*", [])

            self.cache.set_robots_parser(domain, parser, crawl_delays, headers)
            return parser
        except Exception:
            self.cache.mark_failed(domain)
            return None
