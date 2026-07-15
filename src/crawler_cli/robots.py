from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urlparse

import aiohttp

from .backends import _proxy_url, build_proxy_pool
from .config import CrawlConfig
from .proxy_pool import ProxyPool


@lru_cache(maxsize=2048)
def _robots_pattern(rule: str) -> re.Pattern[str]:
    """Compile a robots.txt path rule into a regex per RFC 9309.

    Only '*' (any sequence) and a trailing '$' (end-of-path anchor) are special;
    every other character is matched literally. The pattern is left-anchored
    because robots rules match a path prefix.
    """
    anchored_end = rule.endswith("$")
    body = rule[:-1] if anchored_end else rule
    # Escape literals, then turn the escaped '*' back into a wildcard.
    regex = re.escape(body).replace(r"\*", ".*")
    regex = "^" + regex + ("$" if anchored_end else "")
    return re.compile(regex)


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


def _path_with_query(url: str) -> str:
    """Return the path (+ query if present) used for robots rule matching.

    RFC 9309 §2.2.2 matches against the URI path; query is part of the path
    component for pattern matching (e.g. ``Disallow: /*?``).
    """
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


@dataclass(slots=True)
class RobotsDecision:
    allowed: bool
    matched_rule: str | None
    matched_user_agent: str | None
    source_url: str


class _RobotsRules:
    """Minimal robots.txt parser that exposes matched rules.

    Implements RFC 9309 longest-match precedence with Allow tie-break and
    case-insensitive product-token user-agent matching.

    Consecutive ``User-agent`` lines (before any allow/disallow/crawl-delay)
    form one shared group. Repeated groups that match the same crawler are
    combined when evaluating rules (RFC 9309 §2.2.1).
    """

    def __init__(self, domain: str, content: str, *, scheme: str = "https") -> None:
        self.domain = domain
        self.source_url = f"{scheme}://{domain}/robots.txt"
        self._groups: dict[str, list[tuple[str, str]]] = {}
        self._crawl_delays: dict[str, float] = {}
        self._sitemaps: list[str] = []
        current_uas: list[str] = []
        in_rules = False
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "user-agent":
                if in_rules:
                    current_uas = [value]
                    in_rules = False
                else:
                    current_uas.append(value)
                for ua in current_uas:
                    self._groups.setdefault(ua, [])
            elif key in {"disallow", "allow"} and current_uas:
                in_rules = True
                for ua in current_uas:
                    self._groups.setdefault(ua, []).append((key, value))
            elif key == "crawl-delay" and current_uas:
                in_rules = True
                try:
                    delay = float(value)
                except ValueError:
                    continue
                for ua in current_uas:
                    self._crawl_delays[ua] = delay
            elif key == "sitemap":
                # Sitemap is not a group rule; it must not terminate a
                # consecutive User-agent start-group (Google / common practice).
                self._sitemaps.append(value)
        if not self._groups:
            self._groups["*"] = []

    def _matching_group_keys(self, user_agent: str) -> list[str]:
        """Return all group keys that match *user_agent* (to be combined).

        Matching order (per RFC 9309 §2.2.1):
        1. Exact case-insensitive match on the full token (all such groups).
        2. Case-insensitive prefix/product-token match (e.g. group
           ``crawler_cli`` matches UA ``crawler_cli/0.1``).
        3. The catch-all ``*`` group.
        Specific matches are never combined with ``*``.
        """
        ua_lower = user_agent.lower()
        exact = [key for key in self._groups if key.lower() == ua_lower]
        if exact:
            return exact
        product: list[str] = []
        for key in self._groups:
            if key == "*":
                continue
            token = key.lower()
            if ua_lower == token or ua_lower.startswith(token + "/") or ua_lower.startswith(token + " "):
                product.append(key)
        if product:
            return product
        if "*" in self._groups:
            return ["*"]
        return []

    def _matching_group_key(self, user_agent: str) -> str | None:
        """Return the primary matching group key (first combined key), or None."""
        keys = self._matching_group_keys(user_agent)
        return keys[0] if keys else None

    def check(self, path: str, user_agent: str) -> RobotsDecision:
        """Return the allow/disallow decision for *path* using longest-match
        precedence with Allow tie-break (RFC 9309 §2.2.2).

        The most specific (longest rule pattern) matching rule wins.  When two
        rules of equal specificity conflict, Allow beats Disallow.  Rules from
        all matching groups for *user_agent* are combined before evaluation.
        """
        group_keys = self._matching_group_keys(user_agent)
        rules: list[tuple[str, str]] = []
        for key in group_keys:
            rules.extend(self._groups.get(key, []))

        best_len = -1
        best_type: str | None = None
        best_rule: str | None = None
        best_ua: str | None = group_keys[0] if group_keys else None

        for rule_type, rule_path in rules:
            if not self._match(path, rule_path):
                continue
            rule_len = len(rule_path)
            if rule_len > best_len:
                best_len = rule_len
                best_type = rule_type
                best_rule = rule_path
            elif rule_len == best_len and rule_type == "allow" and best_type == "disallow":
                # Equal specificity: Allow wins.
                best_type = rule_type
                best_rule = rule_path

        if best_type is None:
            return RobotsDecision(
                allowed=True,
                matched_rule=None,
                matched_user_agent=None,
                source_url=self.source_url,
            )
        return RobotsDecision(
            allowed=(best_type == "allow"),
            matched_rule=f"{best_type.capitalize()}: {best_rule}",
            matched_user_agent=best_ua,
            source_url=self.source_url,
        )

    def crawl_delay(self, user_agent: str) -> float | None:
        delays = [
            self._crawl_delays[key]
            for key in self._matching_group_keys(user_agent)
            if key in self._crawl_delays
        ]
        if not delays:
            return None
        # Prefer the most conservative delay when multiple matching groups set one.
        return max(delays)

    def sitemaps(self) -> list[str]:
        return list(self._sitemaps)

    @staticmethod
    def _match(path: str, rule: str) -> bool:
        if not rule:
            return False
        if rule == "/":
            return True
        # RFC 9309 wildcard matching: '*' matches any sequence, a trailing '$'
        # anchors the end of the path. Every other character — including '?' —
        # is LITERAL. (Do not use fnmatch: there '?' means "one char" and
        # '[...]' are classes, which over-match robots patterns. e.g. the common
        # Magento rule "Disallow: /*?" must only block URLs containing '?', not
        # every path.)
        if "*" in rule or rule.endswith("$"):
            return _robots_pattern(rule).match(path) is not None
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
        """Record that robots.txt was unreachable (5xx / network) for *domain*.

        Per RFC 9309 §2.3.1.4, unreachable robots.txt means complete disallow
        for the remainder of this crawl session.
        """
        self._failed_domains.add(domain)

    def is_failed(self, domain: str) -> bool:
        return domain in self._failed_domains


