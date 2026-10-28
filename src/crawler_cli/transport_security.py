"""HSTS preload eligibility and OCSP stapling evidence (ticket 259).

This module is deliberately split into three layers:

Parser
    :func:`parse_strict_transport_security` is the single RFC 6797 parser for
    ``Strict-Transport-Security``. Ticket 150 (passive security posture) should
    reuse it for its ``posture.hsts.*`` facts rather than writing a second one.

Classifiers
    :func:`hsts_preload_assessment` applies the hstspreload.org submission
    criteria that are observable from crawl evidence, and
    :func:`classify_ocsp_stapling` maps a TLS handshake observation onto the
    ``stapled`` / ``not_stapled`` / ``unsupported`` / ``not_determinable``
    vocabulary.

Report
    :func:`transport_security_report` builds per-host technical-audit rows
    from saved response headers and HTTP-scheme URL-variant probes. It sends
    no requests of its own.

Two things are intentionally *not* claimed:

* Chromium preload-list membership. That needs an authoritative external
  lookup (hstspreload.org or the Chromium source list); without one the
  report says ``not_queried`` instead of guessing.
* OCSP stapling. Neither the stdlib :mod:`ssl` module (no ``status_request``
  request or stapled-response accessor) nor the bundled curl_cffi/BoringSSL
  build (``CURLOPT_SSL_VERIFYSTATUS`` returns ``CURLE_NOT_BUILT_IN``) can
  observe a stapled response, so live hosts record ``not_determinable``.
  :func:`classify_ocsp_stapling` exists so an inspector built on a TLS stack
  that does expose the staple can plug into the same evidence vocabulary.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Literal
from urllib.parse import urlsplit

from .exposure_inventory import registrable_domain
from .redaction import redact_url_without_digest

TRANSPORT_SECURITY_RULESET_VERSION = "crawler-cli/transport-security/1"
HSTS_PRELOAD_MIN_MAX_AGE = 31_536_000
"""hstspreload.org minimum ``max-age`` (one year, in seconds)."""

OcspStaplingState = Literal["stapled", "not_stapled", "unsupported", "not_determinable"]

OCSP_NOT_DETERMINABLE_REASON = (
    "tls_stack_cannot_request_or_expose_stapled_ocsp: stdlib ssl has no status_request/stapled-response API; "
    "curl_cffi BoringSSL build rejects CURLOPT_SSL_VERIFYSTATUS"
)


@dataclass(frozen=True, slots=True)
class HstsPolicy:
    """A parsed ``Strict-Transport-Security`` header value."""

    present: bool
    valid: bool
    max_age: int | None = None
    include_subdomains: bool = False
    preload: bool = False
    errors: tuple[str, ...] = ()
    raw: str | None = None
    header_instances: int = 0

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["errors"] = list(self.errors)
        return payload


def parse_strict_transport_security(value: str | None) -> HstsPolicy:
    """Parse an STS header value per RFC 6797 section 6.1.

    Directive names are case-insensitive, values may be quoted strings, a
    repeated directive or a missing/non-numeric ``max-age`` makes the header
    invalid, and unknown directives are ignored. When the transport folded
    several header instances into one comma-joined value, only the first is
    used, which is what a user agent does (RFC 6797 section 8.1).
    """
    if value is None or not value.strip():
        return HstsPolicy(present=False, valid=False, raw=value)
    instances = _split_outside_quotes(value, ",")
    first = instances[0]
    errors: list[str] = []
    seen: set[str] = set()
    max_age: int | None = None
    include_subdomains = False
    preload = False
    for token in _split_outside_quotes(first, ";"):
        token = token.strip()
        if not token:
            continue
        name, has_value, raw_value = token.partition("=")
        name = name.strip().lower()
        directive_value = _unquote(raw_value.strip()) if has_value else None
        if name in seen:
            errors.append(f"duplicate_directive:{name}")
            continue
        seen.add(name)
        if name == "max-age":
            if directive_value is None or not directive_value.isdigit():
                errors.append("max_age_not_a_non_negative_integer")
            else:
                max_age = int(directive_value)
        elif name == "includesubdomains":
            if has_value:
                errors.append("includesubdomains_takes_no_value")
            include_subdomains = True
        elif name == "preload":
            # ``preload`` is not in RFC 6797; it is the hstspreload.org opt-in
            # token and is conventionally valueless.
            preload = True
    if "max-age" not in seen:
        errors.append("max_age_missing")
    return HstsPolicy(
        present=True,
        valid=not errors,
        max_age=max_age,
        include_subdomains=include_subdomains,
        preload=preload,
        errors=tuple(errors),
        raw=value,
        header_instances=len(instances),
    )


@dataclass(frozen=True, slots=True)
class HstsPreloadAssessment:
    """Observable hstspreload.org criteria for one HTTPS host."""

    host: str
    registrable_domain: str | None
    is_apex: bool
    policy: HstsPolicy
    http_redirect_state: str
    eligibility_state: str
    hsts_preload_eligible: bool | None
    warnings: tuple[str, ...] = field(default_factory=tuple)


def hsts_preload_directive_warnings(policy: HstsPolicy) -> list[str]:
    """Return actionable warnings for the header-only preload requirements."""
    if not policy.present:
        return ["hsts_header_missing"]
    warnings = [f"hsts_header_invalid:{error}" for error in policy.errors]
    if policy.max_age is None or policy.max_age < HSTS_PRELOAD_MIN_MAX_AGE:
        warnings.append(f"max_age_below_{HSTS_PRELOAD_MIN_MAX_AGE}")
    if not policy.include_subdomains:
        warnings.append("include_subdomains_missing")
    if not policy.preload:
        warnings.append("preload_token_missing")
    if policy.header_instances > 1:
        warnings.append("multiple_sts_header_instances_first_used")
    return warnings


def hsts_preload_assessment(host: str, policy: HstsPolicy, http_redirect_state: str) -> HstsPreloadAssessment:
    """Assess one HTTPS host against the observable preload criteria.

    ``http_redirect_state`` is one of ``same_host_https`` (``http://host/``
    redirected straight to ``https://host/``), ``other_https_host``,
    ``not_https``, ``not_redirected`` or ``not_observed``.

    Only a registrable domain (apex) can be submitted to the preload list; a
    subdomain is reported for header hygiene but is ``not_applicable``.
    Certificate validity and "all subdomains served over HTTPS" are not
    observable from a crawl, so eligibility means "no observed blocker", not
    that a submission would be accepted.
    """
    host = host.lower().rstrip(".")
    apex = registrable_domain(host)
    is_apex = apex is not None and apex == host
    if not is_apex:
        warnings: list[str] = []
        if not policy.present:
            warnings.append("hsts_header_missing")
        warnings.extend(f"hsts_header_invalid:{error}" for error in policy.errors)
        return HstsPreloadAssessment(
            host=host,
            registrable_domain=apex,
            is_apex=False,
            policy=policy,
            http_redirect_state=http_redirect_state,
            eligibility_state="not_applicable_not_registrable_domain",
            hsts_preload_eligible=None,
            warnings=tuple(warnings),
        )
    warnings = hsts_preload_directive_warnings(policy)
    if http_redirect_state == "other_https_host":
        warnings.append("http_redirect_must_reach_https_on_same_host_first")
    elif http_redirect_state in {"not_https", "not_redirected"}:
        warnings.append("http_not_redirected_to_https")
    blocking = [warning for warning in warnings if warning != "multiple_sts_header_instances_first_used"]
    if blocking:
        state, eligible = "not_eligible", False
    elif http_redirect_state == "same_host_https":
        state, eligible = "eligible_no_observed_blocker", True
    else:
        state, eligible = "undetermined_http_redirect_not_observed", None
    return HstsPreloadAssessment(
        host=host,
        registrable_domain=apex,
        is_apex=True,
        policy=policy,
        http_redirect_state=http_redirect_state,
        eligibility_state=state,
        hsts_preload_eligible=eligible,
        warnings=tuple(warnings),
    )


@dataclass(frozen=True, slots=True)
class OcspHandshakeObservation:
    """What a TLS inspector saw while offering ``status_request``.

    ``server_acknowledged_status_request`` is ``None`` when the stack cannot
    tell (for example TLS 1.3, where the staple rides in the Certificate
    message and there is no separate ServerHello acknowledgement).
    """

    handshake_completed: bool
    status_request_offered: bool
    stapled_response_present: bool = False
    ocsp_response_status: str | None = None
    server_acknowledged_status_request: bool | None = None
    error: str | None = None


def classify_ocsp_stapling(observation: OcspHandshakeObservation | None) -> dict[str, object]:
    """Map a handshake observation onto the stapling vocabulary.

    ``None`` (no inspector available) and any handshake that did not complete
    or did not offer ``status_request`` are ``not_determinable``: absence of
    evidence is never reported as ``not_stapled``.
    """
    if observation is None:
        return _ocsp_result("not_determinable", None, OCSP_NOT_DETERMINABLE_REASON)
    if not observation.handshake_completed:
        return _ocsp_result("not_determinable", None, f"handshake_failed:{observation.error or 'unknown'}")
    if not observation.status_request_offered:
        return _ocsp_result("not_determinable", None, "status_request_extension_not_offered")
    if observation.stapled_response_present:
        status = (observation.ocsp_response_status or "").lower()
        if status == "successful":
            return _ocsp_result("stapled", True, "stapled_ocsp_response_successful", status)
        return _ocsp_result("not_stapled", False, "stapled_ocsp_response_not_successful", status or None)
    if observation.server_acknowledged_status_request is False:
        return _ocsp_result("unsupported", False, "server_did_not_acknowledge_status_request")
    return _ocsp_result("not_stapled", False, "handshake_completed_without_stapled_response")


def _ocsp_result(
    state: OcspStaplingState, stapled: bool | None, reason: str, response_status: str | None = None
) -> dict[str, object]:
    return {
        "ocsp_stapling_state": state,
        "ocsp_stapled": stapled,
        "ocsp_response_status": response_status,
        "ocsp_reason": reason,
        "seo_impact": "informational_low; not_a_ttfb_defect_claim",
    }


def transport_security_report(
    performance_rows: Sequence[Mapping[str, object]],
    url_variant_rows: Sequence[Mapping[str, object]] = (),
    *,
    ocsp_observations: Mapping[str, OcspHandshakeObservation] | None = None,
) -> list[dict[str, object]]:
    """Return a coverage row followed by one row per observed HTTPS host.

    HSTS is taken only from HTTPS responses (RFC 6797 section 8.1 says user
    agents ignore it over HTTP). The header for a host is the one on its
    ``/`` response when that was crawled, otherwise on the first sorted URL.
    HTTP-to-HTTPS behaviour comes only from ``scheme`` URL-variant probes.

    Stored headers belong to the final response after redirects, so each row
    must carry that response's URL as ``final_url`` (ticket 414). Scheme and
    host come from ``final_url`` only; ``requested_url`` (or ``url``) is
    provenance and never decides the host, so a redirecting source host is
    not given the destination's policy. A row with no ``final_url`` has no
    known response identity and is counted, not guessed.
    """
    responses: dict[str, tuple[str, dict[str, str]]] = {}
    requested: dict[str, set[str]] = {}
    http_rows = 0
    unusable = 0
    identity_unknown = 0
    for row in performance_rows:
        final_url = row.get("final_url")
        if not isinstance(final_url, str) or not final_url.strip():
            identity_unknown += 1
            continue
        response_url = final_url.strip()
        requested_url = str(row.get("requested_url") or row.get("url") or "")
        parsed = urlsplit(response_url)
        status = row.get("final_status_code")
        if parsed.scheme.lower() == "http":
            http_rows += 1
            continue
        if parsed.scheme.lower() != "https" or not parsed.hostname or not isinstance(status, int):
            unusable += 1
            continue
        if not 200 <= status < 400:
            unusable += 1
            continue
        host = parsed.hostname.lower().rstrip(".")
        current = responses.get(host)
        if current is None or _response_rank(response_url) < _response_rank(current[0]):
            responses[host] = (response_url, _header_map(row.get("headers_json")))
        if requested_url:
            requested.setdefault(response_url, set()).add(requested_url)

    redirects = _http_redirect_states(url_variant_rows)
    variant_available = bool(url_variant_rows) and url_variant_rows[0].get("record_type") == "coverage"
    host_rows: list[dict[str, object]] = []
    for host in sorted(responses):
        url, headers = responses[host]
        policy = parse_strict_transport_security(headers.get("strict-transport-security"))
        assessment = hsts_preload_assessment(host, policy, redirects.get(host, "not_observed"))
        ocsp = classify_ocsp_stapling((ocsp_observations or {}).get(host))
        host_rows.append(
            {
                "record_type": "candidate" if assessment.warnings else "observation",
                "host": host,
                "registrable_domain": assessment.registrable_domain,
                "is_apex": assessment.is_apex,
                "response_url": redact_url_without_digest(url),
                "requested_urls": sorted(redact_url_without_digest(item) for item in requested.get(url, ())),
                "hsts": policy.as_dict(),
                "http_redirect_state": assessment.http_redirect_state,
                "hsts_preload_eligible": assessment.hsts_preload_eligible,
                "hsts_preload_state": assessment.eligibility_state,
                "hsts_preload_list_membership": "not_queried",
                "warnings": list(assessment.warnings),
                **ocsp,
                "ruleset_version": TRANSPORT_SECURITY_RULESET_VERSION,
            }
        )
    coverage: dict[str, object] = {
        "record_type": "coverage",
        "ruleset_version": TRANSPORT_SECURITY_RULESET_VERSION,
        "source": "stored_https_response_headers; http_scheme_url_variant_probes",
        "https_host_count": len(host_rows),
        "apex_host_count": sum(row["is_apex"] is True for row in host_rows),
        "hsts_present_host_count": sum(_hsts_present(row) for row in host_rows),
        "hsts_preload_eligible_count": sum(row["hsts_preload_eligible"] is True for row in host_rows),
        "hsts_preload_not_eligible_count": sum(row["hsts_preload_eligible"] is False for row in host_rows),
        "hsts_preload_undetermined_count": sum(
            row["is_apex"] is True and row["hsts_preload_eligible"] is None for row in host_rows
        ),
        "candidate_host_count": sum(row["record_type"] == "candidate" for row in host_rows),
        "http_rows_ignored_for_hsts": http_rows,
        "unusable_rows": unusable,
        "response_identity_unknown_rows": identity_unknown,
        "hsts_attribution": "final_response_host; requested_url is provenance only",
        "http_redirect_evidence": "scheme_variant_probes" if variant_available else "unavailable_not_probed",
        "hsts_preload_list_membership": "not_queried_requires_authoritative_external_lookup",
        "hsts_preload_criteria_not_observable": ["valid_certificate_chain", "all_subdomains_served_over_https"],
        "ocsp_stapling_state_counts": _state_counts(host_rows),
        "ocsp_stapling_policy": "informational_low_seo_impact; not_determinable is never reported as not_stapled",
    }
    return [coverage, *host_rows]


def _response_rank(url: str) -> tuple[int, str]:
    return (0 if (urlsplit(url).path or "/") == "/" else 1, url)


def _http_redirect_states(rows: Sequence[Mapping[str, object]]) -> dict[str, str]:
    states: dict[str, str] = {}
    for row in rows:
        if row.get("variant_kind") != "scheme" or row.get("candidate_type") != "url_variant_observation":
            continue
        variant = urlsplit(str(row.get("variant_url") or ""))
        if variant.scheme.lower() != "http" or not variant.hostname or (variant.path or "/") != "/":
            continue
        host = variant.hostname.lower().rstrip(".")
        status = row.get("http_status")
        location = urlsplit(str(row.get("redirect_location") or ""))
        if isinstance(status, int) and 300 <= status < 400 and location.scheme:
            if location.scheme.lower() != "https":
                state = "not_https"
            elif (location.hostname or "").lower().rstrip(".") == host:
                state = "same_host_https"
            else:
                state = "other_https_host"
        elif isinstance(status, int) and status > 0:
            state = "not_redirected"
        else:
            continue
        states[host] = state
    return states


def _hsts_present(row: Mapping[str, object]) -> bool:
    hsts = row.get("hsts")
    return isinstance(hsts, Mapping) and hsts.get("present") is True


def _state_counts(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        state = str(row.get("ocsp_stapling_state"))
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _header_map(value: object) -> dict[str, str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return {str(key).lower(): str(item) for key, item in value.items()} if isinstance(value, Mapping) else {}


def _split_outside_quotes(value: str, separator: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quoted = False
    escaped = False
    for char in value:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\" and quoted:
            current.append(char)
            escaped = True
        elif char == '"':
            current.append(char)
            quoted = not quoted
        elif char == separator and not quoted:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        inner = value[1:-1]
        result: list[str] = []
        escaped = False
        for char in inner:
            if escaped or char != "\\":
                result.append(char)
                escaped = False
            else:
                escaped = True
        return "".join(result)
    return value
