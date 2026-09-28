"""Bounded Accept-Language variation and language-redirect evidence (ticket 260).

The probe asks one question per target URL: does the origin change its
redirect, status, or content when only the ``Accept-Language`` request header
changes?  Each target receives a small fixed set of header variants, redirects
are followed by hand so loops and host changes are visible, and every outcome
is an analyst observation.  A language redirect is not automatically a defect;
it is flagged because search crawlers usually send no ``Accept-Language`` and
may never see the alternate.

Region/geo-IP comparison through configured proxies is ticket 194's scope.
Outcomes stay in the technical-audit evidence stream; the run-scoped custom
probe store of ticket 257 is the future persistence hook.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urljoin, urlsplit

from .hashing import simhash64
from .redaction import redact_url_without_digest


# ``None`` means the header is omitted entirely, which is how search crawlers
# usually fetch.  The order is fixed so evidence is replayable.
ACCEPT_LANGUAGE_VARIANTS: tuple[tuple[str, str | None], ...] = (
    ("none", None),
    ("wildcard", "*"),
    ("en-US", "en-US,en;q=0.9"),
    ("es-ES", "es-ES,es;q=0.9"),
    ("de-DE", "de-DE,de;q=0.9"),
    ("fr-FR", "fr-FR,fr;q=0.9"),
    ("ja-JP", "ja-JP,ja;q=0.9"),
    ("pt-BR", "pt-BR,pt;q=0.9"),
)
# A second header-less request separates language-driven differences from
# pages that change on every request (timestamps, tokens, rotating promos).
_REPEAT_VARIANT = "none-repeat"
_NEUTRAL_VARIANTS = frozenset({"none", "wildcard"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_ACCEPT_LANGUAGE_TARGETS = 20
MAX_REDIRECT_HOPS = 10
# Same tolerance the soft-404 control comparison uses.
_SIMHASH_TOLERANCE = 3
_LOCALE_ROOT = re.compile(r"^/[a-z]{2,3}(?:[-_][a-z0-9]{2,4})?/?$", re.I)
_LANGUAGE_COOKIE = re.compile(r"lang|locale|country|region|geo|market", re.I)
_QUALIFICATION = "accept_language_probe_observation_requires_intent_and_crawler_access_review"


def select_accept_language_targets(
    seed_origins: Sequence[str],
    page_rows: Sequence[Mapping[str, object]],
    *,
    max_targets: int = 5,
) -> tuple[list[str], int]:
    """Pick the root of each seed origin, then saved locale-root pages.

    Returns ``(selected, eligible_population)``.  Locale roots are saved
    200 HTML pages whose whole path is one language-like segment such as
    ``/es/`` or ``/pt-br/``; they are the templates most often wired to
    language negotiation.
    """
    if not 1 <= max_targets <= MAX_ACCEPT_LANGUAGE_TARGETS:
        raise ValueError(f"Accept-Language target limit must be 1–{MAX_ACCEPT_LANGUAGE_TARGETS}")
    candidates: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        key = _url_key(url)
        if key not in seen:
            seen.add(key)
            candidates.append(url)

    origins = []
    for origin in seed_origins:
        parts = urlsplit(str(origin))
        if parts.scheme in {"http", "https"} and parts.netloc:
            origins.append(f"{parts.scheme}://{parts.netloc}/")
    for root in sorted(set(origins)):
        add(root)
    root_hosts = {urlsplit(root).netloc.lower() for root in origins}
    locale_roots = []
    for row in page_rows:
        url = str(row.get("url") or "")
        parts = urlsplit(url)
        if (
            parts.scheme not in {"http", "https"}
            or parts.query
            or row.get("kind") != "html"
            or row.get("final_status_code") != 200
            or (root_hosts and parts.netloc.lower() not in root_hosts)
        ):
            continue
        if parts.path in {"", "/"}:
            add(f"{parts.scheme}://{parts.netloc}/")
        elif _LOCALE_ROOT.match(parts.path):
            locale_roots.append(url)
    for url in sorted(locale_roots):
        add(url)
    return candidates[:max_targets], len(candidates)


async def collect_accept_language_evidence(
    engine: Any,
    targets: Sequence[str],
    *,
    eligible_population: int | None = None,
    max_redirect_hops: int = 5,
) -> list[dict[str, object]]:
    """Probe each target with every Accept-Language variant.

    Returns ``[coverage, *observations, *candidates]``.  The engine applies
    robots, scope, authorization and destination guards to every hop because
    redirects are followed here, one ``engine.crawl`` per hop.
    """
    if not 1 <= max_redirect_hops <= MAX_REDIRECT_HOPS:
        raise ValueError(f"redirect hop limit must be 1–{MAX_REDIRECT_HOPS}")
    observations: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    probe_count = 0
    request_count = 0
    variants = [*ACCEPT_LANGUAGE_VARIANTS, (_REPEAT_VARIANT, None)]
    for target in targets:
        probes: dict[str, dict[str, object]] = {}
        for label, header_value in variants:
            probe = await _probe(engine, target, label, header_value, max_redirect_hops)
            probe_count += 1
            request_count += len(_hops(probe))
            probes[label] = probe
        target_observations, target_candidates = _classify_target(target, probes)
        observations.extend(target_observations)
        candidates.extend(target_candidates)
    population = eligible_population if eligible_population is not None else len(targets)
    coverage: dict[str, object] = {
        "record_type": "coverage",
        "observed_at": _now(),
        "complete": len(targets) >= population,
        "target_count": len(targets),
        "eligible_target_count": population,
        "probe_count": probe_count,
        "request_count": request_count,
        "accept_language_variants": [
            {"variant": label, "accept_language": value} for label, value in ACCEPT_LANGUAGE_VARIANTS
        ],
        "repeat_control": "second header-less request per target separates volatile content from language variation",
        "max_redirect_hops": max_redirect_hops,
        "redirects_followed": "manually, one guarded request per hop",
        "candidate_counts": {
            kind: sum(row.get("candidate_type") == kind for row in candidates)
            for kind in ("language_redirect_detected", "missing_vary_header", "bot_trap")
        },
        "geo_ip_variation": "not_tested; regional proxy comparison is ticket 194",
        "persistence": "technical_audit_evidence_only; run-scoped custom probe store pending ticket 257",
        "sampling": "seed-origin roots first, then saved 200 HTML locale-root paths, sorted",
    }
    return [coverage, *observations, *candidates]


async def _probe(
    engine: Any,
    target: str,
    label: str,
    header_value: str | None,
    max_redirect_hops: int,
) -> dict[str, object]:
    config = engine.config
    original_headers = dict(config.request_headers)
    original_follow = config.follow_redirects
    request_headers = {name: value for name, value in original_headers.items() if name.lower() != "accept-language"}
    if header_value is not None:
        request_headers["Accept-Language"] = header_value
    config.request_headers = request_headers
    config.follow_redirects = False
    hops: list[dict[str, object]] = []
    visited: set[str] = set()
    outcome = "unresolved"
    final = None
    current = target
    try:
        for hop_index in range(max_redirect_hops + 1):
            key = _url_key(current)
            if key in visited:
                outcome = "redirect_loop"
                break
            visited.add(key)
            result = await engine.crawl(current, purpose="probe" if hop_index == 0 else "redirect")
            location = _header(result.headers, "location")
            resolved = urljoin(current, location) if location else None
            hops.append(_hop_record(current, result, resolved))
            final = result
            if result.status == 0:
                if not result.skip_reason:
                    outcome = "fetch_error"
                else:
                    outcome = "not_admitted" if hop_index == 0 else "redirect_target_not_admitted"
                break
            if result.status not in _REDIRECT_STATUSES:
                outcome = "resolved"
                break
            if not resolved:
                outcome = "redirect_without_location"
                break
            current = resolved
        else:
            outcome = "redirect_limit_exceeded"
    finally:
        config.request_headers = original_headers
        config.follow_redirects = original_follow
    raw_html = final.raw_html if final is not None and outcome == "resolved" else None
    return {
        "variant": label,
        "request_headers": {"Accept-Language": header_value} if header_value is not None else {},
        "hops": hops,
        "outcome": outcome,
        "final_url": hops[-1]["url"] if hops else target,
        "final_status": hops[-1]["status"] if hops else None,
        "html_lang": (
            final.extracted.html_lang
            if final is not None and outcome == "resolved" and final.extracted is not None
            else None
        ),
        "body_sha256": hashlib.sha256(raw_html.encode("utf-8")).hexdigest() if raw_html else None,
        "body_simhash": simhash64(raw_html) if raw_html else None,
    }


def _hop_record(url: str, result: Any, location: str | None) -> dict[str, object]:
    return {
        "url": url,
        "status": result.status,
        "location": location,
        "vary": _header(result.headers, "vary"),
        "content_language": _header(result.headers, "content-language"),
        "set_cookies": _set_cookie_summary(_header(result.headers, "set-cookie")),
        "skip_reason": result.skip_reason,
    }


def _classify_target(
    target: str, probes: Mapping[str, Mapping[str, object]]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    baseline = probes["none"]
    repeat = probes[_REPEAT_VARIANT]
    content_stable = _same_content(baseline, repeat, strict=True)
    observations: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    varying: list[tuple[Mapping[str, object], list[str]]] = []
    for label, probe in probes.items():
        differences = [] if label == "none" else _differences(baseline, probe, content_stable=content_stable)
        if label not in {"none", _REPEAT_VARIANT} and differences:
            varying.append((probe, differences))
        observations.append(
            {
                "record_type": "observation",
                "observation_type": "accept_language_probe",
                "target_url": _safe_url(target),
                "observed_at": _now(),
                **_public_probe(probe),
                "differences_from_no_header": differences,
                "qualification": _QUALIFICATION,
            }
        )

    neutral_state = _neutral_access_state(target, baseline)
    observations.append(
        {
            "record_type": "observation",
            "observation_type": "neutral_access",
            "target_url": _safe_url(target),
            "observed_at": _now(),
            "neutral_access_state": neutral_state,
            "final_url": _safe_url(str(baseline["final_url"])),
            "final_status": baseline["final_status"],
            "redirect_hop_count": max(len(_hops(baseline)) - 1, 0),
            "content_stable_across_repeat": content_stable,
            "qualification": _QUALIFICATION,
        }
    )

    for label in ("none", "wildcard"):
        probe = probes[label]
        reason = _trap_reason(target, probe)
        if reason:
            candidates.append(_candidate("bot_trap", target, [probe], trap_reason=reason))

    redirecting = [
        (probe, differences)
        for probe, differences in varying
        if "redirect_target_changed" in differences and _first_hop_redirects(probe)
    ]
    if redirecting:
        candidates.append(
            _candidate(
                "language_redirect_detected",
                target,
                [baseline, *[probe for probe, _ in redirecting]],
                ticket_flag="forced_language_redirect",
                redirect_statuses=sorted(
                    {status for probe, _ in redirecting if isinstance(status := _first_hop(probe).get("status"), int)}
                ),
                redirect_targets={
                    str(probe["variant"]): _safe_url(str(_first_hop(probe)["location"])) for probe, _ in redirecting
                },
            )
        )
    if varying:
        missing = [
            str(probe["variant"])
            for probe in [baseline, *[probe for probe, _ in varying]]
            if not _varies_on_language(_first_hop(probe).get("vary"))
        ]
        if missing:
            candidates.append(
                _candidate(
                    "missing_vary_header",
                    target,
                    [baseline, *[probe for probe, _ in varying]],
                    variants_missing_vary=missing,
                    differences={str(probe["variant"]): differences for probe, differences in varying},
                )
            )
    return observations, candidates


def _differences(baseline: Mapping[str, object], probe: Mapping[str, object], *, content_stable: bool) -> list[str]:
    differences = []
    if _first_hop(baseline).get("status") != _first_hop(probe).get("status"):
        differences.append("first_status_changed")
    if _first_hop(baseline).get("location") != _first_hop(probe).get("location"):
        differences.append("redirect_target_changed")
    if _url_key(str(baseline["final_url"])) != _url_key(str(probe["final_url"])):
        differences.append("final_url_changed")
    if baseline["final_status"] != probe["final_status"]:
        differences.append("final_status_changed")
    if baseline["outcome"] == probe["outcome"] == "resolved" and "final_url_changed" not in differences:
        if baseline.get("html_lang") != probe.get("html_lang"):
            differences.append("html_lang_changed")
        if content_stable and not _same_content(baseline, probe, strict=False):
            differences.append("content_changed")
    return differences


def _same_content(left: Mapping[str, object], right: Mapping[str, object], *, strict: bool) -> bool:
    if left.get("body_sha256") == right.get("body_sha256"):
        return True
    left_hash, right_hash = left.get("body_simhash"), right.get("body_simhash")
    if not isinstance(left_hash, int) or not isinstance(right_hash, int):
        return False
    distance = (left_hash ^ right_hash).bit_count()
    return distance == 0 if strict else distance <= _SIMHASH_TOLERANCE


def _trap_reason(target: str, probe: Mapping[str, object]) -> str | None:
    outcome = probe["outcome"]
    if outcome in {"redirect_loop", "redirect_limit_exceeded", "redirect_without_location"}:
        return str(outcome)
    if outcome == "fetch_error":
        return "fetch_error"
    status = probe.get("final_status")
    if outcome == "resolved" and isinstance(status, int) and status >= 400:
        return "error_status"
    if outcome in {"resolved", "redirect_target_not_admitted"} and not _same_site_host(target, str(probe["final_url"])):
        return "left_primary_host"
    return None


def _neutral_access_state(target: str, probe: Mapping[str, object]) -> str:
    reason = _trap_reason(target, probe)
    if reason:
        return f"trap:{reason}"
    if probe["outcome"] in {"not_admitted", "redirect_target_not_admitted"}:
        return str(probe["outcome"])
    if probe["final_status"] != 200:
        return f"resolved_status_{probe['final_status']}"
    return "clean" if len(_hops(probe)) == 1 else "reached_after_redirects"


def _candidate(
    candidate_type: str, target: str, probes: Sequence[Mapping[str, object]], **fields: object
) -> dict[str, object]:
    return {
        "record_type": "candidate",
        "candidate_type": candidate_type,
        "target_url": _safe_url(target),
        "observed_at": _now(),
        **fields,
        "probes": [_public_probe(probe) for probe in probes],
        "qualification": _QUALIFICATION,
    }


def _public_probe(probe: Mapping[str, object]) -> dict[str, object]:
    hops = _hops(probe)
    return {
        "variant": probe["variant"],
        "request_headers": probe["request_headers"],
        "outcome": probe["outcome"],
        "final_url": _safe_url(str(probe["final_url"])),
        "final_status": probe["final_status"],
        "html_lang": probe["html_lang"],
        "body_sha256": probe["body_sha256"],
        "redirect_chain": [
            {**hop, "url": _safe_url(str(hop["url"])), "location": _safe_url(str(hop["location"] or "") or None)}
            for hop in hops
        ],
    }


def _hops(probe: Mapping[str, object]) -> list[dict[str, object]]:
    hops = probe["hops"]
    assert isinstance(hops, list)
    return hops


def _first_hop(probe: Mapping[str, object]) -> Mapping[str, object]:
    hops = _hops(probe)
    return hops[0] if hops else {}


def _first_hop_redirects(probe: Mapping[str, object]) -> bool:
    return _first_hop(probe).get("status") in _REDIRECT_STATUSES and bool(_first_hop(probe).get("location"))


def _varies_on_language(vary: object) -> bool:
    tokens = {token.strip().lower() for token in str(vary or "").split(",")}
    return "accept-language" in tokens or "*" in tokens


def _same_site_host(left: str, right: str) -> bool:
    def bare(url: str) -> str:
        host = (urlsplit(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host

    return bare(left) == bare(right)


def _set_cookie_summary(value: str | None) -> list[dict[str, object]]:
    """Cookie names and attribute names only; values can be session secrets."""
    if not value:
        return []
    summaries = []
    # Folded multi-cookie headers are comma-joined; Expires dates also contain
    # commas, so only split before something that looks like ``name=``.
    for cookie in re.split(r",\s*(?=[^;,=\s]+=)", value):
        parts = [part.strip() for part in cookie.split(";") if part.strip()]
        if not parts or "=" not in parts[0]:
            continue
        name = parts[0].split("=", 1)[0].strip()
        summaries.append(
            {
                "name": name,
                "attributes": sorted({part.split("=", 1)[0].strip().lower() for part in parts[1:]}),
                "language_cookie_name_candidate": bool(_LANGUAGE_COOKIE.search(name)),
            }
        )
    return summaries


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if str(key).lower() == name:
            return str(value)
    return None


def _url_key(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path or '/'}?{parts.query}"


def _safe_url(url: str | None) -> str | None:
    return redact_url_without_digest(url) if url else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
