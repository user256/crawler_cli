"""Conservative, versioned checks for Google structured-data features.

These checks describe static property completeness only. They do not prove
content-policy compliance, rich-result validity, indexability, or appearance.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from urllib.parse import urlsplit

from .redaction import redact_url_without_digest, scrub_text

GOOGLE_STRUCTURED_DATA_RULESET_VERSION = "crawler-cli/google-structured-data-rules/1"
GOOGLE_RULES_VERIFIED_ON = "2026-09-25"


@dataclass(frozen=True)
class GoogleFeatureRule:
    feature: str
    schema_types: tuple[str, ...]
    required: tuple[str, ...]
    required_groups: tuple[tuple[str, ...], ...]
    recommended: tuple[str, ...]
    source: str
    verified_on: str


GOOGLE_FEATURE_RULES: tuple[GoogleFeatureRule, ...] = (
    GoogleFeatureRule(
        "recipe-rich-result",
        ("Recipe",),
        ("name", "image"),
        (),
        (
            "aggregateRating",
            "author",
            "cookTime",
            "datePublished",
            "description",
            "keywords",
            "prepTime",
            "recipeCategory",
            "recipeCuisine",
            "recipeYield",
            "totalTime",
            "video",
        ),
        "https://developers.google.com/search/docs/appearance/structured-data/recipe",
        GOOGLE_RULES_VERIFIED_ON,
    ),
    GoogleFeatureRule(
        "event-rich-result",
        ("Event",),
        ("name", "startDate", "location.name", "location.address"),
        (),
        ("description", "endDate", "eventStatus", "offers", "organizer", "performer", "previousStartDate"),
        "https://developers.google.com/search/docs/appearance/structured-data/event",
        GOOGLE_RULES_VERIFIED_ON,
    ),
    GoogleFeatureRule(
        "product-snippet",
        ("Product",),
        ("name",),
        (("offers", "review", "aggregateRating"),),
        ("aggregateRating", "offers", "review"),
        "https://developers.google.com/search/docs/appearance/structured-data/product-snippet",
        GOOGLE_RULES_VERIFIED_ON,
    ),
    GoogleFeatureRule(
        "breadcrumb-rich-result",
        ("BreadcrumbList",),
        ("itemListElement",),
        (),
        (),
        "https://developers.google.com/search/docs/appearance/structured-data/breadcrumb",
        GOOGLE_RULES_VERIFIED_ON,
    ),
)


def structured_data_inventory_report(
    source_rows: Sequence[Mapping[str, object]],
    *,
    rendered_rows: Sequence[Mapping[str, object]] = (),
) -> list[dict[str, object]]:
    """Return coverage and item-level feature candidates from active markup.

    Missing required properties are analyst candidates, never client actions.
    Recommended-property omissions are recorded as advisory only. JSON-LD raw
    bytes are represented by digest and bounded scrubbed excerpt, not copied
    wholesale into a publication artifact.
    """
    rules_by_type = {schema_type: rule for rule in GOOGLE_FEATURE_RULES for schema_type in rule.schema_types}
    items = [dict(row) for row in source_rows]
    items.extend(dict(row) for row in rendered_rows)
    candidates: list[dict[str, object]] = []
    inventories: list[dict[str, object]] = []
    source_counts: dict[str, int] = {}

    for row in items:
        url = str(row.get("url") or row.get("source_url") or "")
        raw_type = str(row.get("schema_type") or row.get("type") or "Unknown")
        schema_type = _normal_type(raw_type)
        channel = str(row.get("source_channel") or row.get("format") or "unknown")
        position = row.get("position", row.get("schema_position"))
        raw_data = row.get("raw_data")
        rendered_unsettled = channel == "rendered_dom" and row.get("state") != "complete"
        parsed = None if rendered_unsettled else _parse_object(row.get("parsed_data"))
        digest = hashlib.sha256(url.encode()).hexdigest() if url else None
        raw_text = str(raw_data) if raw_data is not None else ""
        identity = {
            "url": _safe_url(url),
            "url_digest_sha256": digest,
            "source_channel": channel,
            "format": row.get("format"),
            "extraction_state": row.get("extraction_state", "stored_snapshot"),
            "observation_state": row.get("state", "complete" if not rendered_unsettled else "inconclusive"),
            "schema_type": schema_type,
            "position": position,
            "parser_mode": row.get("parser_mode"),
            "json_syntax_state": (
                "not_applicable"
                if row.get("format") not in {"json-ld", None}
                else "invalid"
                if schema_type == "InvalidJSON"
                else "valid"
                if parsed is not None
                else "unavailable"
            ),
            "stored_schema_validation": (
                "local_check_pass"
                if row.get("is_valid") is True
                else "local_check_fail"
                if row.get("is_valid") is False
                else "unavailable"
            ),
            "schema_validation_scope": "existing_local_checks_not_a_comprehensive_schema_org_validator",
            "validation_errors": _safe_value(row.get("validation_errors", [])),
            "compatibility_diagnostics": _safe_value(row.get("compatibility_diagnostics", [])),
            "raw_evidence_sha256": hashlib.sha256(raw_text.encode()).hexdigest() if raw_text else None,
            "raw_evidence_excerpt": scrub_text(raw_text[:500]) if raw_text else None,
            "feature_ruleset_version": GOOGLE_STRUCTURED_DATA_RULESET_VERSION,
        }
        source_counts[channel] = source_counts.get(channel, 0) + 1
        inventories.append({"record_type": "observation", "record_kind": "structured_data_item", **identity})
        if parsed is None:
            continue

        rule = rules_by_type.get(schema_type)
        if rule is not None:
            required = list(rule.required)
            missing = [path for path in required if not _has_path(parsed, path)]
            missing_groups = [
                [path for path in group if not _has_path(parsed, path)]
                for group in rule.required_groups
                if not any(_has_path(parsed, path) for path in group)
            ]
            recommended_missing = [str(path) for path in rule.recommended if not _has_path(parsed, str(path))]
            if missing or missing_groups:
                candidates.append(
                    {
                        "record_type": "candidate",
                        "candidate_type": "google_feature_required_property_missing",
                        **identity,
                        "feature": rule.feature,
                        "missing_required_properties": missing,
                        "missing_required_property_groups": missing_groups,
                        "qualification": "static_markup_candidate_review_content_and_live_rich_results_test",
                        "source": rule.source,
                        "rules_verified_on": rule.verified_on,
                    }
                )
            if recommended_missing:
                candidates.append(
                    {
                        "record_type": "advisory",
                        "candidate_type": "google_feature_recommended_property_absent",
                        **identity,
                        "feature": rule.feature,
                        "missing_recommended_properties": recommended_missing,
                        "qualification": "advisory_only_no_remediation_action",
                        "source": rule.source,
                        "rules_verified_on": rule.verified_on,
                    }
                )
        elif schema_type == "ItemList":
            candidates.extend(_itemlist_checks(identity, parsed))
        else:
            candidates.append(
                {
                    "record_type": "observation",
                    "candidate_type": "google_feature_eligibility_not_evaluated",
                    **identity,
                    "qualification": "no_current_feature_rule_for_observed_type",
                }
            )

    coverage = {
        "record_type": "coverage",
        "ruleset_version": GOOGLE_STRUCTURED_DATA_RULESET_VERSION,
        "rules_verified_on": GOOGLE_RULES_VERIFIED_ON,
        "source_row_count": len(source_rows),
        "rendered_row_count": len(rendered_rows),
        "active_item_count": len(inventories),
        "items_by_source": source_counts,
        "feature_rule_count": len(GOOGLE_FEATURE_RULES),
        "feature_eligibility": "static_required_property_checks_only; final eligibility requires Google tools and policy/content review",
        "validity_separation": "JSON syntax, existing local validation, and Google feature-property checks are distinct; none alone proves final feature eligibility",
        "unsupported_or_stale_rules": "unavailable_not_a_missing_markup_finding",
        "recommended_property_policy": "advisory_only_no_mandatory_remediation",
    }
    return [coverage, *candidates, *inventories]


def _itemlist_checks(row: Mapping[str, object], parsed: Mapping[str, object]) -> list[dict[str, object]]:
    elements = parsed.get("itemListElement")
    values = elements if isinstance(elements, list) else [elements] if isinstance(elements, Mapping) else []
    base = {
        key: row.get(key)
        for key in (
            "url",
            "url_digest_sha256",
            "source_channel",
            "extraction_state",
            "schema_type",
            "position",
            "raw_evidence_sha256",
            "feature_ruleset_version",
        )
    }
    findings: list[dict[str, object]] = []
    if not isinstance(elements, list):
        return [
            {
                "record_type": "candidate",
                "candidate_type": "itemlist_elements_not_array",
                **base,
                "qualification": "structural_markup_review",
            }
        ]
    entries = [item for item in values if isinstance(item, Mapping)]
    if len(entries) != len(values):
        findings.append(
            _itemlist_candidate(
                "itemlist_element_not_listitem_object",
                base,
                element_indexes=[i for i, v in enumerate(values) if not isinstance(v, Mapping)],
            )
        )
    typed_entries = [item for item in entries if "ListItem" in _types(item)]
    if len(typed_entries) != len(entries):
        findings.append(
            _itemlist_candidate(
                "itemlist_element_type_unexpected",
                base,
                element_indexes=[
                    i for i, v in enumerate(values) if not isinstance(v, Mapping) or "ListItem" not in _types(v)
                ],
            )
        )

    summary_shape = bool(entries) and all(not _has_path(item, "item") for item in entries)
    all_in_one_shape = bool(entries) and all(_has_path(item, "item") for item in entries)
    if not summary_shape and not all_in_one_shape:
        findings.append(_itemlist_candidate("itemlist_summary_and_all_in_one_shapes_mixed", base))
    if not summary_shape:
        return findings

    positions: list[tuple[int, int]] = []
    urls: list[tuple[int, str]] = []
    for index, item in enumerate(values):
        if not isinstance(item, Mapping):
            continue
        position = item.get("position")
        if not isinstance(position, int) or isinstance(position, bool) or position < 1:
            findings.append(
                _itemlist_candidate("itemlist_position_invalid", base, item_index=index, observed_position=position)
            )
        else:
            positions.append((index, position))
        item_url = item.get("url")
        if not isinstance(item_url, str) or not _valid_http_url(item_url):
            findings.append(
                _itemlist_candidate(
                    "itemlist_summary_url_invalid",
                    base,
                    item_index=index,
                    observed_url=_safe_url(item_url) if isinstance(item_url, str) else None,
                )
            )
        else:
            urls.append((index, item_url))
            if not _same_domain_or_subdomain(item_url, str(row.get("url") or "")):
                findings.append(
                    _itemlist_candidate(
                        "itemlist_summary_url_off_domain", base, item_index=index, observed_url=_safe_url(item_url)
                    )
                )
    position_values = [position for _, position in positions]
    position_counts = Counter(position_values)
    if any(count > 1 for count in position_counts.values()):
        duplicate_positions = {value for value, count in position_counts.items() if count > 1}
        findings.append(
            _itemlist_candidate(
                "itemlist_positions_duplicate",
                base,
                item_indexes=[index for index, value in positions if value in duplicate_positions],
                observed_positions=position_values,
            )
        )
    misplaced_indexes = [index for index, value in positions if value != index + 1]
    if misplaced_indexes:
        findings.append(
            _itemlist_candidate(
                "itemlist_positions_noncontiguous",
                base,
                item_indexes=misplaced_indexes,
                observed_positions=position_values,
                expected_positions=list(range(1, len(values) + 1)),
            )
        )
    url_values = [value for _, value in urls]
    url_counts = Counter(url_values)
    if any(count > 1 for count in url_counts.values()):
        duplicate_urls = {value for value, count in url_counts.items() if count > 1}
        findings.append(
            _itemlist_candidate(
                "itemlist_summary_urls_duplicate",
                base,
                item_indexes=[index for index, value in urls if value in duplicate_urls],
                observed_urls=[_safe_url(value) for value in url_values],
            )
        )
    declared_count = parsed.get("numberOfItems")
    if isinstance(declared_count, int) and declared_count != len(values):
        findings.append(
            _itemlist_candidate(
                "itemlist_declared_count_mismatch", base, declared_count=declared_count, actual_count=len(values)
            )
        )
    return findings


def _itemlist_candidate(code: str, base: Mapping[str, object], **details: object) -> dict[str, object]:
    return {
        "record_type": "candidate",
        "candidate_type": code,
        **base,
        **details,
        "qualification": "deterministic_itemlist_structure_candidate_not_final_google_eligibility",
        "source": "https://developers.google.com/search/docs/appearance/structured-data/carousel",
        "rules_verified_on": GOOGLE_RULES_VERIFIED_ON,
    }


def _normal_type(value: str) -> str:
    return value.rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _types(value: Mapping[str, object]) -> set[str]:
    raw = value.get("@type", value.get("type", ""))
    values = raw if isinstance(raw, list) else [raw]
    return {_normal_type(str(item)) for item in values if item}


def _parse_object(value: object) -> dict[str, object] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    return dict(value) if isinstance(value, Mapping) else None


def _has_path(value: Mapping[str, object], path: str) -> bool:
    return _has_path_parts(value, path.split("."))


def _has_path_parts(value: object, parts: list[str]) -> bool:
    if isinstance(value, list):
        return any(_has_path_parts(item, parts) for item in value)
    if not parts:
        current = value
        if isinstance(current, str):
            return bool(current.strip())
        return current is not None and current != [] and current != {}
    if not isinstance(value, Mapping) or parts[0] not in value:
        return False
    current = value[parts[0]]
    if len(parts) > 1:
        return _has_path_parts(current, parts[1:])
    if isinstance(current, str):
        return bool(current.strip())
    return current is not None and current != [] and current != {}


def _valid_http_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _same_domain_or_subdomain(left: str, right: str) -> bool:
    left_host = (urlsplit(left).hostname or "").lower().rstrip(".")
    right_host = (urlsplit(right).hostname or "").lower().rstrip(".")
    return bool(
        left_host
        and right_host
        and (left_host == right_host or left_host.endswith("." + right_host) or right_host.endswith("." + left_host))
    )


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    return redact_url_without_digest(parts._replace(query="", fragment="").geturl())


def _safe_value(value: object) -> object:
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, Mapping):
        return {scrub_text(str(key)): _safe_value(item) for key, item in value.items()}
    return value
