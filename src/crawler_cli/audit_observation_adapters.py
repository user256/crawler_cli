"""Turn crawler_cli probe results into audit observation records.

The AI-governance, Accept-Language and transport-security collectors (tickets
258-260, 264) predate the question runner. These adapters express their
results in the observation kinds documented in
``docs/technical-audit-observations.md`` so the runner can answer Q96, Q25 and
Q63 from them. They never guess: a value the collector did not record stays
``None`` or is left out, which the answerers count as untested.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit

from .accept_language_audit import normalized_probe_outcome

_NEUTRAL_VARIANTS = frozenset({"none", "none-repeat"})
_TESTED_RECORD_TYPES = frozenset({"observation", "candidate"})


def llms_txt_status_by_host(collected: Mapping[str, object]) -> dict[str, str]:
    """Map each origin's host to the recorded state of its /llms.txt."""
    rows = collected.get("llms_files")
    status: dict[str, str] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping) or row.get("path") != "/llms.txt":
            continue
        host = urlsplit(str(row.get("origin") or row.get("url") or "")).netloc.casefold()
        state = row.get("state")
        if host and isinstance(state, str):
            status[host] = state
    return status


def robots_txt_record(
    host: str, response: object, llms_txt_status: str | None, *, unknown_reason: str | None = None
) -> dict[str, object]:
    """One ``robots-txt`` record from a guarded fetch.

    The host is the record's identity; the fetch outcome is separate. A file
    that was never read (timeout, denied destination, challenge, truncated
    body, no response) keeps its host with ``fetch_outcome: "unknown"``, a null
    status and body, and the reason, so the answerer counts the host as
    untested instead of the bundle losing it (ticket 410).
    """
    status = getattr(response, "status", None) if response is not None else None
    if not isinstance(status, int) or isinstance(status, bool) or status <= 0:
        return {
            "host": host,
            "fetch_outcome": "unknown",
            "unknown_reason": unknown_reason or ("no_response" if response is None else "no_status"),
            "status": None,
            "body": None,
            "llms_txt_status": llms_txt_status,
        }
    text = getattr(response, "text", None)
    body = str(text) if 200 <= status < 300 and isinstance(text, str) else None
    return {
        "host": host,
        "fetch_outcome": "fetched",
        "status": status,
        "body": body,
        "llms_txt_status": llms_txt_status,
    }


def _http_status(value: object) -> int | None:
    """An observed HTTP status; the collector's 0 means no response was received."""
    if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
        return value
    return None


def _first_hop(probe: Mapping[str, object]) -> Mapping[str, object] | None:
    chain = probe.get("redirect_chain")
    if isinstance(chain, list) and chain and isinstance(chain[0], Mapping):
        return chain[0]
    return None


def _initial_status(probe: Mapping[str, object] | None) -> int | None:
    """Status of the first response; None when that request was never answered (ticket 412)."""
    if probe is None:
        return None
    hop = _first_hop(probe)
    return _http_status(hop.get("status") if hop is not None else probe.get("final_status"))


def _failure(probe: Mapping[str, object] | None) -> dict[str, object] | None:
    """Why a probe did not resolve: its outcome plus the first unanswered hop's skip reason."""
    if probe is None:
        return {"outcome": "not_probed", "skip_reason": None, "hop": None}
    outcome = probe.get("outcome")
    if outcome == "resolved":
        return None
    chain = probe.get("redirect_chain")
    hops = [hop for hop in chain if isinstance(hop, Mapping)] if isinstance(chain, list) else []
    for index, hop in enumerate(hops):
        if _http_status(hop.get("status")) is None:
            skip_reason = hop.get("skip_reason")
            # Older bundles labelled a timeout ``not_admitted``; the skip reason corrects it.
            return {"outcome": normalized_probe_outcome(outcome, skip_reason), "skip_reason": skip_reason, "hop": index}
    return {"outcome": outcome, "skip_reason": None, "hop": None}


def _outcome(probe: Mapping[str, object] | None) -> object:
    """The probe's outcome as the current collector labels it; None when not probed."""
    if probe is None:
        return None
    failure = _failure(probe)
    return failure["outcome"] if failure is not None else probe.get("outcome")


def _initial_location(probe: Mapping[str, object] | None) -> str | None:
    """The Location header on the first response; None when the response carried none."""
    hop = _first_hop(probe) if probe is not None else None
    location = hop.get("location") if hop is not None else None
    return str(location) if location else None


def _resolved(probe: Mapping[str, object] | None) -> bool:
    return (
        probe is not None and probe.get("outcome") == "resolved" and _http_status(probe.get("final_status")) is not None
    )


