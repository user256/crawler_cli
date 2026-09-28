"""Adaptive origin rate calibration and crawl-budget pressure (ticket 261).

Opt-in (``CrawlConfig.adaptive_rate``). The controller only ever *tightens*
the configured politeness: it narrows the per-host concurrency the engine
already enforces (ticket 063) and adds inter-request spacing on top of the
global rate limiter. It never raises concurrency above the configured cap or
lowers the configured delay, so on a 429 the crawl slows down rather than
escalating.

Everything here is deterministic given an injected ``clock`` and ``sleep``,
so tests drive it with simulated latency curves and no real waiting.

Retry-After parsing is intentionally local and small. Ticket 181 (typed
rate-limit outcomes) and ticket 224 (shared per-host rate limit) are not yet
built; when they land, :func:`parse_retry_after` and
:class:`AdaptiveRateRegistry` are the seams they should replace or feed.
"""

from __future__ import annotations

import asyncio
import contextlib
import statistics
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

PRESSURE_STATUSES = frozenset({429, 503})

RATE_LIMIT_HEADER_NAMES = (
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
    "ratelimit-policy",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "retry-after",
)

ADAPTIVE_CALIBRATION_MAX_REQUESTS = 20
"""Hard ceiling on calibration requests per origin, whatever the config says."""

ADAPTIVE_CALIBRATION_MAX_ORIGINS = 3
"""Only the first few distinct seed origins are probed; others learn a runtime baseline."""

_HISTORY_LIMIT = 200
_CURVE_LIMIT = 200
_CURVE_EVERY = 10
_ROLLING_WINDOW = 20
_MIN_ROLLING_SAMPLES = 5
_RUNTIME_BASELINE_SAMPLES = 5
_MIN_DEGRADATION_SECONDS = 0.1
"""Absolute floor so a 2 ms loopback baseline does not throttle on 6 ms noise."""
_BACKOFF_BASE_SECONDS = 1.0
_THROTTLE_DELAY_FLOOR_SECONDS = 0.5
_DELAY_EPSILON_SECONDS = 0.05


def _lower_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in (headers or {}).items()}


