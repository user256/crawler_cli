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


def _initial_status(probe: Mapping[str, object] | None) -> int | None:
    if probe is None:
        return None
    chain = probe.get("redirect_chain")
    if isinstance(chain, list) and chain and isinstance(chain[0], Mapping):
        status = chain[0].get("status")
        return status if isinstance(status, int) else None
    status = probe.get("final_status")
    return status if isinstance(status, int) else None


def _initial_location(probe: Mapping[str, object] | None) -> str | None:
    """The Location header on the first response; None when the response carried none."""
    if probe is None:
        return None
    chain = probe.get("redirect_chain")
    if isinstance(chain, list) and chain and isinstance(chain[0], Mapping):
        location = chain[0].get("location")
        return str(location) if location else None
    return None


def _content_differs(
    baseline: Mapping[str, object] | None,
    probe: Mapping[str, object] | None,
    repeat: Mapping[str, object] | None,
) -> bool | None:
    """Whether the variant body differs from the no-header body; None when that cannot be known."""
    if baseline is None or probe is None:
        return None
    base, variant = baseline.get("body_sha256"), probe.get("body_sha256")
    if not isinstance(base, str) or not isinstance(variant, str):
        return None
    control = repeat.get("body_sha256") if isinstance(repeat, Mapping) else None
    if isinstance(control, str) and control != base:
        # Two identical requests differed, so a body difference proves nothing.
        return None
    return base != variant


def locale_probe_records(evidence: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """``locale-probe`` records: one per target and non-neutral Accept-Language variant."""
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
            records.append(
                {
                    "url": target,
                    "variant": variant,
                    "baseline_status": _initial_status(baseline),
                    "variant_status": _initial_status(probe),
                    "baseline_location": _initial_location(baseline),
                    "variant_location": _initial_location(probe),
                    "primary_content_differs": _content_differs(baseline, probe, repeat),
                }
            )
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