def _same_hash(left: Mapping[str, object] | None, right: Mapping[str, object] | None, field: str) -> bool | None:
    """Whether two resolved responses carry the same hash; None when either is unknown."""
    if not _resolved(left) or not _resolved(right):
        return None
    assert left is not None and right is not None
    a, b = left.get(field), right.get(field)
    if not isinstance(a, str) or not isinstance(b, str):
        return None
    return a == b


def _content_differs(
    baseline: Mapping[str, object] | None,
    probe: Mapping[str, object] | None,
    repeat: Mapping[str, object] | None,
) -> bool | None:
    """Whether the variant's primary content differs from the no-header response.

    Compares the collector's primary-content hash (visible text of ``<main>``
    or ``<body>``), never the raw response bytes (ticket 413).  None when that
    cannot be known: a probe did not resolve, a hash is missing, the regions
    were taken from different elements, or the repeated header-less control did
    not resolve to the same primary content.
    """
    if baseline is None or probe is None or repeat is None:
        return None
    field = "primary_content_sha256"
    if _same_hash(baseline, repeat, field) is not True:
        # Without a stable control request a difference proves nothing.
        return None
    if baseline.get("primary_content_basis") != probe.get("primary_content_basis"):
        return None
    same = _same_hash(baseline, probe, field)
    return None if same is None else not same


def _raw_body_differs(baseline: Mapping[str, object] | None, probe: Mapping[str, object] | None) -> bool | None:
    """Whole-response byte difference: review-only evidence, never a primary-content verdict."""
    same = _same_hash(baseline, probe, "body_sha256")
    return None if same is None else not same


def locale_probe_records(evidence: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """``locale-probe`` records: one per target and non-neutral Accept-Language variant.

    A request that was never answered (fetch error, timeout, robots or scope
    rejection) has no status, Location or content to compare, so those fields
    stay None or are left out and the answerer counts the comparison as
    untested; the outcome and skip reason are kept as evidence (ticket 412).
    """
    by_target: dict[str, dict[str, Mapping[str, object]]] = {}
    for row in evidence:
        if row.get("record_type") != "observation" or row.get("observation_type") != "accept_language_probe":
            continue
        target = str(row.get("target_url") or "")
        variant = str(row.get("variant") or "")
        if target and variant:
            by_target.setdefault(target, {})[variant] = row
    records: list[dict[str, object]] = []
    for target in sorted(by_target):
        probes = by_target[target]
        baseline = probes.get("none")
        repeat = probes.get("none-repeat")
        for variant in sorted(probes):
            if variant in _NEUTRAL_VARIANTS:
                continue
            probe = probes[variant]
            baseline_status = _initial_status(baseline)
            variant_status = _initial_status(probe)
            record: dict[str, object] = {
                "url": target,
                "variant": variant,
                "baseline_status": baseline_status,
                "variant_status": variant_status,
            }
            # A Location of None means the response had none; it is only
            # recorded when both first requests were answered.
            if baseline_status is not None and variant_status is not None:
                record["baseline_location"] = _initial_location(baseline)
                record["variant_location"] = _initial_location(probe)
            record.update(
                {
                    "primary_content_differs": _content_differs(baseline, probe, repeat),
                    "primary_content_basis": probe.get("primary_content_basis"),
                    "raw_body_differs": _raw_body_differs(baseline, probe),
                    "baseline_outcome": _outcome(baseline),
                    "variant_outcome": _outcome(probe),
                    "baseline_failure": _failure(baseline),
                    "variant_failure": _failure(probe),
                    "collection_qualification": probe.get("qualification"),
                }
            )
            records.append(record)
    return records


def tls_probe_records(report_rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """``tls-probe`` records from ``transport_security_report`` host rows.

    The preload list is never queried and OCSP stapling is not observed by the
    stored-header path, so those fields stay None and the answer stays below
    Healthy until a real probe records them.
    """
    records: list[dict[str, object]] = []
    for row in report_rows:
        if row.get("record_type") not in _TESTED_RECORD_TYPES or not row.get("host"):
            continue
        hsts = row.get("hsts")
        policy = hsts if isinstance(hsts, Mapping) else {}
        header = policy.get("raw") if policy.get("present") else None
        membership = row.get("hsts_preload_list_membership")
        stapled = row.get("ocsp_stapled")
        records.append(
            {
                "host": str(row["host"]),
                "hsts_header": str(header) if isinstance(header, str) else None,
                "preload_status": None if membership in (None, "not_queried") else str(membership),
                "ocsp_stapled": stapled if isinstance(stapled, bool) else None,
            }
        )
    return records
