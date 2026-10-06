"""Bounded, run-scoped TTFB distribution facts for technical-audit Q88.

The persistence/report layer supplies plain saved-page records; this module
does no I/O and makes no assumptions about a site's URL structure.  A record
can supply a resolved template name (``template``, ``template_id`` or
``template_pattern``) and a TTFB either in seconds (``ttfb_seconds``) or
milliseconds (``ttfb_ms``).  A caller that has not classified a page into a
template must not treat that page as a healthy performance result.

Percentiles use deterministic linear interpolation between ordered samples:
``rank = (n - 1) * percentile``.  This is explicit so runs produce the same
facts without a dependency on a database-specific percentile implementation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import floor, isfinite
from typing import Literal


DEFAULT_P90_MS = 600.0
DEFAULT_P99_MS = 1_500.0
DEFAULT_MIN_SAMPLES = 20
DEFAULT_MAX_EXAMPLE_URLS = 10

FactOutcome = Literal["finding", "observed", "unavailable"]


@dataclass(frozen=True)
class PerformanceDistributionFact:
    """One template population's Q88 evidence.

    ``outcome == 'unavailable'`` means this population has fewer than the
    required samples.  It is evidence of incomplete coverage, never a pass.
    URLs are the slowest retained observations, ordered slowest first, and are
    capped by ``max_example_urls`` to keep artifacts bounded.
    """

    template: str
    outcome: FactOutcome
    sample_count: int
    p90_ms: float | None
    p99_ms: float | None
    p90_threshold_ms: float
    p99_threshold_ms: float
    p90_breach: bool | None
    p99_breach: bool | None
    slowest_urls: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-ready evidence row."""

        return {
            "template": self.template,
            "outcome": self.outcome,
            "sample_count": self.sample_count,
            "p90_ms": self.p90_ms,
            "p99_ms": self.p99_ms,
            "p90_threshold_ms": self.p90_threshold_ms,
            "p99_threshold_ms": self.p99_threshold_ms,
            "p90_breach": self.p90_breach,
            "p99_breach": self.p99_breach,
            "slowest_urls": list(self.slowest_urls),
        }


@dataclass(frozen=True)
class PerformanceDistributionAudit:
    """Complete, bounded Q88 evidence from one crawl run.

    ``available`` establishes that at least one usable TTFB observation was
    supplied.  ``complete`` additionally requires template identity and a
    qualifying sample population for every usable saved record.  Therefore a
    consumer cannot report a Healthy result from a partial crawl.
    """

    available: bool
    complete: bool
    eligible_record_count: int
    excluded_record_count: int
    facts: tuple[PerformanceDistributionFact, ...]
    unavailable_reasons: tuple[str, ...] = ()
    facts_truncated: bool = False

    @property
    def affected(self) -> tuple[PerformanceDistributionFact, ...]:
        """Template facts whose p90 or p99 breaches the Q88 threshold."""

        return tuple(fact for fact in self.facts if fact.outcome == "finding")


