"""Run-scoped timing summaries and bounded HTTP validator probes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
import math
from urllib.parse import urlsplit

from .authorisation import ScopePredicate
from .backends import AiohttpBackend
from .config import CrawlConfig
from .engine import CrawlEngine
from .redaction import redact_headers, redact_url_without_digest

CONDITIONAL_PROBE_RULESET_VERSION = "crawler-cli/conditional-get/1"
MAX_CONDITIONAL_PROBE_PAGES = 25
MAX_CONDITIONAL_PROBE_TIMEOUT_SECONDS = 15.0


def performance_inventory_report(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Summarise valid canonical HTML timings with nearest-rank quantiles."""
    eligible: list[dict[str, object]] = []
    excluded: Counter[str] = Counter()
    for source in rows:
        row = dict(source)
        if row.get("kind") != "html":
            excluded["non_html"] += 1
            continue
        if row.get("final_status_code") != 200:
            excluded["status_not_200"] += 1
            continue
        if row.get("challenge"):
            excluded["challenge"] += 1
            continue
        if row.get("content_extracted") is not True:
            excluded["content_not_extracted"] += 1
            continue
        if row.get("overall_indexable") is not True:
            excluded["not_indexable_or_unknown"] += 1
            continue
        if not _is_self_canonical(row):
            excluded["canonical_unknown_or_nonself"] += 1
            continue
        eligible.append(row)

    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in eligible:
        locale = str(row.get("html_lang") or "missing_locale")
        template = str(row.get("template") or "not_stored")
        groups.setdefault((locale, template), []).append(row)

    summaries = []
    for (locale, template), members in sorted(groups.items()):
        headers = [_header_map(row.get("headers_json")) for row in members]
        summaries.append(
            {
                "locale": locale,
                "template": template,
                "eligible_page_count": len(members),
                "ttfb_seconds": _distribution([row.get("ttfb_seconds") for row in members]),
                "total_duration_seconds": _distribution([row.get("total_duration_seconds") for row in members]),
                "cache_evidence": {
                    key: sum(bool(header.get(key)) for header in headers)
                    for key in ("cache-control", "age", "etag", "last-modified", "via", "x-cache", "cf-cache-status")
                },
                "lab_cwv_sample_count": sum(
                    any(row.get(field) is not None for field in ("lcp_ms", "cls", "inp_ms")) for row in members
                ),
                "cwv_source": "crawler_lab_only; not_field_or_real_user_data",
            }
        )
    return [
        {
            "record_type": "coverage",
            "source": "stored_crawl_http_lab",
            "source_row_count": len(rows),
            "eligible_canonical_indexable_html_count": len(eligible),
            "excluded_by_reason": dict(sorted(excluded.items())),
            "quantile_method": "nearest_rank: sorted[ceil(p*n)-1]",
            "groups": len(summaries),
            "field_cwv": "unavailable_not_supplied",
            "browser_trace_evidence": "unavailable_not_supplied_as_independent_trace",
        },
        *summaries,
    ]


def select_conditional_probe_candidates(
    rows: Sequence[Mapping[str, object]],
    *,
    max_pages: int,
) -> list[dict[str, object]]:
    """Select deterministic public canonical-HTML controls, balanced by context."""
    if not 1 <= max_pages <= MAX_CONDITIONAL_PROBE_PAGES:
        raise ValueError(f"conditional probe page limit must be 1–{MAX_CONDITIONAL_PROBE_PAGES}")
    strata = _conditional_candidate_strata(rows)
    selected: list[dict[str, object]] = []
    depth = 0
    while len(selected) < max_pages:
        added = False
        for stratum in sorted(strata):
            members = strata[stratum]
            if depth < len(members):
                selected.append(members[depth])
                added = True
                if len(selected) >= max_pages:
                    break
        if not added:
            break
        depth += 1
    return selected


def conditional_probe_candidate_population(rows: Sequence[Mapping[str, object]]) -> int:
    """Count eligible controls before applying the sample cap."""
    return sum(len(members) for members in _conditional_candidate_strata(rows).values())


def _conditional_candidate_strata(
    rows: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str], list[dict[str, object]]]:
    strata: dict[tuple[str, str], list[dict[str, object]]] = {}
    for source in rows:
        row = dict(source)
        url = str(row.get("url") or "")
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            continue
        if parsed.username or parsed.password or parsed.query:
            continue
        if row.get("kind") != "html" or row.get("final_status_code") != 200:
            continue
        if row.get("content_extracted") is not True or row.get("overall_indexable") is not True:
            continue
        if row.get("challenge") or not _is_self_canonical(row):
            continue
        locale = str(row.get("html_lang") or "missing_locale")
        template = str(row.get("template") or "not_stored")
        row["stratum"] = f"{locale}|{template}"
        strata.setdefault((locale, template), []).append(row)
    for members in strata.values():
        members.sort(key=lambda row: (hashlib.sha256(str(row["url"]).encode()).hexdigest(), str(row["url"])))
    return strata


