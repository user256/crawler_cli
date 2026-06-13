"""Proxy pool with rotation and failure-based eviction (ticket 045).

Extends the single-proxy support from ticket-027 to a pool of egress proxies.
Two rotation strategies:

* ``round-robin`` — each ``select`` advances to the next live proxy.
* ``per-host`` — a proxy is chosen per target host and stuck to it (better for
  sites that bind sessions to an IP), re-chosen only if that proxy is evicted.

A proxy is evicted (placed on cooldown) after ``max_failures`` consecutive
failures and returns to rotation once ``cooldown_seconds`` have elapsed.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class _ProxyState:
    url: str
    consecutive_failures: int = 0
    cooled_until: float = 0.0  # monotonic time the proxy is unavailable until

    def is_available(self, now: float) -> bool:
        return now >= self.cooled_until


@dataclass
class ProxyPool:
    """A rotating pool of proxy URLs with eviction.

    Thread-safe (a simple lock guards selection/reporting) so it is safe under
    the engine's concurrent ``fetch`` calls.
    """

    proxies: list[str]
    rotation: str = "round-robin"  # or "per-host"
    max_failures: int = 3
    cooldown_seconds: float = 60.0
    _states: list[_ProxyState] = field(default_factory=list)
    _rr_index: int = 0
    _host_assignments: dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        # Deduplicate while preserving order.
        unique = list(dict.fromkeys(self.proxies))
        self._states = [_ProxyState(url=p) for p in unique]
        if self.rotation not in {"round-robin", "per-host"}:
            raise ValueError(f"Unknown proxy rotation strategy: {self.rotation}")

    @property
    def size(self) -> int:
        return len(self._states)

    def _available_states(self, now: float) -> list[_ProxyState]:
        return [s for s in self._states if s.is_available(now)]

    def select(self, url: str) -> str | None:
        """Return a proxy URL for *url*, or None when the pool is empty.

        If every proxy is cooling down, the least-recently-cooled one is used
        anyway (better to try a degraded proxy than to drop the request).
        """
        if not self._states:
            return None
        host = (urlparse(url).hostname or "").lower()
        now = time.monotonic()
        with self._lock:
            if self.rotation == "per-host":
                return self._select_per_host(host, now)
            return self._select_round_robin(now)

    def _select_round_robin(self, now: float) -> str:
        n = len(self._states)
        for _ in range(n):
            state = self._states[self._rr_index % n]
            self._rr_index = (self._rr_index + 1) % n
            if state.is_available(now):
                return state.url
        # All cooling down — pick the one closest to recovery.
        return min(self._states, key=lambda s: s.cooled_until).url

    def _select_per_host(self, host: str, now: float) -> str:
        assigned = self._host_assignments.get(host)
        if assigned is not None:
            state = next((s for s in self._states if s.url == assigned), None)
            if state is not None and state.is_available(now):
                return assigned
        # Need a fresh assignment: pick an available proxy round-robin style.
        available = self._available_states(now)
        if available:
            state = available[self._rr_index % len(available)]
            self._rr_index += 1
        else:
            state = min(self._states, key=lambda s: s.cooled_until)
        self._host_assignments[host] = state.url
        return state.url

    def report_success(self, proxy_url: str | None) -> None:
        if proxy_url is None:
            return
        with self._lock:
            for state in self._states:
                if state.url == proxy_url:
                    state.consecutive_failures = 0
                    return

    def report_failure(self, proxy_url: str | None) -> None:
        if proxy_url is None:
            return
        with self._lock:
            for state in self._states:
                if state.url != proxy_url:
                    continue
                state.consecutive_failures += 1
                if state.consecutive_failures >= self.max_failures:
                    state.cooled_until = time.monotonic() + self.cooldown_seconds
                    logger.warning(
                        "Proxy %s evicted for %.0fs after %d consecutive failures",
                        proxy_url, self.cooldown_seconds, state.consecutive_failures,
                    )
                    state.consecutive_failures = 0
                    # Drop any host stickiness to this proxy so traffic moves on.
                    self._host_assignments = {
                        h: p for h, p in self._host_assignments.items() if p != proxy_url
                    }
                return