class RobotsPolicyCache:
    """Fetch, cache, and evaluate robots.txt for crawl URLs.

    Temporary-failure policy (RFC 9309 §2.3.1.4): when robots.txt is
    unreachable due to HTTP 5xx or a network error, the host is marked failed
    and ``check()`` returns ``allowed=False`` (complete disallow) for the rest
    of the session. HTTP 4xx remains allow-all (§2.3.1.3).
    """

    def __init__(self, config: CrawlConfig) -> None:
        self.config = config
        self.cache = RobotsCache(default_ttl=int(config.robots_cache_ttl_seconds))
        self._locks: dict[str, asyncio.Lock] = {}
        self._proxy_pool: ProxyPool | None = build_proxy_pool(config)

    def _user_agent_for(self, url: str) -> str:
        return self.config.user_agent_for(url)

    def _select_proxy(self, robots_url: str) -> str | None:
        if self._proxy_pool is not None:
            return self._proxy_pool.select(robots_url)
        return _proxy_url(self.config)

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
            return await self._fetch_and_parse(url)

    async def check(self, url: str) -> RobotsDecision:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        source_url = f"{parsed.scheme}://{domain}/robots.txt"
        if self.cache.is_failed(domain):
            # RFC 9309 §2.3.1.4: unreachable → complete disallow.
            return RobotsDecision(
                allowed=False,
                matched_rule="robots.txt unreachable",
                matched_user_agent=None,
                source_url=source_url,
            )

        rules = await self.get_rules(url)
        if rules is None:
            # Still unreachable after fetch attempt (or mark_failed mid-flight).
            if self.cache.is_failed(domain):
                return RobotsDecision(
                    allowed=False,
                    matched_rule="robots.txt unreachable",
                    matched_user_agent=None,
                    source_url=source_url,
                )
            return RobotsDecision(
                allowed=True,
                matched_rule=None,
                matched_user_agent=None,
                source_url=source_url,
            )

        path = _path_with_query(url)
        return rules.check(path, self._user_agent_for(url))

    async def is_allowed(self, url: str) -> bool:
        decision = await self.check(url)
        return decision.allowed

    async def get_crawl_delay(self, url: str) -> Optional[float]:
        domain = urlparse(url).netloc.lower()
        await self.get_rules(url)
        return self.cache.get_crawl_delay(domain, self._user_agent_for(url))

    async def sitemaps(self, url: str) -> list[str]:
        rules = await self.get_rules(url)
        if rules is None:
            return []
        return rules.sitemaps()

    async def _fetch_robots_txt(self, url: str) -> tuple[str | None, dict[str, str], int]:
        """Fetch robots.txt for the scheme+netloc of *url*.

        Returns (content_or_None, response_headers, http_status).
        Uses the same scheme/host as the crawled URL so http:// sites
        are fetched over http, not https.

        Requests go through the configured proxy pool / proxy+auth. Headers
        carry only the effective per-URL User-Agent — crawl-target cookies,
        Authorization, and ``request_headers`` are intentionally omitted so
        site credentials do not leak across hosts on this dedicated session.
        """
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        req_headers = {"User-Agent": self._user_agent_for(robots_url)}
        proxy = self._select_proxy(robots_url)
        try:
            timeout = aiohttp.ClientTimeout(total=min(self.config.timeout_seconds, 10.0))
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    robots_url,
                    headers=req_headers,
                    ssl=self.config.verify_ssl,
                    proxy=proxy or None,
                    allow_redirects=True,
                ) as response:
                    headers = dict(response.headers)
                    status = response.status
                    if status == 200:
                        return await response.text(errors="ignore"), headers, status
                    return None, headers, status
        except Exception:
            return None, {}, 0

    async def _fetch_and_parse(self, url: str) -> _RobotsRules | None:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        robots_content, headers, status = await self._fetch_robots_txt(url)

        if robots_content is None:
            if status >= 500 or status == 0:
                # RFC 9309 §2.3.1.4: server/network unreachable → complete
                # disallow for this session (see RobotsPolicyCache.check).
                self.cache.mark_failed(domain)
            # 4xx (including 404): allow-all per RFC 9309 §2.3.1.3.
            elif 400 <= status < 500:
                rules = _RobotsRules(domain, "")
                self.cache.set_rules(domain, rules, headers)
                return rules
            return None

        try:
            rules = _RobotsRules(domain, robots_content, scheme=parsed.scheme)
            self.cache.set_rules(domain, rules, headers)
            return rules
        except Exception:
            self.cache.mark_failed(domain)
            return None