async def collect_conditional_get_evidence(
    candidates: Sequence[Mapping[str, object]],
    *,
    allowed_hosts: Sequence[str],
    scope_predicate: ScopePredicate | None,
    timeout_seconds: float = 10.0,
) -> list[dict[str, object]]:
    """Perform a paired ordinary GET then a real-validator conditional GET.

    Robots and authorization scope are enforced by CrawlEngine for each
    request. Redirect following is disabled to avoid probing an unapproved hop.
    """
    if not 0 < timeout_seconds <= MAX_CONDITIONAL_PROBE_TIMEOUT_SECONDS:
        raise ValueError(f"conditional probe timeout must be in (0, {MAX_CONDITIONAL_PROBE_TIMEOUT_SECONDS}] seconds")
    rows: list[dict[str, object]] = []
    for candidate in candidates:
        url = str(candidate.get("url") or "")
        digest = hashlib.sha256(url.encode()).hexdigest()
        common = {
            "url": redact_url_without_digest(url),
            "url_digest_sha256": digest,
            "stratum": candidate.get("stratum"),
            "locale": candidate.get("html_lang"),
            "template": candidate.get("template"),
            "ruleset_version": CONDITIONAL_PROBE_RULESET_VERSION,
        }
        ordinary_config = _probe_config(
            allowed_hosts=allowed_hosts,
            scope_predicate=scope_predicate,
            timeout_seconds=timeout_seconds,
        )
        ordinary_engine = CrawlEngine(ordinary_config)
        try:
            ordinary = await ordinary_engine.crawl(url, purpose="probe")
        finally:
            await ordinary_engine.close()

        validators = _validators(ordinary.headers)
        ordinary_body = ordinary.raw_html
        ordinary_digest = _representation_digest(ordinary_body)
        record: dict[str, object] = {
            "record_type": "observation",
            "observed_at": datetime.now(UTC).isoformat(),
            **common,
            "ordinary_status": ordinary.status,
            "ordinary_headers": redact_headers(ordinary.headers),
            "ordinary_ttfb_seconds": ordinary.ttfb_seconds,
            "ordinary_duration_seconds": ordinary.total_duration_seconds,
            "ordinary_wire_bytes": ordinary.wire_bytes,
            "ordinary_decoded_bytes": ordinary.decoded_bytes,
            "ordinary_representation_sha256": ordinary_digest,
            "ordinary_state": ordinary.skip_reason or "response_received",
            "validator_kind": "+".join(sorted(validators)) if validators else None,
            "validator_digest_sha256": _validator_digest(validators),
            "conditional_status": None,
            "conditional_headers": {},
            "conditional_ttfb_seconds": None,
            "conditional_duration_seconds": None,
            "conditional_wire_bytes": None,
            "conditional_decoded_bytes": None,
            "conditional_representation_sha256": None,
            "representation_equal": None,
            "outcome": "not_testable",
            "qualification": "ordinary_request_must_return_200_with_a_real_validator",
        }
        if ordinary.status != 200 or ordinary.challenge or ordinary.raw_html is None:
            record["outcome"] = "not_testable_ordinary_response_unavailable"
            rows.append(record)
            continue
        if not validators:
            record["outcome"] = "not_testable_no_server_validator"
            rows.append(record)
            continue

        conditional_config = _probe_config(
            allowed_hosts=allowed_hosts,
            scope_predicate=scope_predicate,
            timeout_seconds=timeout_seconds,
        )
        conditional_engine = _ConditionalCrawlEngine(conditional_config, url, validators)
        try:
            conditional = await conditional_engine.crawl(url, purpose="probe")
        finally:
            await conditional_engine.close()
        conditional_digest = _representation_digest(conditional.raw_html)
        record.update(
            {
                "conditional_status": conditional.status,
                "conditional_headers": redact_headers(conditional.headers),
                "conditional_ttfb_seconds": conditional.ttfb_seconds,
                "conditional_duration_seconds": conditional.total_duration_seconds,
                "conditional_wire_bytes": conditional.wire_bytes,
                "conditional_decoded_bytes": conditional.decoded_bytes,
                "conditional_representation_sha256": conditional_digest,
                "representation_equal": (
                    ordinary_digest == conditional_digest
                    if ordinary_digest is not None and conditional_digest is not None
                    else None
                ),
            }
        )
        if conditional.status == 304:
            record.update(
                outcome="not_modified_304",
                representation_equal="validator_matched_body_not_transferred",
                qualification="conditional_get_efficiency_observed",
            )
        elif conditional.status == 200:
            if ordinary_digest is not None and conditional_digest == ordinary_digest:
                record.update(
                    record_type="candidate",
                    outcome="validator_not_honored_unchanged_200",
                    qualification="unchanged_representation_retransferred; check intermediary and cache policy",
                )
            else:
                record.update(
                    outcome="changed_or_uncomparable_200_no_validator_defect",
                    qualification="a_changed_200_is_not_a_validator_defect",
                )
        else:
            record.update(outcome="conditional_response_other_status", qualification="manual_review_required")
        rows.append(record)
    return rows


