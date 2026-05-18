from __future__ import annotations

import asyncio
import fnmatch
import time
from dataclasses import dataclass
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


@dataclass(slots=True)
class RobotsDecision:
    allowed: bool
    matched_rule: str | None
    matched_user_agent: str | None
    source_url: str


class _RobotsRules:
    """Minimal robots.txt parser that exposes matched rules."""

    def __init__(self, domain: str, content: str) -> None:
        self.domain = domain
        self.source_url = f"https://{domain}/robots.txt"
        self._groups: dict[str, list[tuple[str, str]]] = {}
        self._crawl_delays: dict[str, float] = {}
        self._sitemaps: list[str] = []
        current_ua: str | None = None
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "user-agent":
                current_ua = value
                self._groups.setdefault(current_ua, [])
            elif key in {"disallow", "allow"} and current_ua is not None:
                self._groups[current_ua].append((key, value))
            elif key == "crawl-delay" and current_ua is not None:
                try:
                    self._crawl_delays[current_ua] = float(value)
                except ValueError:
                    pass
            elif key == "sitemap":
                self._sitemaps.append(value)
        if not self._groups:
            self._groups["*"] = []

    def check(self, path: str, user_agent: str) -> RobotsDecision:
        uas = [user_agent, "*"] if user_agent != "*" else ["*"]
        matched_rule: str | None = None
        matched_ua: str | None = None
        allowed = True
        for ua in uas:
            rules = self._groups.get(ua, [])
            for rule_type, rule_path in rules:
                if self._match(path, rule_path):
                    matched_rule = f"{rule_type.capitalize()}: {rule_path}"
                    matched_ua = ua
                    if rule_type == "allow":
                        allowed = True
                    elif rule_type == "disallow":
                        allowed = False
        return RobotsDecision(
            allowed=allowed,
            matched_rule=matched_rule,
            matched_user_agent=matched_ua,
            source_url=self.source_url,
        )

    def crawl_delay(self, user_agent: str) -> float | None:
        return self._crawl_delays.get(user_agent) or self._crawl_delays.get("*")

    def sitemaps(self) -> list[str]:
        return list(self._sitemaps)

    @staticmethod
    def _match(path: str, rule: str) -> bool:
        if rule == "/":
            return True
        if "*" in rule or "?" in rule:
            return fnmatch.fnmatchcase(path, rule)
        return path.startswith(rule)


class RobotsCache:
    """Lifted and adapted from PostgreSQLCrawlerWIP."""

    def __init__(self, default_ttl: int = 86400) -> None:
        self._cache: dict[str, tuple[_RobotsRules, float, dict[str, str]]] = {}
        self._failed_domains: set[str] = set()
        self._default_ttl = default_ttl

    def get_rules(self, domain: str) -> _RobotsRules | None:
        if domain not in self._cache:
            return None
        rules, cached_time, headers = self._cache[domain]
        server_ttl = calculate_cache_ttl(headers, self._default_ttl)
        if time.time() - cached_time > server_ttl:
            del self._cache[domain]
            return None
        return rules

    def get_crawl_delay(self, domain: str, user_agent: str = "*") -> Optional[float]:
        rules = self.get_rules(domain)
        if rules is None:
            return None
        return rules.crawl_delay(user_agent)

    def set_rules(
        self,
        domain: str,
        rules: _RobotsRules,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._cache[domain] = (rules, time.time(), headers or {})

    def mark_failed(self, domain: str) -> None:
        self._failed_domains.add(domain)

    def is_failed(self, domain: str) -> bool:
        return domain in self._failed_domains


class RobotsPolicyCache:
    def __init__(self, config: CrawlConfig) -> None:
        self.config = config
        self.cache = RobotsCache(default_ttl=int(config.robots_cache_ttl_seconds))
        self._locks: dict[str, asyncio.Lock] = {}

    async def get_rules(self, url: str) -> _RobotsRules | None:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        if self.cache.is_failed(domain):
            return None

        cached = self.cache.get_rules(domain)
        if cached is not None:
            return cached

        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock:
            cached = self.cache.get_rules(domain)
            if cached is not None:
                return cached
            return await self._fetch_and_parse(domain)

    async def check(self, url: str) -> RobotsDecision:
        domain = urlparse(url).netloc.lower()
        if self.cache.is_failed(domain):
            return RobotsDecision(
                allowed=True,
                matched_rule=None,
                matched_user_agent=None,
                source_url=f"https://{domain}/robots.txt",
            )

        rules = await self.get_rules(url)
        if rules is None:
            return RobotsDecision(
                allowed=True,
                matched_rule=None,
                matched_user_agent=None,
                source_url=f"https://{domain}/robots.txt",
            )

        path = urlparse(url).path or "/"
        return rules.check(path, self.config.user_agent)

    async def is_allowed(self, url: str) -> bool:
        decision = await self.check(url)
        return decision.allowed

    async def get_crawl_delay(self, url: str) -> Optional[float]:
        domain = urlparse(url).netloc.lower()
        await self.get_rules(url)
        return self.cache.get_crawl_delay(domain, self.config.user_agent)

    async def sitemaps(self, url: str) -> list[str]:
        rules = await self.get_rules(url)
        if rules is None:
            return []
        return rules.sitemaps()

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

    async def _fetch_and_parse(self, domain: str) -> _RobotsRules | None:
        robots_content, headers = await self._fetch_robots_txt(domain)
        if robots_content is None:
            self.cache.mark_failed(domain)
            return None

        try:
            rules = _RobotsRules(domain, robots_content)
            self.cache.set_rules(domain, rules, headers)
            return rules
        except Exception:
            self.cache.mark_failed(domain)
            return None
