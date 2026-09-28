"""Bounded, scope-authorised live rechecks for saved crawl failures."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from urllib.parse import urlparse

from .authorisation import ScopePredicate
from .config import CrawlConfig
from .engine import CrawlEngine
from .redaction import redact_url_without_digest

MAX_RECHECK_TARGETS = 25
MAX_RECHECK_ATTEMPTS = 3
MAX_RECHECK_TIMEOUT_SECONDS = 15.0


def candidate_targets(rows: Iterable[dict[str, object]], *, limit: int) -> list[str]:
    """Select unique historical HTTP failures in stable URL order."""
    if not 1 <= limit <= MAX_RECHECK_TARGETS:
        raise ValueError(f"recheck limit must be between 1 and {MAX_RECHECK_TARGETS}")
    targets = set()
    for row in rows:
        target_url, status = row.get("target_url"), row.get("target_status")
        if isinstance(target_url, str) and isinstance(status, int) and status >= 400:
            targets.add(target_url)
    return sorted(targets)[:limit]


async def collect_live_rechecks(
    targets: Iterable[str],
    *,
    scope_predicate: ScopePredicate,
    allowed_hosts: Iterable[str],
    attempts: int = 2,
    timeout_seconds: float = 10.0,
) -> dict[str, dict[str, object]]:
    """Fetch exact historical targets through the crawler's guarded engine.

    Robots rules, redirect policy, destination validation and the manifest's
    probe/redirect scope apply. No link discovery or browser challenge
    escalation is enabled. Two or more repeated HTTP failures are required
    before a saved failure can be promoted to a current failure.
    """
    if not 2 <= attempts <= MAX_RECHECK_ATTEMPTS:
        raise ValueError(f"recheck attempts must be between 2 and {MAX_RECHECK_ATTEMPTS}")
    if not 0 < timeout_seconds <= MAX_RECHECK_TIMEOUT_SECONDS:
        raise ValueError(f"recheck timeout must be between 0 and {MAX_RECHECK_TIMEOUT_SECONDS} seconds")
    hosts = {host.lower() for host in allowed_hosts}
    selected = sorted(set(targets))
    if len(selected) > MAX_RECHECK_TARGETS:
        raise ValueError(f"cannot recheck more than {MAX_RECHECK_TARGETS} URLs per audit")
    observations: dict[str, dict[str, object]] = {}
    eligible: list[str] = []
    for url in selected:
        host = (urlparse(url).hostname or "").lower()
        if host not in hosts:
            observations[url] = {
                "state": "out_of_scope",
                "attempts": [],
                "detail": "target host is not in the selected run's declared scope",
            }
        elif not scope_predicate.decide(url, purpose="probe").allowed:
            observations[url] = {"state": "scope_denied", "attempts": []}
        else:
            eligible.append(url)

    if eligible:
        config = CrawlConfig(
            backend="aiohttp",
            user_agent="crawler_cli-audit-recheck/1",
            max_concurrency=1,
            rate_limit_per_second=1.0,
            timeout_seconds=timeout_seconds,
            max_response_bytes=2_000_000,
            respect_robots_txt=True,
            same_host_only=False,
            allowed_hosts=sorted(hosts),
            challenge_escalate_to_browser=False,
            scope_predicate=scope_predicate,
        )
        engine = CrawlEngine(config)
        try:
            for url in eligible:
                samples = []
                for _ in range(attempts):
                    result = await engine.crawl(url, purpose="probe")
                    samples.append(_observation(result))
                observations[url] = {"state": _aggregate(samples), "attempts": samples}
        finally:
            await engine.close()
    return observations


def _observation(result) -> dict[str, object]:
    if result.skip_reason == "robots_txt_disallow":
        state = "robots_disallowed"
    elif result.challenge:
        state = "challenge"
    elif result.skip_reason and result.skip_reason.startswith("scope_manifest_denied:"):
        state = "scope_denied"
    elif result.skip_reason and result.skip_reason.startswith("fetch_error:"):
        error_kind = result.skip_reason.lower()
        if any(marker in error_kind for marker in ("ssl", "tls", "certificate")):
            state = "tls_error"
        elif any(marker in error_kind for marker in ("dns", "gaierror", "getaddrinfo")):
            state = "dns_error"
        else:
            state = "transport_error"
    elif result.skip_reason and result.skip_reason.startswith("destination_denied:"):
        state = "destination_denied"
    elif result.status in {401, 403}:
        state = "access_denied"
    elif result.status == 429:
        state = "rate_limited"
    elif result.status >= 400:
        state = "http_failure"
    elif result.status > 0:
        state = "responsive"
    else:
        state = "incomplete"
    safe_headers = {
        key.lower(): redact_url_without_digest(value) if key.lower() == "location" else value
        for key, value in result.headers.items()
        if key.lower() in {"content-type", "location", "retry-after", "last-modified", "cache-control"}
    }
    chain = [{**hop, "url": redact_url_without_digest(str(hop.get("url", "")))} for hop in result.redirect_chain]
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "state": state,
        "requested_url": redact_url_without_digest(result.requested_url),
        "final_url": redact_url_without_digest(result.final_url),
        "status": result.status,
        "headers": safe_headers,
        "content_type": result.content_type,
        "fetch_backend": result.fetch_backend,
        "allowed_by_robots": result.allowed_by_robots,
        "skip_reason": result.skip_reason,
        "challenge": result.challenge,
        "redirect_chain": chain,
    }


def _aggregate(samples: list[dict[str, object]]) -> str:
    states = [str(sample["state"]) for sample in samples]
    if states and all(state == "responsive" for state in states):
        return "recovered"
    if states and all(state == "http_failure" for state in states):
        statuses = {sample.get("status") for sample in samples}
        return (
            "persistent_server_error"
            if statuses and all(isinstance(s, int) and s >= 500 for s in statuses)
            else "persistent_http_failure"
        )
    exceptional = {
        "incomplete",
        "robots_disallowed",
        "scope_denied",
        "out_of_scope",
        "challenge",
        "tls_error",
        "dns_error",
        "transport_error",
        "destination_denied",
        "access_denied",
        "rate_limited",
    }
    if states and all(state == states[0] for state in states) and states[0] in exceptional:
        return states[0]
    if any(state in exceptional for state in states):
        return "incomplete"
    return "intermittent_failure"