def analyse_performance_distribution(
    pages: Sequence[Mapping[str, object]],
    *,
    p90_threshold_ms: float = DEFAULT_P90_MS,
    p99_threshold_ms: float = DEFAULT_P99_MS,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    max_facts: int = 500,
    max_example_urls: int = DEFAULT_MAX_EXAMPLE_URLS,
) -> PerformanceDistributionAudit:
    """Calculate Q88's per-template TTFB percentiles from saved page records.

    Only successful (2xx) records, when a response status is supplied, are
    eligible.  Records with no status are accepted because older saved crawl
    artifacts may retain timing but not the final status.  Missing, malformed
    or non-finite TTFB and missing template identity make the audit incomplete
    rather than being silently omitted.  Populations with fewer than
    ``min_samples`` are retained as unavailable evidence.
    """

    _validate_options(p90_threshold_ms, p99_threshold_ms, min_samples, max_facts, max_example_urls)

    populations: dict[str, list[tuple[float, str]]] = defaultdict(list)
    reasons: set[str] = set()
    eligible_record_count = 0
    excluded_record_count = 0

    for page in pages:
        if not isinstance(page, Mapping):
            reasons.add("invalid_page_record")
            continue
        status = _status(page)
        if status is not None and not 200 <= status < 300:
            excluded_record_count += 1
            continue
        if _has_status_value(page) and status is None:
            reasons.add("invalid_response_status")
            continue
        ttfb_ms = _ttfb_ms(page)
        if ttfb_ms is None:
            reasons.add("missing_or_invalid_ttfb")
            continue
        template = _template(page)
        if template is None:
            reasons.add("missing_template_identity")
            continue
        eligible_record_count += 1
        populations[template].append((ttfb_ms, _url(page)))

    facts: list[PerformanceDistributionFact] = []
    facts_truncated = False
    for template in sorted(populations):
        if len(facts) >= max_facts:
            facts_truncated = True
            reasons.add("facts_truncated")
            break
        samples = populations[template]
        values = sorted(value for value, _url in samples)
        slowest = tuple(
            url
            for _value, url in sorted(samples, key=lambda sample: (-sample[0], sample[1]))[:max_example_urls]
            if url
        )
        if len(values) < min_samples:
            reasons.add("insufficient_template_samples")
            facts.append(
                PerformanceDistributionFact(
                    template=template,
                    outcome="unavailable",
                    sample_count=len(values),
                    p90_ms=None,
                    p99_ms=None,
                    p90_threshold_ms=p90_threshold_ms,
                    p99_threshold_ms=p99_threshold_ms,
                    p90_breach=None,
                    p99_breach=None,
                    slowest_urls=slowest,
                )
            )
            continue
        p90 = _percentile(values, 0.90)
        p99 = _percentile(values, 0.99)
        p90_breach = p90 > p90_threshold_ms
        p99_breach = p99 > p99_threshold_ms
        facts.append(
            PerformanceDistributionFact(
                template=template,
                outcome="finding" if p90_breach or p99_breach else "observed",
                sample_count=len(values),
                p90_ms=p90,
                p99_ms=p99,
                p90_threshold_ms=p90_threshold_ms,
                p99_threshold_ms=p99_threshold_ms,
                p90_breach=p90_breach,
                p99_breach=p99_breach,
                slowest_urls=slowest,
            )
        )

    available = eligible_record_count > 0
    if not available:
        reasons.add("no_eligible_ttfb_samples")
    complete = available and not reasons and not facts_truncated
    return PerformanceDistributionAudit(
        available=available,
        complete=complete,
        eligible_record_count=eligible_record_count,
        excluded_record_count=excluded_record_count,
        facts=tuple(facts),
        unavailable_reasons=tuple(sorted(reasons)),
        facts_truncated=facts_truncated,
    )


def _validate_options(
    p90_threshold_ms: float,
    p99_threshold_ms: float,
    min_samples: int,
    max_facts: int,
    max_example_urls: int,
) -> None:
    if not _positive_finite(p90_threshold_ms) or not _positive_finite(p99_threshold_ms):
        raise ValueError("thresholds must be positive finite numbers")
    if min_samples < 1:
        raise ValueError("min_samples must be at least 1")
    if max_facts < 1:
        raise ValueError("max_facts must be at least 1")
    if max_example_urls < 1:
        raise ValueError("max_example_urls must be at least 1")


def _positive_finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value > 0


def _has_status_value(page: Mapping[str, object]) -> bool:
    return any(key in page and page[key] is not None for key in ("status", "response_status", "final_status_code"))


def _status(page: Mapping[str, object]) -> int | None:
    for key in ("status", "response_status", "final_status_code"):
        value = page.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            return None
        try:
            status = int(value)
        except (TypeError, ValueError):
            return None
        return status if 100 <= status <= 599 else None
    return None


def _ttfb_ms(page: Mapping[str, object]) -> float | None:
    for key, multiplier in (("ttfb_ms", 1.0), ("response_time_ms", 1.0), ("ttfb_seconds", 1_000.0)):
        if key not in page or page[key] is None:
            continue
        value = page[key]
        if isinstance(value, bool):
            return None
        try:
            milliseconds = float(value) * multiplier
        except (TypeError, ValueError):
            return None
        return milliseconds if isfinite(milliseconds) and milliseconds >= 0 else None
    return None


def _template(page: Mapping[str, object]) -> str | None:
    for key in ("template", "template_id", "template_pattern"):
        value = page.get(key)
        if isinstance(value, str) and (template := value.strip()):
            return template
    return None


def _url(page: Mapping[str, object]) -> str:
    value = page.get("url")
    return value.strip() if isinstance(value, str) else ""


def _percentile(values: Sequence[float], percentile: float) -> float:
    """Return a rounded linear-interpolation percentile from sorted values."""

    rank = (len(values) - 1) * percentile
    lower = floor(rank)
    upper = min(lower + 1, len(values) - 1)
    return round(values[lower] + (values[upper] - values[lower]) * (rank - lower), 3)