def parse_retry_after(value: str | None, *, now_epoch: float | None = None) -> float | None:
    """Return the ``Retry-After`` delay in seconds, or ``None`` if unusable.

    Accepts delta-seconds and HTTP-date forms (RFC 9110 §10.2.3). A date in
    the past yields ``0.0``. Negative or malformed values yield ``None``.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        seconds = None
    if seconds is not None:
        if seconds != seconds or seconds < 0 or seconds == float("inf"):
            return None
        return seconds
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc).timestamp() if now_epoch is None else now_epoch
    return max(0.0, when.timestamp() - now)


def detect_origin_stack(headers: Mapping[str, str] | None) -> list[str]:
    """Identify CDN / server software from response headers (best effort)."""
    h = _lower_headers(headers)
    server = h.get("server", "").lower()
    via = h.get("via", "").lower()
    labels: list[str] = []

    def add(label: str) -> None:
        if label not in labels:
            labels.append(label)

    if "cf-ray" in h or "cloudflare" in server:
        add("cloudflare")
    if "fastly" in h.get("x-served-by", "").lower() or "x-fastly-request-id" in h or "fastly" in via:
        add("fastly")
    if "akamai" in server or "akamai-grn" in h or "x-akamai-transformed" in h:
        add("akamai")
    if "x-amz-cf-id" in h or "cloudfront" in via or "cloudfront" in server:
        add("cloudfront")
    if "x-azure-ref" in h:
        add("azure-front-door")
    if "x-vercel-id" in h:
        add("vercel")
    if "x-nf-request-id" in h or "netlify" in server:
        add("netlify")
    if "x-varnish" in h or "varnish" in via:
        add("varnish")
    for name in ("nginx", "apache", "litespeed", "openresty", "caddy", "envoy", "gunicorn", "iis"):
        if name in server:
            add(name)
    return labels


def _parse_non_negative_number(value: str | None) -> float | None:
    if value is None:
        return None
    # Structured RateLimit headers may carry parameters ("100;w=60").
    head = value.split(",", 1)[0].split(";", 1)[0].strip()
    try:
        number = float(head)
    except ValueError:
        return None
    if number != number or number < 0 or number == float("inf"):
        return None
    return number


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = fraction * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


@dataclass(slots=True)
class CalibrationSample:
    url: str
    status: int
    ttfb_seconds: float | None
    headers: dict[str, str] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class CalibrationResult:
    host: str
    requests: int
    statuses: list[int]
    ttfb_median_seconds: float | None
    ttfb_p95_seconds: float | None
    rate_limit_headers: dict[str, str]
    origin_stack: list[str]
    recommended_concurrency: int
    recommended_min_interval_seconds: float
    reasons: list[str]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "requests": self.requests,
            "statuses": list(self.statuses),
            "ttfb_median_seconds": self.ttfb_median_seconds,
            "ttfb_p95_seconds": self.ttfb_p95_seconds,
            "rate_limit_headers": dict(self.rate_limit_headers),
            "origin_stack": list(self.origin_stack),
            "recommended_concurrency": self.recommended_concurrency,
            "recommended_min_interval_seconds": self.recommended_min_interval_seconds,
            "reasons": list(self.reasons),
            "errors": list(self.errors),
        }


def summarize_calibration(
    host: str,
    samples: list[CalibrationSample],
    *,
    max_concurrency: int,
    max_retry_after_seconds: float = 60.0,
    now_epoch: float | None = None,
) -> CalibrationResult:
    """Turn probe samples into a baseline and a recommendation.

    The recommendation is always ``<= max_concurrency``: calibration can only
    suggest going slower than configured, never faster.
    """
    ceiling = max(1, max_concurrency)
    ttfbs = [s.ttfb_seconds for s in samples if s.ttfb_seconds is not None and s.status and s.status < 400]
    median = statistics.median(ttfbs) if ttfbs else None
    p95 = _percentile(ttfbs, 0.95) if ttfbs else None

    rate_headers: dict[str, str] = {}
    stack: list[str] = []
    for sample in samples:
        lowered = _lower_headers(sample.headers)
        for name in RATE_LIMIT_HEADER_NAMES:
            if name in lowered:
                rate_headers[name] = lowered[name]
        for label in detect_origin_stack(sample.headers):
            if label not in stack:
                stack.append(label)

    concurrency = ceiling
    delay = 0.0
    reasons: list[str] = []
    if median is not None:
        if median > 2.0:
            concurrency, reason = 1, "baseline_ttfb_over_2s"
        elif median > 1.0:
            concurrency, reason = min(concurrency, 2), "baseline_ttfb_over_1s"
        elif median > 0.5:
            concurrency, reason = min(concurrency, 4), "baseline_ttfb_over_500ms"
        else:
            reason = ""
        if reason and concurrency < ceiling:
            reasons.append(reason)
    if p95 is not None and median is not None and median > 0 and p95 > 4 * median and concurrency > 2:
        concurrency = 2
        reasons.append("ttfb_p95_unstable")

    pressure = [s for s in samples if s.status in PRESSURE_STATUSES]
    if pressure:
        concurrency = 1
        reasons.append("calibration_saw_" + "_".join(sorted({str(s.status) for s in pressure})))
        waits = [parse_retry_after(_lower_headers(s.headers).get("retry-after"), now_epoch=now_epoch) for s in pressure]
        clamped = [min(w, max_retry_after_seconds) for w in waits if w is not None]
        delay = max(delay, max(clamped) if clamped else _BACKOFF_BASE_SECONDS)

    remaining = _parse_non_negative_number(
        rate_headers.get("ratelimit-remaining", rate_headers.get("x-ratelimit-remaining"))
    )
    reset = _parse_non_negative_number(rate_headers.get("ratelimit-reset", rate_headers.get("x-ratelimit-reset")))
    if reset is not None and reset > 1_000_000_000:
        # X-RateLimit-Reset is often an epoch timestamp rather than a delta.
        reference = time.time() if now_epoch is None else now_epoch
        reset = max(0.0, reset - reference)
    if remaining is not None and remaining <= 10:
        concurrency = 1
        reasons.append("rate_limit_remaining_low")
    if remaining is not None and reset is not None and reset > 0:
        spacing = reset / max(remaining, 1.0)
        if spacing > delay:
            delay = spacing
            reasons.append("rate_limit_window_spacing")

    delay = min(delay, max_retry_after_seconds)
    return CalibrationResult(
        host=host,
        requests=len(samples),
        statuses=[s.status for s in samples],
        ttfb_median_seconds=median,
        ttfb_p95_seconds=p95,
        rate_limit_headers=rate_headers,
        origin_stack=stack,
        recommended_concurrency=max(1, min(ceiling, concurrency)),
        recommended_min_interval_seconds=round(delay, 3),
        reasons=reasons,
        errors=[s.error for s in samples if s.error],
    )


class AdaptiveRateController:
    """Per-origin adaptive gate: a variable-limit slot pool plus a pause clock.

    ``slot()`` is entered around each page fetch, inside the engine's fixed
    per-host semaphore, so it can only narrow the configured cap.
    """

    def __init__(
        self,
        host: str,
        *,
        max_concurrency: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        degradation_factor: float = 2.5,
        recovery_window: int = 50,
        max_retry_after_seconds: float = 60.0,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.host = host
        self.configured_concurrency = max(1, max_concurrency)
        self._clock = clock
        self._sleep = sleep
        self._wall_clock = wall_clock
        self.degradation_factor = degradation_factor
        self.recovery_window = max(1, recovery_window)
        self.max_retry_after_seconds = max_retry_after_seconds

        self.ceiling = self.configured_concurrency
        self.concurrency_limit = self.configured_concurrency
        self.min_interval_seconds = 0.0
        self.min_concurrency_reached = self.configured_concurrency
        self.baseline_ttfb: float | None = None
        self.baseline_source: str | None = None
        self.calibration: CalibrationResult | None = None

        self._in_flight = 0
        self._condition: asyncio.Condition | None = None
        self._pause_until = 0.0
        self._last_start: float | None = None
        self._started_at = clock()
        self._rolling: deque[float] = deque(maxlen=_ROLLING_WINDOW)
        self._runtime_baseline_samples: list[float] = []
        self._healthy_streak = 0
        self._consecutive_backoffs = 0

        self.responses_observed = 0
        self.rate_limited_count = 0
        self.unavailable_count = 0
        self.retry_after_count = 0
        self.retry_after_max_seconds: float | None = None
        self.fetch_error_count = 0
        self.throttled_seconds = 0.0
        self.throttle_events = 0
        self.backoff_events = 0
        self.recovery_events = 0
        self.peak_rolling_ttfb: float | None = None
        self.ttfb_curve: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = []
        self.history_truncated = False

    # -- calibration -------------------------------------------------------

    def apply_calibration(self, result: CalibrationResult) -> None:
        """Adopt the calibration baseline and start no faster than it recommends."""
        self.calibration = result
        if result.ttfb_median_seconds is not None and result.ttfb_median_seconds > 0:
            self.baseline_ttfb = result.ttfb_median_seconds
            self.baseline_source = "calibration"
        self.ceiling = max(1, min(self.configured_concurrency, result.recommended_concurrency))
        self.concurrency_limit = min(self.concurrency_limit, self.ceiling)
        self.min_concurrency_reached = min(self.min_concurrency_reached, self.concurrency_limit)
        self.min_interval_seconds = max(self.min_interval_seconds, result.recommended_min_interval_seconds)
        self._event(
            "calibrated",
            reason=",".join(result.reasons) or "baseline",
        )

    # -- gate --------------------------------------------------------------

    def pause_remaining(self) -> float:
        return max(0.0, self._pause_until - self._clock())

    def _get_condition(self) -> asyncio.Condition:
        if self._condition is None:
            self._condition = asyncio.Condition()
        return self._condition

    async def _wait_for_timing(self) -> None:
        while True:
            now = self._clock()
            wait_for = max(0.0, self._pause_until - now)
            if self._last_start is not None and self.min_interval_seconds > 0:
                wait_for = max(wait_for, self._last_start + self.min_interval_seconds - now)
            if wait_for <= 0:
                return
            await self._sleep(wait_for)

    @contextlib.asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        condition = self._get_condition()
        async with condition:
            await condition.wait_for(lambda: self._in_flight < self.concurrency_limit)
            self._in_flight += 1
        try:
            # Pause/spacing are re-checked after taking the slot: a 429 seen by
            # a sibling while this task queued must still hold it back.
            await self._wait_for_timing()
            self._last_start = self._clock()
            yield
        finally:
            async with condition:
                self._in_flight -= 1
                condition.notify_all()

    # -- signals -----------------------------------------------------------

    def record_response(self, status: int, ttfb_seconds: float | None, headers: Mapping[str, str] | None) -> None:
        self.responses_observed += 1
        if status in PRESSURE_STATUSES:
            self._record_backoff(status, headers)
            return
        if status <= 0:
            return
        self._consecutive_backoffs = 0
        degraded = False
        if ttfb_seconds is not None and ttfb_seconds >= 0:
            degraded = self._record_ttfb(ttfb_seconds)
        if degraded:
            return
        self._healthy_streak += 1
        if self._healthy_streak >= self.recovery_window:
            self._healthy_streak = 0
            self._recover()

    def record_fetch_error(self, kind: str) -> None:
        """Count a transport failure; it resets the recovery streak but does not throttle."""
        self.fetch_error_count += 1
        self._healthy_streak = 0

    def _degradation_threshold(self) -> float | None:
        if self.baseline_ttfb is None:
            return None
        return max(self.baseline_ttfb * self.degradation_factor, self.baseline_ttfb + _MIN_DEGRADATION_SECONDS)

    def _record_ttfb(self, ttfb: float) -> bool:
        if self.baseline_ttfb is None:
            self._runtime_baseline_samples.append(ttfb)
            if len(self._runtime_baseline_samples) >= _RUNTIME_BASELINE_SAMPLES:
                baseline = statistics.median(self._runtime_baseline_samples)
                if baseline > 0:
                    self.baseline_ttfb = baseline
                    self.baseline_source = "runtime"
        self._rolling.append(ttfb)
        rolling = statistics.median(self._rolling)
        if self.peak_rolling_ttfb is None or rolling > self.peak_rolling_ttfb:
            self.peak_rolling_ttfb = rolling
        if self.responses_observed % _CURVE_EVERY == 0:
            self._append_curve(rolling)
        threshold = self._degradation_threshold()
        if threshold is None or len(self._rolling) < _MIN_ROLLING_SAMPLES:
            return False
        if rolling > threshold:
            self._append_curve(rolling)
            self._throttle(
                "ttfb_degraded",
                detail={
                    "rolling_median_ttfb_seconds": round(rolling, 4),
                    "baseline_ttfb_seconds": round(self.baseline_ttfb or 0.0, 4),
                },
            )
            # Require a fresh window before judging the new, slower rate.
            self._rolling.clear()
            return True
        return False

    def _append_curve(self, rolling: float) -> None:
        point = {
            "response": self.responses_observed,
            "at_seconds": round(self._clock() - self._started_at, 3),
            "rolling_median_ttfb_seconds": round(rolling, 4),
            "concurrency": self.concurrency_limit,
        }
        if self.ttfb_curve and self.ttfb_curve[-1]["response"] == point["response"]:
            return
        if len(self.ttfb_curve) >= _CURVE_LIMIT:
            # Keep the shape: drop every other point, then keep appending.
            self.ttfb_curve = self.ttfb_curve[::2]
        self.ttfb_curve.append(point)

    def _record_backoff(self, status: int, headers: Mapping[str, str] | None) -> None:
        if status == 429:
            self.rate_limited_count += 1
        else:
            self.unavailable_count += 1
        self._healthy_streak = 0
        self._consecutive_backoffs += 1
        retry_after = parse_retry_after(_lower_headers(headers).get("retry-after"), now_epoch=self._wall_clock())
        if retry_after is not None:
            self.retry_after_count += 1
            if self.retry_after_max_seconds is None or retry_after > self.retry_after_max_seconds:
                self.retry_after_max_seconds = retry_after
            pause = min(retry_after, self.max_retry_after_seconds)
            source = "retry_after"
        else:
            pause = min(
                _BACKOFF_BASE_SECONDS * (2 ** (self._consecutive_backoffs - 1)),
                self.max_retry_after_seconds,
            )
            source = "exponential"
        now = self._clock()
        end = now + pause
        start = max(now, self._pause_until)
        if end > start:
            self.throttled_seconds += end - start
            self._pause_until = end
        self.backoff_events += 1
        self._throttle(f"http_{status}", detail={"pause_seconds": round(pause, 3), "pause_source": source})

    def _throttle(self, reason: str, *, detail: dict[str, Any]) -> None:
        if self.concurrency_limit > 1:
            self.concurrency_limit = max(1, self.concurrency_limit // 2)
        else:
            base = self.baseline_ttfb or _THROTTLE_DELAY_FLOOR_SECONDS
            self.min_interval_seconds = min(
                max(self.min_interval_seconds * 2, base, _THROTTLE_DELAY_FLOOR_SECONDS),
                self.max_retry_after_seconds,
            )
        self.min_concurrency_reached = min(self.min_concurrency_reached, self.concurrency_limit)
        self.throttle_events += 1
        self._event("throttle", reason=reason, **detail)

    def _recover(self) -> None:
        calibrated_delay = self.calibration.recommended_min_interval_seconds if self.calibration else 0.0
        if self.min_interval_seconds > calibrated_delay:
            halved = self.min_interval_seconds / 2
            self.min_interval_seconds = (
                calibrated_delay if halved - calibrated_delay < _DELAY_EPSILON_SECONDS else halved
            )
        elif self.concurrency_limit < self.ceiling:
            self.concurrency_limit += 1
        else:
            return
        self.recovery_events += 1
        # Queued fetches see the wider limit on the next slot release; any
        # waiter implies at least one fetch in flight, so one always follows.
        self._event("recover", reason="sustained_healthy_window")

    def _event(self, event: str, *, reason: str, **detail: Any) -> None:
        if len(self.history) >= _HISTORY_LIMIT:
            self.history_truncated = True
            return
        self.history.append(
            {
                "at_seconds": round(self._clock() - self._started_at, 3),
                "event": event,
                "reason": reason,
                "concurrency": self.concurrency_limit,
                "min_interval_seconds": round(self.min_interval_seconds, 3),
                **detail,
            }
        )

    # -- reporting ---------------------------------------------------------

    @property
    def pressure_detected(self) -> bool:
        return bool(self.rate_limited_count or self.unavailable_count or self.throttle_events)

    def recommended_concurrency(self) -> int:
        recommended = self.ceiling
        for entry in self.history:
            if entry["event"] == "throttle":
                recommended = min(recommended, int(entry["concurrency"]))
        return max(1, recommended)

    def recommended_min_interval_seconds(self) -> float:
        floor = self.calibration.recommended_min_interval_seconds if self.calibration else 0.0
        if self.rate_limited_count or self.unavailable_count:
            floor = max(floor, self.min_interval_seconds, _THROTTLE_DELAY_FLOOR_SECONDS)
        return round(floor, 3)

    def snapshot(self) -> dict[str, Any]:
        ratio = (
            round(self.peak_rolling_ttfb / self.baseline_ttfb, 3)
            if self.peak_rolling_ttfb is not None and self.baseline_ttfb
            else None
        )
        return {
            "host": self.host,
            "calibration": None if self.calibration is None else self.calibration.to_dict(),
            "baseline_ttfb_seconds": None if self.baseline_ttfb is None else round(self.baseline_ttfb, 4),
            "baseline_source": self.baseline_source,
            "peak_rolling_ttfb_seconds": (None if self.peak_rolling_ttfb is None else round(self.peak_rolling_ttfb, 4)),
            "ttfb_degradation_ratio": ratio,
            "responses_observed": self.responses_observed,
            "rate_limited_429_count": self.rate_limited_count,
            "unavailable_503_count": self.unavailable_count,
            "retry_after_count": self.retry_after_count,
            "retry_after_max_seconds": self.retry_after_max_seconds,
            "fetch_error_count": self.fetch_error_count,
            "throttled_seconds": round(self.throttled_seconds, 3),
            "throttle_events": self.throttle_events,
            "backoff_events": self.backoff_events,
            "recovery_events": self.recovery_events,
            "configured_concurrency": self.configured_concurrency,
            "final_concurrency": self.concurrency_limit,
            "min_concurrency_reached": self.min_concurrency_reached,
            "final_min_interval_seconds": round(self.min_interval_seconds, 3),
            "recommended_concurrency": self.recommended_concurrency(),
            "recommended_min_interval_seconds": self.recommended_min_interval_seconds(),
            "pressure_detected": self.pressure_detected,
            "ttfb_curve": list(self.ttfb_curve),
            "history": list(self.history),
            "history_truncated": self.history_truncated,
        }


class AdaptiveRateRegistry:
    """One :class:`AdaptiveRateController` per host, mirroring the circuit-breaker registry."""

    def __init__(
        self,
        *,
        max_concurrency: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        degradation_factor: float = 2.5,
        recovery_window: int = 50,
        max_retry_after_seconds: float = 60.0,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.max_concurrency = max(1, max_concurrency)
        self._clock = clock
        self._sleep = sleep
        self._wall_clock = wall_clock
        self.degradation_factor = degradation_factor
        self.recovery_window = recovery_window
        self.max_retry_after_seconds = max_retry_after_seconds
        self._controllers: dict[str, AdaptiveRateController] = {}
        self.calibrated_hosts: set[str] = set()

    def for_host(self, host: str) -> AdaptiveRateController:
        controller = self._controllers.get(host)
        if controller is None:
            controller = AdaptiveRateController(
                host,
                max_concurrency=self.max_concurrency,
                clock=self._clock,
                sleep=self._sleep,
                degradation_factor=self.degradation_factor,
                recovery_window=self.recovery_window,
                max_retry_after_seconds=self.max_retry_after_seconds,
                wall_clock=self._wall_clock,
            )
            self._controllers[host] = controller
        return controller

    def summary(self) -> dict[str, Any]:
        hosts = {host: controller.snapshot() for host, controller in sorted(self._controllers.items())}
        return {
            "enabled": True,
            "pressure_detected": any(c.pressure_detected for c in self._controllers.values()),
            "rate_limited_429_count": sum(c.rate_limited_count for c in self._controllers.values()),
            "unavailable_503_count": sum(c.unavailable_count for c in self._controllers.values()),
            "throttled_seconds": round(sum(c.throttled_seconds for c in self._controllers.values()), 3),
            "throttle_events": sum(c.throttle_events for c in self._controllers.values()),
            "hosts": hosts,
        }


def format_pressure_summary(pressure: Mapping[str, Any] | None) -> str | None:
    """One-line CLI rendering of a job's crawl-budget pressure block."""
    if not pressure:
        return None
    parts = [
        f"{pressure.get('rate_limited_429_count', 0)}x429",
        f"{pressure.get('unavailable_503_count', 0)}x503",
        f"throttled {float(pressure.get('throttled_seconds', 0.0)):.1f}s",
        f"{pressure.get('throttle_events', 0)} throttle events",
    ]
    for host, snap in (pressure.get("hosts") or {}).items():
        baseline = snap.get("baseline_ttfb_seconds")
        peak = snap.get("peak_rolling_ttfb_seconds")
        ttfb = f"TTFB {baseline:.3f}s->{peak:.3f}s" if baseline is not None and peak is not None else "TTFB n/a"
        parts.append(
            f"{host}: {ttfb}, recommended concurrency {snap.get('recommended_concurrency')}"
            f" / interval {snap.get('recommended_min_interval_seconds')}s"
        )
    status = "PRESSURE DETECTED" if pressure.get("pressure_detected") else "no pressure"
    return f"Crawl-budget pressure ({status}): " + "; ".join(parts)
