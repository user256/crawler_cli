"""Answerers for questions whose evidence arrives as run-scoped observations.

These questions need a rendered or mobile page, an active probe, or a supplied
third-party record (stream C of the question queue). Their evidence is an
observation bundle attached to the audit (see ``audit_observations``), never a
live request made by the runner.

Each answerer reports which records it tested.  A record that lacks the field
a rule needs is untested, which keeps the answer below Healthy; a kind with no
tested record at all leaves the question Pending.  Every row carries the
source, time and coverage of the collection it came from.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

from .audit_observations import observation_collections
from .robots import _RobotsRules
from .technical_audit_questions import (
    Answerer,
    Evidence,
    Json,
    _int_or_none,
    _path_and_query,
    _profile_value,
)


# A rule returns a finding (text) for an affected record, None for a clean
# one, UNTESTED when the record lacks the field the rule needs, and EXCLUDED
# when the record is outside the question's population.
UNTESTED = object()
EXCLUDED = object()
Rule = Callable[[Json, Json, Json | None], object]

AI_CRAWLERS = (
    "GPTBot",
    "OAI-SearchBot",
    "ClaudeBot",
    "Claude-SearchBot",
    "PerplexityBot",
    "Google-Extended",
    "CCBot",
)
_QUESTION_RULE_CODES = {"canonical_changed", "indexing_directive_changed", "hreflang_changed"}


class _Observed:
    """Records of one observation kind with their collection provenance."""

    def __init__(self, audit: Json, kind: str) -> None:
        self.kind = kind
        self.collections = observation_collections(audit, kind)
        self.records: list[dict[str, Any]] = []
        for item in self.collections:
            provenance = {
                "observation_source": str(item.get("source", "")),
                "observed_at": str(item.get("collected_at", "")),
                "coverage": str(item.get("coverage_state", "")),
            }
            for record in item["records"]:
                if isinstance(record, Mapping):
                    self.records.append({**record, "_provenance": provenance})
        self.complete = bool(self.collections) and all(
            item.get("coverage_state") == "complete" for item in self.collections
        )

    @property
    def missing(self) -> Evidence:
        return Evidence(
            available=False,
            note=f"No {self.kind} observations attached (technical-audit-questions --observations).",
        )

    def scopes(self) -> str:
        return "; ".join(f"{item.get('source')}: {item.get('scope')}" for item in self.collections)


def _row(record: Json, fields: Iterable[str], finding: object) -> dict[str, object]:
    row: dict[str, object] = {field: record.get(field) for field in fields}
    row["finding"] = finding
    row.update(record.get("_provenance") or {})
    return row


def _evaluate(
    audit: Json,
    question: Json,
    profile: Json | None,
    *,
    kind: str,
    rule: Rule,
    fields: tuple[str, ...],
    by_template: bool = False,
    scope_note: str = "",
    qualification: str | None = None,
    keep: Callable[[Json, Json | None], bool] | None = None,
) -> Evidence:
    observed = _Observed(audit, kind)
    if not observed.collections:
        return observed.missing
    tested: list[tuple[dict[str, Any], object]] = []
    untested = 0
    for record in observed.records:
        if keep is not None and not keep(record, profile):
            continue
        verdict = rule(record, question, profile)
        if verdict is EXCLUDED:
            continue
        if verdict is UNTESTED:
            untested += 1
            continue
        tested.append((record, verdict))
    notes = [f"Observations: {observed.scopes()}."]
    if scope_note:
        notes.append(scope_note)
    if untested:
        notes.append(f"{untested:,} {kind} records lack the fields this rule needs and were not tested.")
    if not tested:
        return Evidence(available=False, note=" ".join(notes))
    if by_template:
        rows, denominator, inferred = _template_rows(tested, profile)
        if inferred:
            notes.append("No site-profile templates matched; pages are grouped by their first non-locale path segment.")
    else:
        rows = [_row(record, fields, verdict) for record, verdict in tested if verdict is not None]
        denominator = len(tested)
    return Evidence(
        rows=rows,
        denominator=denominator,
        scope_complete=not scope_note and not untested,
        coverage_complete=observed.complete,
        qualification=qualification,
        note=" ".join(notes),
    )


def _template_rows(
    tested: list[tuple[dict[str, Any], object]], profile: Json | None
) -> tuple[list[dict[str, object]], int, bool]:
    groups: dict[str, list[tuple[dict[str, Any], object]]] = {}
    inferred = False
    for record, verdict in tested:
        template = str(record.get("template") or "") or _template_name(str(record.get("url", "")), profile)
        if not template:
            inferred = True
            template = _path_family(str(record.get("url", "")))
        groups.setdefault(template, []).append((record, verdict))
    rows = []
    for template, members in groups.items():
        affected = [(record, verdict) for record, verdict in members if verdict is not None]
        if not affected:
            continue
        record, verdict = affected[0]
        rows.append(
            {
                "template": template,
                "affected_pages": len(affected),
                "tested_pages": len(members),
                "sample_url": record.get("url"),
                "finding": verdict,
                **(record.get("_provenance") or {}),
            }
        )
    return rows, len(groups), inferred


def _template_name(url: str, profile: Json | None) -> str:
    templates = _profile_value(profile or {}, "templates")
    if not isinstance(templates, Mapping):
        return ""
    path = _path_and_query(url)
    for name, spec in templates.items():
        pattern = spec.get("pattern") if isinstance(spec, Mapping) else None
        if isinstance(pattern, str) and re.search(pattern, path):
            return str(name)
    return ""


_LOCALE_SEGMENT = re.compile(r"^[a-z]{2}(?:[-_][a-z]{2,4})?$", re.IGNORECASE)


def _path_family(url: str) -> str:
    """First path segment, skipping a leading locale such as /ar/ or /pt-br/."""
    segments = [part for part in urlsplit(url).path.split("/") if part]
    if segments and _LOCALE_SEGMENT.match(segments[0]):
        segments = segments[1:]
    return f"/{segments[0]}/" if segments else "/"


def _matches_template(name: str) -> Callable[[Json, Json | None], bool]:
    def keep(record: Json, profile: Json | None) -> bool:
        if record.get("template"):
            return str(record["template"]) == name
        pattern = _profile_value(profile or {}, f"templates.{name}.pattern")
        return isinstance(pattern, str) and bool(re.search(pattern, _path_and_query(str(record.get("url", "")))))

    return keep


def _needs_profile(key: str, inner: Callable[[Json, Json, Json | None], Evidence]) -> Callable[..., Evidence]:
    def answer(audit: Json, question: Json, profile: Json | None) -> Evidence:
        if _profile_value(profile or {}, key) is None:
            return Evidence(available=False, note=f"site profile lacks {key}")
        return inner(audit, question, profile)

    return answer


def _observe(kind: str, rule: Rule, fields: tuple[str, ...] = ("url",), **options: Any) -> Callable[..., Evidence]:
    def answer(audit: Json, question: Json, profile: Json | None) -> Evidence:
        return _evaluate(audit, question, profile, kind=kind, rule=rule, fields=fields, **options)

    return answer


def _profile_list(profile: Json | None, key: str) -> list[object]:
    value = _profile_value(profile or {}, key)
    return list(value) if isinstance(value, list) else []


def _has(record: Json, *keys: str) -> bool:
    return all(key in record for key in keys)


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _host(url: str) -> str:
    host = (urlsplit(url).hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def _domain_listed(host: str, domains: Iterable[object]) -> bool:
    host = host.casefold().removeprefix("www.")
    for domain in domains:
        text = str(domain).casefold().removeprefix("www.")
        if text and (host == text or host.endswith("." + text)):
            return True
    return False


# --- stored-HTML signals ----------------------------------------------------


def _mixed_content(record: Json, _q: Json, _p: Json | None) -> object:
    if not _has(record, "is_https", "mixed_content", "insecure_internal_links"):
        return UNTESTED
    if not record["is_https"]:
        return EXCLUDED
    mixed = list(record["mixed_content"] or [])
    links = list(record["insecure_internal_links"] or [])
    if not mixed and not links:
        return None
    parts = []
    if mixed:
        first = mixed[0] if isinstance(mixed[0], Mapping) else {}
        parts.append(f"{len(mixed)} http:// subresources (first: {first.get('tag')} {first.get('url')})")
    if links:
        parts.append(f"{len(links)} internal http:// links (first: {links[0]})")
    return "; ".join(parts)


def _insecure_forms(audit: Json, question: Json, profile: Json | None) -> Evidence:
    observed = _Observed(audit, "html-signals")
    if not observed.collections:
        return observed.missing
    rows: list[dict[str, object]] = []
    forms = untested = 0
    for record in observed.records:
        if "forms" not in record:
            untested += 1
            continue
        for form in record["forms"] or []:
            if not isinstance(form, Mapping):
                continue
            forms += 1
            if form.get("insecure"):
                rows.append(
                    {
                        "url": record.get("url"),
                        "action": form.get("action"),
                        "resolved_action": form.get("resolved_action"),
                        "method": form.get("method"),
                        **record["_provenance"],
                    }
                )
    note = f"Observations: {observed.scopes()}."
    if untested:
        note += f" {untested:,} pages carry no form inventory and were not tested."
    if untested == len(observed.records):
        return Evidence(available=False, note=note)
    return Evidence(
        rows=rows, denominator=forms, scope_complete=not untested, coverage_complete=observed.complete, note=note
    )


def _tracking_preloads(record: Json, _q: Json, _p: Json | None) -> object:
    if "tracking_preloads" not in record:
        return UNTESTED
    preloads = list(record["tracking_preloads"] or [])
    return (
        f"preloads {preloads[0]}" + (f" and {len(preloads) - 1} more" if len(preloads) > 1 else "")
        if preloads
        else None
    )


def _font_loading(record: Json, _q: Json, _p: Json | None) -> object:
    if not _has(record, "font_faces_without_swap", "font_preloads"):
        return UNTESTED
    blocking = list(record["font_faces_without_swap"] or [])
    preloads = _int_or_none(record["font_preloads"]) or 0
    parts = []
    if blocking:
        first = blocking[0] if isinstance(blocking[0], Mapping) else {}
        parts.append(
            f"{len(blocking)} @font-face rules without swap/optional "
            f"(first: {first.get('family') or 'unnamed'}, font-display {first.get('font_display') or 'missing'})"
        )
    if preloads > 4:
        parts.append(f"{preloads} font preloads")
    return "; ".join(parts) or None


def _render_blocking_head(record: Json, _q: Json, _p: Json | None) -> object:
    if not _has(record, "head_blocking_stylesheets", "head_sync_scripts"):
        return UNTESTED
    sheets = list(record["head_blocking_stylesheets"] or [])
    scripts = list(record["head_sync_scripts"] or [])
    parts = []
    if len(sheets) > 3:
        parts.append(f"{len(sheets)} render-blocking stylesheets")
    if scripts:
        parts.append(f"{len(scripts)} synchronous head scripts (first: {scripts[0]})")
    return "; ".join(parts) or None


def _spam_patterns(record: Json, _q: Json, _p: Json | None) -> object:
    if not _has(record, "spam_matches", "hidden_links"):
        return UNTESTED
    matches = [item for item in record["spam_matches"] or [] if isinstance(item, Mapping)]
    hidden = list(record["hidden_links"] or [])
    parts = []
    if matches:
        parts.append("terms: " + ", ".join(f"{item.get('category')}:{item.get('term')}" for item in matches[:5]))
    if hidden:
        parts.append(f"{len(hidden)} hidden external links (first: {hidden[0]})")
    return "; ".join(parts) or None


def _locale_sibling_links(record: Json, _q: Json, _p: Json | None) -> object:
    if not _has(record, "hreflang_alternates", "linked_alternates"):
        return UNTESTED
    alternates = list(record["hreflang_alternates"] or [])
    if not alternates:
        return EXCLUDED
    if record["linked_alternates"]:
        return None
    return f"no <a href> to any of {len(alternates)} hreflang alternates"


def _sitewide_external_links(audit: Json, question: Json, profile: Json | None) -> Evidence:
    observed = _Observed(audit, "html-signals")
    if not observed.collections:
        return observed.missing
    pages = [record for record in observed.records if "followed_external_links" in record]
    if not pages:
        return Evidence(available=False, note="html-signals records carry no external link inventory.")
    share = float(dict(question.get("threshold") or {}).get("min_page_share", 0.5))
    allowed = _profile_list(profile, "allowed_external_domains")
    counts: dict[str, int] = {}
    for record in pages:
        for url in dict.fromkeys(str(link) for link in record["followed_external_links"] or []):
            counts[url] = counts.get(url, 0) + 1
    rows = []
    for url, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        host = _host(url)
        if count / len(pages) > share and host and not _domain_listed(host, allowed):
            rows.append(
                {
                    "target_url": url,
                    "domain": host,
                    "pages_linking": count,
                    "page_share": round(count / len(pages), 3),
                    **pages[0]["_provenance"],
                }
            )
    untested = len(observed.records) - len(pages)
    note = f"Observations: {observed.scopes()}. Followed external links on over {share:.0%} of {len(pages):,} pages."
    if untested:
        note += f" {untested:,} pages carry no external link inventory."
    return Evidence(
        rows=rows,
        denominator=len(pages),
        scope_complete=not untested,
        coverage_complete=observed.complete,
        note=note,
    )


# --- rendered and mobile observations ---------------------------------------


def _render_parity(record: Json, _q: Json, _p: Json | None) -> object:
    if record.get("state") != "complete" or not isinstance(record.get("findings"), list):
        return UNTESTED
    changed = [
        str(item.get("field") or item.get("code"))
        for item in record["findings"]
        if isinstance(item, Mapping)
        and (
            item.get("code") in _QUESTION_RULE_CODES
            or (item.get("code") == "metadata_render_dependency" and item.get("field") == "title")
        )
    ]
    return "rendering changes " + ", ".join(dict.fromkeys(changed)) if changed else None


def _footer_parity(record: Json, _q: Json, _p: Json | None) -> object:
    footer = record.get("footer")
    if record.get("state") != "complete" or not isinstance(footer, Mapping):
        return UNTESTED
    if not _has(footer, "raw_links", "rendered_links"):
        return UNTESTED
    raw = {str(url).rstrip("/") for url in footer["raw_links"] or []}
    added = [str(url) for url in footer["rendered_links"] or [] if str(url).rstrip("/") not in raw]
    return f"{len(added)} footer links only after rendering (first: {added[0]})" if added else None


def _listing_controls(record: Json, _q: Json, _p: Json | None) -> object:
    if not _has(record, "changes_listing", "crawlable_href"):
        return UNTESTED
    if not record["changes_listing"]:
        return EXCLUDED
    if record["crawlable_href"]:
        return None
    return f"control {record.get('control')!r} ({record.get('element') or 'element'}) has no crawlable href"


def _interstitial(record: Json, _q: Json, _p: Json | None) -> object:
    share = _number(record.get("overlay_viewport_share"))
    raw = _number(record.get("raw_primary_words"))
    rendered = _number(record.get("rendered_primary_words"))
    ratio = rendered / raw if raw and rendered is not None else None
    if share is None and ratio is None:
        return UNTESTED
    parts = []
    if share is not None and share > 0.5:
        parts.append(f"{record.get('overlay_kind') or 'overlay'} covers {share:.0%} of the viewport")
    if ratio is not None and ratio < 0.5:
        parts.append(f"rendered primary content is {ratio:.0%} of the raw HTML")
    return "; ".join(parts) or None


# --- render traces ------------------------------------------------------------


def _api_requests(record: Json, question: Json, _p: Json | None) -> object:
    count = _int_or_none(record.get("api_request_count"))
    if count is None:
        return UNTESTED
    limit = int(dict(question.get("threshold") or {}).get("max_api_requests", 50))
    uncacheable = list(record.get("uncacheable_api_urls") or [])
    parts = []
    if count > limit:
        parts.append(f"{count} XHR/fetch requests")
    if uncacheable:
        parts.append(f"{len(uncacheable)} uncacheable API responses (first: {uncacheable[0]})")
    return "; ".join(parts) or None


def _lcp_element(record: Json) -> Mapping[str, Any] | None:
    element = record.get("lcp_element")
    return element if isinstance(element, Mapping) else None


def _lcp_image_attributes(record: Json, _q: Json, _p: Json | None) -> object:
    element = _lcp_element(record)
    if element is None:
        return UNTESTED
    if element.get("type") != "image" or element.get("is_background"):
        return None
    problems = []
    if str(element.get("loading") or "").casefold() == "lazy":
        problems.append("loading=lazy")
    if str(element.get("fetchpriority") or "").casefold() != "high":
        problems.append("no fetchpriority=high")
    if not element.get("width") or not element.get("height"):
        problems.append("no width/height")
    return f"LCP image {element.get('src') or ''}: {', '.join(problems)}".strip() if problems else None


def _lcp_background(record: Json, _q: Json, _p: Json | None) -> object:
    element = _lcp_element(record)
    if element is None:
        return UNTESTED
    return (
        f"LCP element is a CSS background image ({element.get('src') or 'unknown source'})"
        if element.get("is_background")
        else None
    )


def _preconnects(record: Json, _q: Json, _p: Json | None) -> object:
    if "critical_origins" not in record:
        return UNTESTED
    origin = _origin(str(record.get("url", "")))
    hinted = {_origin(str(item)) for item in record.get("preconnect_origins") or []}
    missing = [
        str(item)
        for item in dict.fromkeys(_origin(str(value)) for value in record["critical_origins"] or [])
        if item and item != origin and item not in hinted
    ]
    return f"no preconnect for {', '.join(missing)}" if missing else None


def _origin(url: str) -> str:
    parts = urlsplit(url if "//" in url else f"https://{url}")
    return f"{parts.scheme}://{parts.netloc}".casefold() if parts.netloc else ""


def _lab_vitals(audit: Json, question: Json, profile: Json | None) -> Evidence:
    observed = _Observed(audit, "render-trace")
    if not observed.collections:
        return observed.missing
    threshold = dict(question.get("threshold") or {})
    limits = {
        "lcp_ms": float(threshold.get("lcp_ms", 2500)),
        "cls": float(threshold.get("cls", 0.1)),
        "inp_ms": float(threshold.get("inp_ms", 200)),
    }
    groups: dict[str, list[dict[str, Any]]] = {}
    inferred = False
    for record in observed.records:
        template = str(record.get("template") or "") or _template_name(str(record.get("url", "")), profile)
        if not template:
            inferred = True
            template = _path_family(str(record.get("url", "")))
        groups.setdefault(template, []).append(record)
    rows: list[dict[str, object]] = []
    tested = 0
    unmeasured: set[str] = set()
    for template, members in groups.items():
        problems = []
        measured = False
        for metric, limit in limits.items():
            values = [value for value in (_number(record.get(metric)) for record in members) if value is not None]
            if not values:
                unmeasured.add(metric)
                continue
            measured = True
            p75 = _percentile(values, 0.75)
            if p75 > limit:
                problems.append(f"p75 {metric} {p75:g} > {limit:g} ({len(values)} samples)")
        images = sum(_int_or_none(record.get("images_total")) or 0 for record in members)
        missing = sum(_int_or_none(record.get("images_missing_dimensions")) or 0 for record in members)
        if images:
            measured = True
            if missing / images > 0.2:
                problems.append(f"{missing} of {images} images lack width/height")
        if not measured:
            continue
        tested += 1
        if problems:
            rows.append(
                {
                    "template": template,
                    "tested_pages": len(members),
                    "sample_url": members[0].get("url"),
                    "finding": "; ".join(problems),
                    **members[0]["_provenance"],
                }
            )
    note = f"Observations: {observed.scopes()}. Lab measurements only; confirm with CrUX or Search Console."
    if inferred:
        note += " No site-profile templates matched; pages are grouped by their first non-locale path segment."
    if unmeasured:
        note += f" Not measured for some templates: {', '.join(sorted(unmeasured))}."
    if not tested:
        return Evidence(available=False, note=note)
    return Evidence(
        rows=rows,
        denominator=tested,
        scope_complete=not unmeasured,
        coverage_complete=observed.complete,
        note=note,
    )


def _percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def _image_formats(audit: Json, question: Json, profile: Json | None) -> Evidence:
    observed = _Observed(audit, "image-resources")
    if not observed.collections:
        return observed.missing
    raster = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/avif", "image/gif"}
    legacy = {"image/jpeg", "image/jpg", "image/png"}
    seen: dict[str, dict[str, Any]] = {}
    for record in observed.records:
        if record.get("in_content") is False:
            continue
        content_type = str(record.get("content_type", "")).split(";", 1)[0].strip().casefold()
        if content_type in raster:
            seen.setdefault(str(record["image_url"]), {**record, "content_type": content_type})
    rows = [
        {
            "image_url": url,
            "page_url": record.get("page_url"),
            "content_type": record["content_type"],
            **record["_provenance"],
        }
        for url, record in seen.items()
        if record["content_type"] in legacy
    ]
    note = f"Observations: {observed.scopes()}. Share of in-content raster images; compression quality is not measured."
    if not seen:
        return Evidence(available=False, note=note)
    return Evidence(rows=rows, denominator=len(seen), coverage_complete=observed.complete, note=note)


# --- probes -------------------------------------------------------------------


def _locale_probes(audit: Json, question: Json, profile: Json | None) -> Evidence:
    observed = _Observed(audit, "locale-probe")
    if not observed.collections:
        return observed.missing
    by_url: dict[str, list[dict[str, Any]]] = {}
    untested = 0
    for record in observed.records:
        if record.get("baseline_status") is None or record.get("variant_status") is None:
            untested += 1
            continue
        by_url.setdefault(str(record["url"]), []).append(record)
    rows = []
    for url, probes in by_url.items():
        changes = []
        for probe in probes:
            what = []
            if probe["baseline_status"] != probe["variant_status"]:
                what.append(f"status {probe['baseline_status']}->{probe['variant_status']}")
            if (probe.get("baseline_location") or "") != (probe.get("variant_location") or ""):
                what.append(f"Location {probe.get('variant_location') or 'none'}")
            if probe.get("primary_content_differs") is True:
                what.append("primary content differs")
            if what:
                changes.append(f"{probe['variant']}: {', '.join(what)}")
        if changes:
            rows.append({"url": url, "finding": "; ".join(changes), **probes[0]["_provenance"]})
    note = f"Observations: {observed.scopes()}."
    if untested:
        note += f" {untested:,} probes lack a baseline or variant status."
    if not by_url:
        return Evidence(available=False, note=note)
    return Evidence(
        rows=rows,
        denominator=len(by_url),
        scope_complete=not untested,
        coverage_complete=observed.complete,
        note=note,
    )


def _host_exposure(*, mitigations: tuple[str, ...]) -> Callable[..., Evidence]:
    """Profile non-production hosts returning 200 HTML without auth or a listed mitigation."""

    def answer(audit: Json, question: Json, profile: Json | None) -> Evidence:
        observed = _Observed(audit, "host-probe")
        if not observed.collections:
            return observed.missing
        declared = [str(host).casefold() for host in _profile_list(profile, "nonproduction_hosts")]
        rows = []
        tested: set[str] = set()
        review = False
        for record in observed.records:
            host = str(record["host"]).casefold()
            status = _int_or_none(record.get("status"))
            if status is None:
                continue
            tested.add(host)
            content_type = str(record.get("content_type") or "")
            if status != 200 or record.get("auth_required") or (content_type and "html" not in content_type):
                continue
            if any(record.get(key) is True for key in mitigations):
                continue
            unknown = [key for key in mitigations if record.get(key) is None]
            if unknown:
                review = True
            rows.append(
                {
                    "host": record["host"],
                    "status": status,
                    "discovered_via": record.get("discovered_via"),
                    "finding": "200 response without authentication"
                    + (f"; not read: {', '.join(unknown)}" if unknown else f"; no {', '.join(mitigations)}"),
                    **record["_provenance"],
                }
            )
        untested = [host for host in declared if host not in tested]
        note = f"Observations: {observed.scopes()}."
        if untested:
            note += f" Profile hosts not probed: {', '.join(untested)}."
        note += " Hosts beyond the profile list and linked hosts need DNS or certificate-log discovery."
        if not tested:
            return Evidence(available=False, note=note)
        return Evidence(
            rows=rows,
            denominator=len(tested),
            scope_complete=not untested,
            coverage_complete=observed.complete,
            qualification="review_required" if review else None,
            note=note,
        )

    return answer


def _external_links(record: Json, _q: Json, profile: Json | None) -> object:
    status = _int_or_none(record.get("status"))
    if status is None:
        return UNTESTED
    problems = []
    if status >= 400:
        problems.append(f"returns {status}")
    affiliate_domains = _profile_list(profile, "affiliate.domains")
    affiliate = record.get("affiliate") is True or _domain_listed(_host(str(record["target_url"])), affiliate_domains)
    if affiliate and "rel" in record:
        rel = str(record.get("rel") or "").casefold().split()
        if "sponsored" not in rel and "nofollow" not in rel:
            problems.append("affiliate link without rel=sponsored or nofollow")
    return "; ".join(problems) or None


def _hsts_ocsp(record: Json, _q: Json, _p: Json | None) -> object:
    if "hsts_header" not in record:
        return UNTESTED
    problems = []
    header = str(record.get("hsts_header") or "")
    if not header:
        problems.append("no Strict-Transport-Security header")
    else:
        directives = [part.strip().casefold() for part in header.split(";")]
        max_age = next((part.split("=", 1)[1].strip('" ') for part in directives if part.startswith("max-age=")), "")
        if not max_age.isdigit() or int(max_age) < 31_536_000:
            problems.append(f"max-age {max_age or 'missing'}")
        for directive in ("includesubdomains", "preload"):
            if directive not in directives:
                problems.append(f"no {directive}")
    preload = record.get("preload_status")
    if preload is not None and str(preload).casefold() != "preloaded":
        problems.append(f"preload list status {preload}")
    if record.get("ocsp_stapled") is False:
        problems.append("no stapled OCSP response")
    return "; ".join(problems) or None


def _hsts_ocsp_answer(audit: Json, question: Json, profile: Json | None) -> Evidence:
    evidence = _evaluate(audit, question, profile, kind="tls-probe", rule=_hsts_ocsp, fields=("host", "hsts_header"))
    observed = _Observed(audit, "tls-probe")
    partial = [
        str(record["host"])
        for record in observed.records
        if record.get("preload_status") is None or record.get("ocsp_stapled") is None
    ]
    if not evidence.available or not partial:
        return evidence
    note = f"{evidence.note} Preload status or OCSP stapling not recorded for: {', '.join(partial)}."
    return Evidence(**{**evidence.__dict__, "scope_complete": False, "note": note})


def _utility_paths(record: Json, _q: Json, _p: Json | None) -> object:
    path_class = record.get("path_class")
    status = _int_or_none(record.get("status"))
    if path_class not in {"protected", "public-utility"} or status is None:
        return UNTESTED
    if path_class == "protected":
        if "exposes_content" not in record:
            return UNTESTED
        exposed = record["exposes_content"] is True and not record.get("auth_required")
        return f"unauthenticated {status} response exposes protected content" if exposed else None
    if record.get("noindex") is None and record.get("robots_blocked") is None:
        return UNTESTED
    if record.get("noindex") is True and record.get("robots_blocked") is True:
        return "noindex is unreadable because robots.txt blocks the URL"
    if record.get("noindex") is not True and record.get("robots_blocked") is not True:
        return "public utility URL has no noindex or robots.txt control"
    return None


def _ai_crawler_policy(audit: Json, question: Json, profile: Json | None) -> Evidence:
    observed = _Observed(audit, "robots-txt")
    if not observed.collections:
        return observed.missing
    policy = _profile_value(profile or {}, "ai_crawler_policy")
    policy = policy if isinstance(policy, Mapping) else {}
    inventory: list[str] = []
    rows: list[dict[str, object]] = []
    tested = 0
    unknown_hosts = []
    llms = []
    for record in observed.records:
        host = str(record["host"])
        status = _int_or_none(record.get("status"))
        if record.get("llms_txt_status") is not None:
            llms.append(f"{host} /llms.txt {record['llms_txt_status']}")
        if status is None or status >= 500 or (200 <= status < 300 and record.get("body") is None):
            unknown_hosts.append(host)
            continue
        # RFC 9309: an unavailable (4xx) robots.txt allows everything.
        rules = _RobotsRules(host, str(record.get("body") or "") if status < 400 else "")
        for agent in AI_CRAWLERS:
            decision = rules.check("/", agent)
            verdict = "allow" if decision.allowed else "disallow"
            inventory.append(f"{host} {agent} {verdict}")
            declared = str(policy.get(agent, "")).casefold()
            if declared not in {"allow", "disallow"}:
                continue
            tested += 1
            if declared != verdict:
                rows.append(
                    {
                        "host": host,
                        "user_agent": agent,
                        "robots_verdict": verdict,
                        "declared_policy": declared,
                        "matched_rule": decision.matched_rule,
                        "matched_user_agent": decision.matched_user_agent,
                        **record["_provenance"],
                    }
                )
    note = f"Observations: {observed.scopes()}. Verdicts are for the site root path."
    if unknown_hosts:
        note += f" robots.txt unavailable or unread for: {', '.join(unknown_hosts)}."
    if llms:
        note += f" {'; '.join(llms)} (reported only; not a defect)."
    if not policy:
        if not inventory:
            return Evidence(available=False, note=note)
        note += " No ai_crawler_policy in the site profile; per-agent verdicts: " + "; ".join(inventory) + "."
        return Evidence(rows=[], denominator=None, scope_complete=False, note=note)
    if not tested:
        return Evidence(available=False, note=note)
    undeclared = [agent for agent in AI_CRAWLERS if str(policy.get(agent, "")).casefold() not in {"allow", "disallow"}]
    if undeclared:
        note += f" Policy declares no verdict for: {', '.join(undeclared)}."
    return Evidence(
        rows=rows,
        denominator=tested,
        scope_complete=not unknown_hosts and not undeclared,
        coverage_complete=observed.complete,
        note=note,
    )


# --- supplied third-party evidence -------------------------------------------


def _google_render(record: Json, _q: Json, _p: Json | None) -> object:
    if record.get("primary_content_present") is None:
        return UNTESTED
    problems = []
    if record["primary_content_present"] is False:
        problems.append("primary content missing")
    blocked = record.get("blocked_resources")
    blocked_count = len(blocked) if isinstance(blocked, list) else _int_or_none(blocked) or 0
    if blocked_count:
        problems.append(f"{blocked_count} blocked resources")
    if record.get("render_error"):
        problems.append(f"render error: {record['render_error']}")
    return f"{record.get('tool')}: {'; '.join(problems)}" if problems else None


def _verified_google_fetch(record: Json, _q: Json, _p: Json | None) -> object:
    flags = {key: record.get(key) for key in ("content_differs", "links_differ", "directives_differ")}
    if all(value is None for value in flags.values()):
        return UNTESTED
    differs = [key.split("_", 1)[0] for key, value in flags.items() if value is True]
    return f"{', '.join(differs)} differ from the visitor fetch" if differs else None


def _topic_gap(record: Json, _q: Json, _p: Json | None) -> object:
    competitors = _int_or_none(record.get("competitors_covering"))
    if competitors is None:
        return UNTESTED
    if record.get("site_covers") is True or competitors < 1:
        return None
    return f"covered by {competitors} competitors, not by the site"


OBSERVED_ANSWERERS: dict[str, Answerer] = {
    "Q5": Answerer("html-signals mixed content on HTTPS pages", _observe("html-signals", _mixed_content)),
    "Q18": Answerer(
        "supplied URL Inspection / Rich Results Test renders per key template",
        _observe(
            "google-render-inspection",
            _google_render,
            by_template=True,
        ),
    ),
    "Q25": Answerer("locale-probe status, Location and content per variant", _locale_probes),
    "Q27": Answerer(
        "host-probe of profile non-production hosts",
        _needs_profile("nonproduction_hosts", _host_exposure(mitigations=("noindex",))),
    ),
    "Q28": Answerer(
        "external-link-recheck status and affiliate rel",
        _observe("external-link-recheck", _external_links, fields=("source_url", "target_url", "status", "rel")),
    ),
    "Q29": Answerer("render-trace lab vitals and image dimensions per template", _lab_vitals),
    "Q31": Answerer(
        "supplied verified-Google versus visitor fetch comparison",
        _observe("verified-google-fetch", _verified_google_fetch, fields=("url", "google_fetch_method")),
    ),
    "Q33": Answerer(
        "html-signals spam terms and hidden external links",
        _observe("html-signals", _spam_patterns),
    ),
    "Q35": Answerer(
        "render-trace API requests per template", _observe("render-trace", _api_requests, by_template=True)
    ),
    "Q38": Answerer(
        "listing-controls without a crawlable href on the listing template",
        _needs_profile(
            "templates.listing",
            _observe(
                "listing-controls",
                _listing_controls,
                by_template=True,
                keep=_matches_template("listing"),
            ),
        ),
    ),
    "Q43": Answerer(
        "html-signals followed external links by page share",
        _needs_profile("allowed_external_domains", _sitewide_external_links),
    ),
    "Q45": Answerer(
        "html-signals pages with hreflang alternates and no sibling link",
        _observe("html-signals", _locale_sibling_links),
    ),
    "Q46": Answerer(
        "render-parity footer links on the article template",
        _needs_profile(
            "templates.article",
            _observe("render-parity", _footer_parity, by_template=True, keep=_matches_template("article")),
        ),
    ),
    "Q50": Answerer(
        "supplied competitor topic-gap comparison",
        _observe("competitor-topic-gap", _topic_gap, fields=("topic", "query", "competitors_covering", "method")),
    ),
    "Q63": Answerer("tls-probe HSTS, preload status and OCSP stapling", _hsts_ocsp_answer),
    "Q64": Answerer(
        "render-trace critical third-party origins without preconnect",
        _observe("render-trace", _preconnects, by_template=True),
    ),
    "Q65": Answerer("html-signals analytics preloads", _observe("html-signals", _tracking_preloads, by_template=True)),
    "Q66": Answerer("image-resources content types of in-content raster images", _image_formats),
    "Q67": Answerer(
        "html-signals inline @font-face rules and font preloads",
        _observe(
            "html-signals",
            _font_loading,
            by_template=True,
            scope_note="Inline <style> @font-face rules only; external stylesheets are not fetched.",
        ),
    ),
    "Q68": Answerer(
        "render-trace LCP image attributes", _observe("render-trace", _lcp_image_attributes, by_template=True)
    ),
    "Q69": Answerer("render-trace LCP background images", _observe("render-trace", _lcp_background, by_template=True)),
    "Q77": Answerer(
        "host-probe of profile cache and preview hosts",
        _needs_profile(
            "nonproduction_hosts", _host_exposure(mitigations=("noindex", "canonical_to_main_host", "robots_blocked"))
        ),
    ),
    "Q85": Answerer(
        "render-parity canonical, title, robots and hreflang changes",
        _observe("render-parity", _render_parity, fields=("url", "final_url", "stratum")),
    ),
    "Q86": Answerer(
        "html-signals render-blocking head resources",
        _observe("html-signals", _render_blocking_head, by_template=True),
    ),
    "Q92": Answerer("html-signals form actions", _insecure_forms),
    "Q95": Answerer(
        "mobile-render overlay share and primary-content ratio",
        _observe("mobile-render", _interstitial, by_template=True),
    ),
    "Q96": Answerer("robots-txt verdicts for AI crawlers against the profile policy", _ai_crawler_policy),
    "Q102": Answerer(
        "utility-path-probe against the approved path classes",
        _observe(
            "utility-path-probe",
            _utility_paths,
            fields=("url", "path_class", "status", "auth_required", "noindex", "robots_blocked"),
        ),
    ),
}
