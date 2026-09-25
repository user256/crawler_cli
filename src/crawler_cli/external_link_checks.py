"""Bounded, explicitly authorized checks of rendered external links."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .authorisation import ScopePredicate
from .config import CrawlConfig
from .engine import CrawlEngine
from .live_rechecks import _aggregate, _observation
from .redaction import redact_url_without_digest, scrub_text

MAX_EXTERNAL_LINK_TARGETS = 25
MAX_EXTERNAL_LINK_INSTANCES = 10_000
MAX_EXTERNAL_LINK_EXAMPLES_PER_TARGET = 25


def _safe_url(value: str) -> str:
    parsed = urlsplit(value)
    query = "&".join(key for key, _ in parse_qsl(parsed.query, keep_blank_values=True))
    return redact_url_without_digest(parsed._replace(query=query, fragment="").geturl())


def _safe_attempt(result: Any) -> dict[str, object]:
    observation = _observation(result)
    observation["requested_url"] = _safe_url(str(result.requested_url))
    observation["final_url"] = _safe_url(str(result.final_url))
    headers = observation.get("headers")
    if isinstance(headers, dict) and headers.get("location"):
        headers["location"] = _safe_url(str(headers["location"]))
    chain = observation.get("redirect_chain")
    if isinstance(chain, list):
        observation["redirect_chain"] = [
            {**dict(hop), "url": _safe_url(str(hop.get("url") or ""))} for hop in chain if isinstance(hop, Mapping)
        ]
    return observation


def _source_examples(instances: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "source_url": _safe_url(str(item.get("source_url") or "")),
            "device": item.get("device"),
            "anchor_text": scrub_text(str(item.get("anchor_text") or "")),
            "dom_path": scrub_text(str(item.get("dom_path") or "")),
            "capture_phase": item.get("capture_phase"),
            "reveal_state": item.get("reveal_state"),
        }
        for item in instances[:MAX_EXTERNAL_LINK_EXAMPLES_PER_TARGET]
    ]


async def collect_external_link_rechecks(
    instances: Sequence[Mapping[str, object]],
    *,
    scope_predicate: ScopePredicate,
    max_targets: int = MAX_EXTERNAL_LINK_TARGETS,
    truncated_instance_count: int = 0,
) -> list[dict[str, object]]:
    """Test a deterministic sample of external links under explicit scope.

    First responses are collected for in-scope targets. A second request is
    made only for an HTTP, DNS, TLS, or transport failure so transient errors
    can be distinguished without doubling all third-party traffic.
    """
    if not 1 <= max_targets <= MAX_EXTERNAL_LINK_TARGETS:
        raise ValueError(f"external link limit must be between 1 and {MAX_EXTERNAL_LINK_TARGETS}")
    effective_truncated_count = truncated_instance_count + max(0, len(instances) - MAX_EXTERNAL_LINK_INSTANCES)
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    invalid_count = 0
    for item in instances[:MAX_EXTERNAL_LINK_INSTANCES]:
        target = str(item.get("target_url") or "")
        parsed = urlsplit(target)
        source_host = (urlsplit(str(item.get("source_url") or "")).hostname or "").casefold()
        target_host = (parsed.hostname or "").casefold()
        if (
            parsed.scheme not in {"http", "https"}
            or not target_host
            or parsed.username is not None
            or parsed.password is not None
            or target_host == source_host
        ):
            invalid_count += 1
            continue
        grouped[parsed._replace(fragment="").geturl()].append(item)

    ordered_targets = sorted(grouped)
    selected_targets = ordered_targets[:max_targets]
    authorized: list[str] = []
    rows: list[dict[str, object]] = []
    for target in selected_targets:
        source_instances = grouped[target]
        decision = scope_predicate.decide(target, purpose="probe", method="GET")
        if not decision.allowed:
            rows.append(
                {
                    "record_type": "observation",
                    "record_kind": "external_link_recheck",
                    "target_url": _safe_url(target),
                    "state": "out_of_scope",
                    "scope_reason": decision.reason,
                    "source_instance_count": len(source_instances),
                    "source_page_count": len({str(item.get("source_url") or "") for item in source_instances}),
                    "source_examples": _source_examples(source_instances),
                    "source_examples_truncated": len(source_instances) > MAX_EXTERNAL_LINK_EXAMPLES_PER_TARGET,
                    "attempts": [],
                }
            )
        else:
            authorized.append(target)

    hosts = sorted({(urlsplit(origin).hostname or "").lower() for origin in scope_predicate.manifest.allowed_origins})
    if authorized:
        engine = CrawlEngine(
            CrawlConfig(
                backend="aiohttp",
                user_agent="crawler_cli-technical-audit-external-check/1",
                timeout_seconds=10.0,
                max_response_bytes=65_536,
                max_concurrency=1,
                per_host_concurrency=1,
                rate_limit_per_second=1.0,
                respect_robots_txt=True,
                challenge_escalate_to_browser=False,
                same_host_only=False,
                allowed_hosts=hosts,
                destination_guard="pinned",
                scope_predicate=scope_predicate,
            )
        )
        try:
            for target in authorized:
                samples = [_safe_attempt(await engine.crawl(target, purpose="probe"))]
                if samples[0]["state"] in {"http_failure", "dns_error", "tls_error", "transport_error"}:
                    samples.append(_safe_attempt(await engine.crawl(target, purpose="probe")))
                state = _aggregate(samples) if len(samples) > 1 else str(samples[0]["state"])
                source_instances = grouped[target]
                rows.append(
                    {
                        "record_type": "observation",
                        "record_kind": "external_link_recheck",
                        "target_url": _safe_url(target),
                        "state": state,
                        "source_instance_count": len(source_instances),
                        "source_page_count": len({str(item.get("source_url") or "") for item in source_instances}),
                        "source_examples": _source_examples(source_instances),
                        "source_examples_truncated": len(source_instances) > MAX_EXTERNAL_LINK_EXAMPLES_PER_TARGET,
                        "attempts": samples,
                        "qualification": "third_party_observation; interpret confirmed failures before client action",
                    }
                )
        finally:
            await engine.close()

    denied_count = sum(1 for row in rows if row.get("state") == "out_of_scope")
    attempts_count = sum(len(attempts) for row in rows if isinstance((attempts := row.get("attempts")), list))
    omitted_targets = max(0, len(ordered_targets) - len(selected_targets))
    coverage_state = (
        "partial" if omitted_targets or effective_truncated_count or invalid_count or denied_count else "complete"
    )
    rows.sort(key=lambda row: str(row.get("target_url") or ""))
    return [
        {
            "record_type": "coverage",
            "record_kind": "external_link_recheck_coverage",
            "state": coverage_state,
            "candidate_instance_count": len(instances) + truncated_instance_count,
            "candidate_target_count": len(ordered_targets),
            "selected_target_count": len(selected_targets),
            "attempted_target_count": len(authorized),
            "out_of_scope_target_count": denied_count,
            "invalid_or_internal_instance_count": invalid_count,
            "truncated_instance_count": effective_truncated_count,
            "omitted_target_count": omitted_targets,
            "attempt_count": attempts_count,
            "target_limit": max_targets,
            "instance_limit": MAX_EXTERNAL_LINK_INSTANCES,
            "source_examples_per_target_limit": MAX_EXTERNAL_LINK_EXAMPLES_PER_TARGET,
            "max_concurrency": 1,
            "respect_robots_txt": True,
            "scope_manifest_required": True,
            "classification_policy": "evidence_only_no_automatic_client_action",
        },
        *rows,
    ]