def conditional_get_report(
    observations: Sequence[Mapping[str, object]],
    *,
    candidate_population: int,
    sample_size: int,
) -> list[dict[str, object]]:
    """Add explicit validator coverage and 304-rate denominators."""
    attempted = [row for row in observations if isinstance(row.get("conditional_status"), int)]
    count_304 = sum(row.get("conditional_status") == 304 for row in attempted)
    not_testable_no_validator = sum(row.get("outcome") == "not_testable_no_server_validator" for row in observations)
    not_testable_ordinary = sum(
        row.get("outcome") == "not_testable_ordinary_response_unavailable" for row in observations
    )
    candidates = [dict(row) for row in observations if row.get("record_type") == "candidate"]
    coverage: dict[str, object] = {
        "record_type": "coverage",
        "state": "tested" if attempted else "not_testable",
        "ruleset_version": CONDITIONAL_PROBE_RULESET_VERSION,
        "candidate_population": candidate_population,
        "sample_size": sample_size,
        "conditional_requests_attempted": len(attempted),
        "validator_eligible_count": len(attempted),
        "no_validator_count": not_testable_no_validator,
        "ordinary_response_unavailable_count": not_testable_ordinary,
        "not_testable_count": not_testable_no_validator + not_testable_ordinary,
        "not_modified_304_count": count_304,
        "not_modified_304_rate": count_304 / len(attempted) if attempted else None,
        "conditional_validator_policy": "real ETag and/or Last-Modified from paired ordinary GET; never synthesized",
        "redirects_followed": False,
        "scope_and_robots": "CrawlEngine authorization, pinned public destination and robots enforcement",
        "representation_equality": "decoded HTML UTF-8 SHA-256; 304 means body not transferred",
        "changed_200_policy": "not_a_validator_defect",
        "efficiency_warning_count": len(candidates),
    }
    return [coverage, *[dict(row) for row in observations]]


class _ConditionalAiohttpBackend(AiohttpBackend):
    def __init__(self, config: CrawlConfig, target_url: str, headers: Mapping[str, str]) -> None:
        super().__init__(config)
        self._target_url = target_url
        self._conditional_headers = dict(headers)

    async def fetch(self, url: str):
        if url != self._target_url:
            return await super().fetch(url)
        original = self.config.request_headers
        self.config.request_headers = {**original, **self._conditional_headers}
        try:
            return await super().fetch(url)
        finally:
            self.config.request_headers = original


class _ConditionalCrawlEngine(CrawlEngine):
    def __init__(self, config: CrawlConfig, target_url: str, headers: Mapping[str, str]) -> None:
        super().__init__(config)
        self.backend = _ConditionalAiohttpBackend(config, target_url, headers)


def _probe_config(
    *,
    allowed_hosts: Sequence[str],
    scope_predicate: ScopePredicate | None,
    timeout_seconds: float,
) -> CrawlConfig:
    return CrawlConfig(
        backend="aiohttp",
        same_host_only=True,
        allowed_hosts=sorted({host.lower() for host in allowed_hosts}),
        respect_robots_txt=True,
        honor_robots_crawl_delay=True,
        max_concurrency=1,
        per_host_concurrency=1,
        rate_limit_per_second=1.0,
        timeout_seconds=timeout_seconds,
        follow_redirects=False,
        challenge_escalate_to_browser=False,
        destination_guard="pinned",
        scope_predicate=scope_predicate,
    )


def _validators(headers: Mapping[str, str]) -> dict[str, str]:
    lower = {str(key).lower(): str(value).strip() for key, value in headers.items()}
    result: dict[str, str] = {}
    if lower.get("etag"):
        result["If-None-Match"] = lower["etag"]
    if lower.get("last-modified"):
        result["If-Modified-Since"] = lower["last-modified"]
    return result


def _validator_digest(headers: Mapping[str, str]) -> str | None:
    if not headers:
        return None
    payload = "\n".join(f"{key.lower()}:{value}" for key, value in sorted(headers.items()))
    return hashlib.sha256(payload.encode()).hexdigest()


def _representation_digest(body: str | None) -> str | None:
    return hashlib.sha256(body.encode("utf-8")).hexdigest() if body is not None else None


def _header_map(value: object) -> dict[str, str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return {str(key).lower(): str(item) for key, item in value.items()} if isinstance(value, Mapping) else {}


def _is_self_canonical(row: Mapping[str, object]) -> bool:
    url = str(row.get("url") or "")
    raw = row.get("canonical_urls_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return False
    if not isinstance(raw, list):
        return False
    return not raw or url in {str(value) for value in raw}


def _distribution(raw_values: Sequence[object]) -> dict[str, object]:
    values = sorted(
        float(value)
        for value in raw_values
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
    )
    if not values:
        return {
            "valid_sample_count": 0,
            "excluded_sample_count": len(raw_values),
            "mean": None,
            "p90": None,
            "p99": None,
            "worst": None,
        }

    def quantile(percentile: float) -> float:
        return values[max(0, math.ceil(percentile * len(values)) - 1)]

    return {
        "valid_sample_count": len(values),
        "excluded_sample_count": len(raw_values) - len(values),
        "mean": sum(values) / len(values),
        "p90": quantile(0.90),
        "p99": quantile(0.99),
        "worst": values[-1],
    }
