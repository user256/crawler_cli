"""Question registry for the Questions tab of the technical audit template.

Each question is phrased so that Yes means a problem, carries a deterministic
``issue_if`` rule, and names the contract checks and inputs that answer it.
The JSON file is the source of truth; the review document is rendered from it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .technical_audit import TECHNICAL_AUDIT_CHECK_CONTRACT, TECHNICAL_AUDIT_LEGACY_CHECK_ID_ALIASES
from .technical_audit_evidence import (
    Answerer,
    Evidence,
    Json,
    _int_or_none,
    _path_and_query,
    _profile_value,
    unit_label,
)
from .technical_audit_tickets import _placeholders, _render, _sample_urls, ticket_sheet_table
from .profile_indexability_audit import analyse_profile_indexability
from .crawl_depth_audit import analyse_priority_crawl_depth
from .performance_distribution import analyse_performance_distribution
from .empty_anchor_audit import evaluate_empty_anchors


QUESTION_STATUSES = ("Issue", "Healthy", "Needs validation", "Pending")
CLASSIFICATIONS = ("Error", "Issue", "Warning", "Improvement")
PRIORITIES = ("High", "Medium", "Low")
_REQUIRED_FIELDS = (
    "id",
    "theme",
    "area",
    "original_question",
    "question",
    "issue_if",
    "unit",
    "group",
    "requires",
    "checks",
    "why",
)
_TICKETLESS_GROUPS = frozenset({"external", "run-gate"})


class QuestionRegistryError(ValueError):
    """The question registry is inconsistent with the audit contract."""


def default_question_registry_path() -> Path:
    return Path(__file__).parents[2] / "templates" / "technical-audit-questions.json"


def default_site_profile_example_path() -> Path:
    return Path(__file__).parents[2] / "templates" / "site-profile.example.json"


def load_question_registry(path: str | Path | None = None) -> dict[str, object]:
    target = Path(path) if path else default_question_registry_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QuestionRegistryError(f"could not load question registry {target}: {exc}") from exc
    validate_question_registry(payload)
    return payload


def validate_question_registry(
    registry: Mapping[str, object], site_profile: Mapping[str, object] | None = None
) -> None:
    """Raise on any entry that the question runner could not evaluate faithfully."""

    questions = registry.get("questions")
    groups = registry.get("groups")
    vocabulary = registry.get("requires_vocabulary")
    if not isinstance(questions, list) or not isinstance(groups, Mapping) or not isinstance(vocabulary, Mapping):
        raise QuestionRegistryError("registry needs questions, groups and requires_vocabulary")
    contract_ids = {str(check["id"]) for check in TECHNICAL_AUDIT_CHECK_CONTRACT}
    errors: list[str] = []
    seen: set[str] = set()
    for entry in questions:
        if not isinstance(entry, Mapping):
            errors.append(f"non-object entry: {entry!r}")
            continue
        qid = str(entry.get("id"))
        missing = [field for field in _REQUIRED_FIELDS if not entry.get(field) and field != "checks"]
        if missing:
            errors.append(f"{qid}: missing {', '.join(missing)}")
        if qid in seen:
            errors.append(f"{qid}: duplicate id")
        seen.add(qid)
        group = entry.get("group")
        if group not in groups:
            errors.append(f"{qid}: unknown group {group!r}")
        for check in entry.get("checks") or []:
            if check not in contract_ids:
                errors.append(f"{qid}: unknown contract check {check!r}")
        if not entry.get("checks") and not entry.get("new_detector") and group not in {"external", "heuristic"}:
            errors.append(f"{qid}: needs a contract check or a new_detector")
        for requirement in entry.get("requires") or []:
            if requirement not in vocabulary:
                errors.append(f"{qid}: unknown requirement {requirement!r}")
        if entry.get("profile_keys") and "site-profile" not in (entry.get("requires") or []):
            errors.append(f"{qid}: profile_keys without the site-profile requirement")
        if group not in _TICKETLESS_GROUPS:
            if entry.get("classification") not in CLASSIFICATIONS:
                errors.append(f"{qid}: classification must be one of {CLASSIFICATIONS}")
            if entry.get("priority") not in PRIORITIES:
                errors.append(f"{qid}: priority must be one of {PRIORITIES}")
        if site_profile is not None:
            for key in entry.get("profile_keys") or []:
                if _profile_value(site_profile, str(key)) is None:
                    errors.append(f"{qid}: site profile lacks {key!r}")
    if errors:
        raise QuestionRegistryError("; ".join(errors))


def questions_markdown(registry: Mapping[str, object]) -> str:
    """Render the reviewer-facing document; regenerate it whenever the JSON changes."""

    questions = registry["questions"]
    groups = registry["groups"]
    assert isinstance(questions, list) and isinstance(groups, Mapping)
    lines = [
        "# Technical audit questions",
        "",
        "Generated from [`templates/technical-audit-questions.json`](../templates/technical-audit-questions.json); "
        "edit the JSON, not this file. Every question is phrased so that **Yes means a problem**; "
        "`Issue if` is the rule that makes the answer Yes.",
        "",
        "## Statuses",
        "",
    ]
    statuses = registry.get("statuses", {})
    assert isinstance(statuses, Mapping)
    lines += [f"- **{name}**: {text}" for name, text in statuses.items()]
    lines += ["", "## Groups", "", "| Group | Answerable | Ticket policy | Questions |", "|---|---|---|---|"]
    for name, policy in groups.items():
        assert isinstance(policy, Mapping)
        ids = ", ".join(str(q["id"]) for q in questions if q["group"] == name)
        lines.append(f"| {name} | {policy['answerable']} | {policy['ticket']} | {ids} |")
    theme = None
    for entry in questions:
        if entry["theme"] != theme:
            theme = entry["theme"]
            lines += ["", f"## {theme}"]
        lines += ["", f"### {entry['id']} · {entry['area']}", "", f"**{entry['question']}**", ""]
        lines.append(f"- Issue if: {entry['issue_if']}")
        lines.append(f"- Why it matters: {entry['why']}")
        ticket = f"{entry['classification']} / {entry['priority']}" if entry.get("classification") else "no ticket"
        lines.append(f"- Group: {entry['group']} · Ticket: {ticket} · Unit: {entry['unit']}")
        lines.append(f"- Needs: {', '.join(entry['requires'])}")
        if entry["id"] in ANSWERERS:
            lines.append(f"- Runner: answered today ({ANSWERERS[entry['id']].basis})")
        owners = [f"`{check}`" for check in entry["checks"]]
        if entry.get("new_detector"):
            owners.append(f"new detector `{entry['new_detector']}`")
        lines.append(f"- Evidence owners: {', '.join(owners) or 'outside crawler_cli'}")
        if entry.get("profile_keys"):
            lines.append(f"- Site profile keys: {', '.join(f'`{key}`' for key in entry['profile_keys'])}")
        if entry.get("sheet_answerable_was"):
            lines.append(f"- Sheet said answerable: {entry['sheet_answerable_was']} (changed)")
        if entry.get("note"):
            lines.append(f"- Note: {entry['note']}")
        lines.append(f"- Original: {entry['original_question']}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Runner: answer each registry question from one technical-audit JSON bundle.
#
# A question is answered only by an explicit answerer that knows exactly which
# evidence rows belong to it.  Contract checks often hold a narrower or wider
# population than the question asks about, so mapping a question to a check
# status would overstate or understate the answer.  Everything without an
# answerer is reported as Pending with the reason, never as Healthy.

MAX_DATA_TAB_ROWS = 50_000
QUESTION_SHEET_COLUMNS = (
    "Theme",
    "ID",
    "Area",
    "Question",
    "Answer",
    "Status",
    "Affected",
    "Tested",
    "Issue if",
    "Why it matters",
    "Basis / notes",
    "Evidence tab",
    "Ticket",
)
_TAB_UNSAFE = re.compile(r"[\[\]\*\?/\\:']")


def _check(audit: Json, identifier: str) -> Json | None:
    """Find a check by contract ID, accepting schema-v1 IDs in older saved audits."""
    for check in audit.get("checks", []) or []:
        if not isinstance(check, Mapping):
            continue
        check_id = str(check.get("id"))
        if identifier in {check_id, TECHNICAL_AUDIT_LEGACY_CHECK_ID_ALIASES.get(check_id)}:
            return check
    return None


# What each contract check's denominator counts.  Most count stored or parsed
# HTML pages; the rest are listed here.
_CHECK_DENOMINATOR_UNITS = {
    "nonhtml-search-assets": "documents",
    "locale-html-lang": "content signatures",
    "rendered-robots-links": "interaction captures",
    "supplied-search-evidence": "records",
}


def _check_denominator_unit(identifier: str) -> str:
    return _CHECK_DENOMINATOR_UNITS.get(identifier, "pages")


def _from_check(
    identifier: str,
    *,
    keep: Callable[[Json], bool] | None = None,
    scope_note: str = "",
    distinct_url: bool = False,
) -> Callable[[Json, Json, Json | None], Evidence]:
    def answer(audit: Json, _question: Json, _profile: object) -> Evidence:
        check = _check(audit, identifier)
        if check is None or check.get("status") == "unavailable":
            required = check.get("required_evidence") if check else None
            return Evidence(
                available=False, note=f"{identifier} not collected: {required or 'check missing from audit'}"
            )
        rows = [dict(row) for row in check.get("evidence", []) or [] if isinstance(row, Mapping)]
        if keep is not None:
            rows = [row for row in rows if keep(row)]
        if distinct_url:
            rows = _distinct_by_url(rows)
        return Evidence(
            rows=rows,
            denominator=_int_or_none(check.get("denominator")),
            scope_complete=not scope_note,
            coverage_complete=check.get("coverage_state") == "complete",
            qualification=str(check["qualification"]) if check.get("qualification") else None,
            note=scope_note,
            language_check=identifier,
            denominator_unit=_check_denominator_unit(identifier),
        )

    return answer


def _with_template(
    template: str,
    inner: Callable[[Json, Json, Json | None], Evidence],
) -> Callable[[Json, Json, Json | None], Evidence]:
    """Restrict an answer's rows to URLs whose path matches a site-profile template."""

    def answer(audit: Json, question: Json, profile: Json | None) -> Evidence:
        pattern = _profile_value(profile or {}, f"templates.{template}.pattern")
        if not isinstance(pattern, str):
            return Evidence(available=False, note=f"site profile lacks templates.{template}.pattern")
        evidence = inner(audit, question, profile)
        if not evidence.available:
            return evidence
        compiled = re.compile(pattern)
        rows = [row for row in evidence.rows if compiled.search(_path_and_query(_row_url(row)))]
        return Evidence(**{**evidence.__dict__, "rows": rows})

    return answer


def _heading_link(row: Json) -> bool:
    return bool(re.search(r"/h[23](?:\[\d+\])?(?:/|$)", str(row.get("xpath", "")), re.IGNORECASE))


def _heading_target_failure(row: Json) -> bool:
    """Q39 asks about non-200 or non-canonical targets; a noindex 200 target is out of scope."""
    issues = row.get("issues") or [row.get("issue")]
    return _heading_link(row) and any(
        issue in {"error_target", "redirect_target", "noncanonical_target"}
        for issue in issues  # type: ignore[union-attr]
    )


def _trailing_slash_redirect(row: Json) -> bool:
    if row.get("issue") != "redirect_target":
        return False
    target = str(row.get("target_url", ""))
    final = str(row.get("final_url", ""))
    if not target or not final:
        return False
    return target.rstrip("/") == final.rstrip("/") and target != final


def _excessive_outlinks(audit: Json, question: Json, profile: object) -> Evidence:
    limit = int(dict(question.get("threshold") or {}).get("max_unique_internal_outlinks", 300))
    evidence = _from_check("internal-authority")(audit, question, None)
    if not evidence.available:
        return evidence
    rows = [row for row in evidence.rows if (_int_or_none(row.get("unique_outlinks")) or 0) > limit]
    rows.sort(key=lambda row: -(_int_or_none(row.get("unique_outlinks")) or 0))
    return Evidence(**{**evidence.__dict__, "rows": rows, "qualification": None, "language_check": None})


def _check_kinds(identifier: str, *kinds: str) -> Callable[[Json, Json, Json | None], Evidence]:
    """Restrict a shared deterministic check to the named raw-HTML facts."""

    allowed = frozenset(kinds)
    return _from_check(identifier, keep=lambda row: str(row.get("kind", "")) in allowed, distinct_url=True)


def _duplicate_head_elements(audit: Json, question: Json, profile: Json | None) -> Evidence:
    metadata = _check_kinds(
        "metadata-basics", "duplicate-title", "duplicate-meta-description", "duplicate-meta-robots"
    )(audit, question, profile)
    canonical = _check_kinds("canonical-declarations", "duplicate-canonical")(audit, question, profile)
    if not metadata.available or not canonical.available:
        return Evidence(available=False, note="raw HTML metadata or canonical inventory was not collected")
    return Evidence(
        rows=_distinct_by_url([*metadata.rows, *canonical.rows]),
        denominator=metadata.denominator,
        coverage_complete=metadata.coverage_complete and canonical.coverage_complete,
        language_check="metadata-basics",
        denominator_unit=metadata.denominator_unit,
    )


def _indexable_page_count(audit: Json) -> int | None:
    """Indexable pages in the run, from the profile page facts; None when they were not collected."""
    pages, available = _question_input(audit, "profile-indexability-pages")
    if not available:
        return None
    return sum(1 for page in pages if page.get("indexable") is True)


def _within_indexable_pages(audit: Json, evidence: Evidence) -> Evidence:
    """Use the indexable-page count as the denominator, so an empty population cannot pass."""
    count = _indexable_page_count(audit)
    if not evidence.available or count is None:
        return evidence
    return Evidence(**{**evidence.__dict__, "denominator": count, "denominator_unit": "indexable pages"})


def _indexable_heading_issues(audit: Json, question: Json, profile: Json | None) -> Evidence:
    evidence = _from_check(
        "metadata-basics",
        keep=lambda row: (
            row.get("overall_indexable") is True
            and str(row.get("kind", "")) in {"missing-h1", "multiple-h1", "heading-level-skip"}
        ),
        distinct_url=True,
    )(audit, question, profile)
    return _within_indexable_pages(audit, evidence)


def _missing_indexable_canonical(audit: Json, question: Json, profile: Json | None) -> Evidence:
    evidence = _from_check(
        "canonical-declarations",
        keep=lambda row: (
            str(row.get("kind", "")) == "missing-canonical"
            and row.get("overall_indexable") is True
            and _int_or_none(row.get("final_status_code")) == 200
        ),
        distinct_url=True,
    )(audit, question, profile)
    return _within_indexable_pages(audit, evidence)


def _header_html_parity(audit: Json, question: Json, profile: Json | None) -> Evidence:
    """Robots header/meta conflicts plus Link-header/HTML canonical conflicts."""
    coverage = audit.get("source_coverage")
    if not isinstance(coverage, Mapping):
        return Evidence(available=False, note="audit has no source coverage")
    required = ("indexability", "stored-html")
    if any(
        not isinstance(coverage.get(name), Mapping) or coverage[name].get("available") is not True for name in required
    ):
        return Evidence(available=False, note="header/HTML parity needs both saved directives and raw HTML")
    robots = _from_check("indexability-segmentation")(audit, question, profile)
    canonical = _check_kinds("canonical-declarations", "html-header-canonical-mismatch")(audit, question, profile)
    if not robots.available or not canonical.available:
        return Evidence(available=False, note=robots.note or canonical.note)
    return Evidence(
        rows=[*robots.rows, *canonical.rows],
        denominator=robots.denominator,
        coverage_complete=robots.coverage_complete and canonical.coverage_complete,
        language_check="indexability-segmentation",
        denominator_unit=robots.denominator_unit,
    )


def _semantic_rows(audit: Json) -> tuple[list[dict[str, object]], bool]:
    coverage = audit.get("source_coverage")
    inputs = audit.get("question_inputs")
    available = (
        isinstance(coverage, Mapping)
        and isinstance(coverage.get("semantic-html"), Mapping)
        and coverage["semantic-html"].get("available") is True
    )
    rows = inputs.get("semantic-html") if isinstance(inputs, Mapping) else None
    return ([dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else [], available)


def _semantic_landmarks(audit: Json, question: Json, profile: Json | None) -> Evidence:
    rows, available = _semantic_rows(audit)
    eligible = [row for row in rows if row.get("landmark_eligible") is True]
    return Evidence(
        rows=[row for row in eligible if row.get("missing_required_landmarks") is True],
        denominator=len(eligible) if available else None,
        available=available,
        qualification="review_required",
        note="Rows are page-level source candidates; confirm their template grouping before raising a ticket.",
        language_check="semantic-html",
        denominator_unit="pages",
    )


def _semantic_toc(audit: Json, question: Json, profile: Json | None) -> Evidence:
    rows, available = _semantic_rows(audit)
    eligible = [row for row in rows if row.get("toc_eligible") is True]
    return Evidence(
        rows=[row for row in eligible if row.get("missing_h2_fragment_toc") is True],
        denominator=len(eligible) if available else None,
        available=available,
        language_check="semantic-html",
        denominator_unit="pages",
    )


def _profile_indexability(question_id: str) -> Callable[[Json, Json, Json | None], Evidence]:
    def answer(audit: Json, _question: Json, profile: Json | None) -> Evidence:
        coverage = audit.get("source_coverage")
        inputs = audit.get("question_inputs")
        available = (
            isinstance(coverage, Mapping)
            and isinstance(coverage.get("profile-indexability-pages"), Mapping)
            and coverage["profile-indexability-pages"].get("available") is True
        )
        pages = inputs.get("profile-indexability-pages") if isinstance(inputs, Mapping) else None
        if not available or not isinstance(pages, list):
            return Evidence(available=False, note="profile indexability page facts were not collected")
        if profile is None:
            return Evidence(available=False, note="site profile was not supplied")
        result = analyse_profile_indexability(
            [row for row in pages if isinstance(row, Mapping)], profile
        ).by_question()[question_id]  # type: ignore[index]
        if result.available and result.denominator == 0:
            return Evidence(available=False, note=f"no saved page matches the {question_id} profile template")
        return Evidence(
            rows=[fact.as_dict() for fact in result.affected],
            denominator=result.denominator,
            available=result.available,
            coverage_complete=result.complete,
            note="; ".join(result.unavailable_reasons),
            language_check="profile-indexability-pages",
            denominator_unit="pages",
        )

    return answer


def _semantic_figure_caption(audit: Json, question: Json, profile: Json | None) -> Evidence:
    """One row per in-content image without a figure/figcaption, named by its source."""
    rows, available = _semantic_rows(audit)
    eligible = [row for row in rows if row.get("main_image_eligible") is True]
    total_images = sum(_int_or_none(row.get("main_image_count")) or 0 for row in eligible)
    findings: list[dict[str, object]] = []
    unlisted = 0
    for row in eligible:
        missing = _int_or_none(row.get("main_images_without_figure_and_figcaption")) or 0
        listed = row.get("uncaptioned_main_image_srcs")
        srcs = [str(src) for src in listed] if isinstance(listed, (list, tuple)) else []
        findings.extend({"url": row.get("url"), "image_src": src} for src in srcs[:missing])
        unlisted += max(0, missing - len(srcs))
        findings.extend({"url": row.get("url"), "image_src": ""} for _ in range(max(0, missing - len(srcs))))
    note = "Counts in-content source images; confirm decorative-image intent before ticketing."
    if unlisted:
        note += f" {unlisted:,} images beyond the per-page listing limit are counted without a source."
    return Evidence(
        rows=findings,
        denominator=total_images if available else None,
        available=available,
        qualification="review_required",
        note=note,
        language_check="semantic-html",
        denominator_unit="images",
    )


def _question_input(audit: Json, name: str) -> tuple[list[dict[str, object]], bool]:
    coverage = audit.get("source_coverage")
    inputs = audit.get("question_inputs")
    available = (
        isinstance(coverage, Mapping)
        and isinstance(coverage.get(name), Mapping)
        and coverage[name].get("available") is True
    )
    rows = inputs.get(name) if isinstance(inputs, Mapping) else None
    return ([dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else [], available)


def _is_homepage(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.path in {"", "/"} and not parsed.query


def _threshold(question: Json) -> Mapping[str, object]:
    threshold = question.get("threshold")
    return threshold if isinstance(threshold, Mapping) else {}


def _crawl_depth(audit: Json, question: Json, profile: Json | None) -> Evidence:
    pages, available = _question_input(audit, "crawl-depth-pages")
    if not available or profile is None:
        return Evidence(available=False, note="crawl depth needs saved graph evidence and a site profile")
    raw_context = audit.get("run_context")
    context = raw_context if isinstance(raw_context, Mapping) else {}
    roots = [str(row["url"]) for row in pages if _int_or_none(row.get("crawl_depth")) == 0 and row.get("url")]
    # Frontier depth is first-discovery depth. It is click depth from the
    # homepage only when no URL entered the frontier from a sitemap (those are
    # enqueued at depth 0) and every depth-0 URL is a homepage.
    sitemap_sources = _int_or_none(context.get("run_sitemap_source_count"))
    homepage_roots = bool(roots) and all(_is_homepage(root) for root in roots)
    notes: list[str] = []
    if sitemap_sources is None:
        notes.append("The run context has no sitemap-sourced URL count, so saved depths are not verified click depths.")
    elif sitemap_sources:
        notes.append(
            f"{sitemap_sources:,} URLs entered the frontier from sitemaps at depth 0, "
            "so saved depths are first-discovery depths, not click depths from the homepage."
        )
    if roots and not homepage_roots:
        other = sum(1 for root in roots if not _is_homepage(root))
        notes.append(f"{other:,} depth-0 URLs are not homepages, so depths are not measured from a declared root.")
    graph = {
        "root_urls": roots,
        "depths_from_roots": sitemap_sources == 0 and homepage_roots,
        "coverage_complete": context.get("completion_state") == "complete",
    }
    max_depth = _int_or_none(_threshold(question).get("max_depth"))
    result = analyse_priority_crawl_depth(pages, graph, profile, max_depth=3 if max_depth is None else max_depth)
    return Evidence(
        rows=[fact.as_dict() for fact in result.affected],
        denominator=result.denominator,
        available=result.available and result.eligible,
        coverage_complete=result.complete,
        note="; ".join([*notes, *result.unavailable_reasons]),
        language_check="crawl-depth-pages",
        denominator_unit="priority pages",
    )


def _performance_distribution(audit: Json, question: Json, profile: Json | None) -> Evidence:
    pages, available = _question_input(audit, "performance-pages")
    templates = _profile_value(profile or {}, "templates")
    if not available or not isinstance(templates, Mapping):
        return Evidence(
            available=False, note="performance distribution needs saved timings and site-profile template patterns"
        )
    patterns = [
        (str(name), spec["pattern"])
        for name, spec in templates.items()
        if isinstance(spec, Mapping) and isinstance(spec.get("pattern"), str)
    ]
    classified = []
    for page in pages:
        value = dict(page)
        path = _path_and_query(str(value.get("url", "")))
        # Pages matching no profile template are still timed pages; group them as "other".
        value["template"] = next((name for name, pattern in patterns if re.search(pattern, path)), "other")
        classified.append(value)
    threshold = _threshold(question)
    options: dict[str, float | int] = {}
    for key, option in (("p90_ms", "p90_threshold_ms"), ("p99_ms", "p99_threshold_ms")):
        if isinstance(threshold.get(key), (int, float)) and not isinstance(threshold.get(key), bool):
            options[option] = float(threshold[key])  # type: ignore[arg-type]
    min_samples = _int_or_none(threshold.get("min_samples"))
    if min_samples is not None:
        options["min_samples"] = min_samples
    result = analyse_performance_distribution(classified, **options)  # type: ignore[arg-type]
    return Evidence(
        rows=[fact.as_dict() for fact in result.affected],
        denominator=result.eligible_record_count,
        available=result.available,
        coverage_complete=result.complete,
        note="; ".join(result.unavailable_reasons),
        language_check="performance-pages",
        denominator_unit="timed pages",
    )


def _empty_anchors(audit: Json, question: Json, profile: Json | None) -> Evidence:
    pages, available = _question_input(audit, "empty-anchor-links")
    if not available:
        return Evidence(available=False, note="saved empty-anchor link facts were not collected")
    if not pages:
        return Evidence(available=False, note="no stored HTML page carried internal link facts")
    links: list[dict[str, object]] = []
    total = 0
    truncated = False
    for page in pages:
        if "empty_anchors" not in page:
            # Link-level rows (one per internal anchor).
            links.append(page)
            total += 1
            continue
        total += _int_or_none(page.get("internal_anchor_count")) or 0
        truncated = truncated or page.get("empty_anchors_truncated") is True
        anchors = page.get("empty_anchors")
        for anchor in anchors if isinstance(anchors, list) else []:
            if isinstance(anchor, Mapping):
                links.append({"source_url": page.get("source_url"), **anchor})
    result = evaluate_empty_anchors(links)
    raw_context = audit.get("run_context")
    context = raw_context if isinstance(raw_context, Mapping) else {}
    stored = _int_or_none(context.get("stored_html_count"))
    all_pages_seen = stored is None or len(pages) >= stored
    notes = [
        f"unknown image-alt facts: {result.coverage.unknown_image_alt_count}; "
        f"invalid link facts: {result.coverage.invalid_record_count}"
    ]
    if truncated:
        notes.append("some pages listed more text-less anchors than the per-page cap, so counts are a lower bound")
    if not all_pages_seen:
        notes.append(f"{len(pages):,} of {stored:,} stored pages carried link facts")
    return Evidence(
        rows=[finding.as_dict() for finding in result.findings],
        denominator=total,
        available=True,
        coverage_complete=(
            result.coverage.complete
            and not truncated
            and all_pages_seen
            and context.get("completion_state") == "complete"
        ),
        note="; ".join(notes),
        language_check="empty-anchor-links",
        denominator_unit="links",
    )


def _run_gate(audit: Json, question: Json, profile: object) -> Evidence:
    context = audit.get("run_context")
    if not isinstance(context, Mapping) or not context:
        return Evidence(available=False, note="audit has no run_context")
    limit = float(dict(question.get("threshold") or {}).get("max_failure_share", 0.02))
    html = _int_or_none(context.get("html_count")) or 0
    failures: list[dict[str, object]] = []

    def fail(condition: str, observed: object, expected: object) -> None:
        failures.append({"condition": condition, "observed": observed, "expected": expected})

    if context.get("completion_state") != "complete":
        fail("run completion state", context.get("completion_state"), "complete")
    if context.get("snapshot_consistency") == "changed_during_collection":
        fail("run changed while the audit read it", "changed_during_collection", "stable")
    pending = _int_or_none(context.get("frontier_pending")) or 0
    if pending:
        fail("frontier URLs still pending", pending, 0)
    for key, label in (
        ("unparsed_html_count", "HTML responses not parsed"),
        ("challenged_count", "bot-challenge responses"),
    ):
        count = _int_or_none(context.get(key))
        if count and html and count / html > limit:
            fail(label, f"{count:,} of {html:,}", f"<= {limit:.0%}")
    return Evidence(rows=failures, denominator=1, denominator_unit="runs")


_MIN_DRIFT_SAMPLES = 20


def _rate_limit_gate(audit: Json, question: Json, profile: object) -> Evidence:
    """Q81: 429/503 responses, or median TTFB rising over 50% between the first and last tenth of the run."""
    context = audit.get("run_context")
    if not isinstance(context, Mapping) or not context:
        return Evidence(available=False, note="audit has no run_context")
    rate_limited = _int_or_none(context.get("rate_limited_count"))
    if rate_limited is None:
        return Evidence(available=False, note="audit has no saved 429/503 response count; regenerate the audit")
    rows: list[dict[str, object]] = []
    if rate_limited:
        rows.append({"condition": "429/503 responses", "observed": rate_limited, "expected": 0})
    samples = _int_or_none(context.get("ttfb_sample_count")) or 0
    early = context.get("ttfb_early_median_ms")
    late = context.get("ttfb_late_median_ms")
    note = ""
    drift_tested = samples >= _MIN_DRIFT_SAMPLES and isinstance(early, (int, float)) and isinstance(late, (int, float))
    if drift_tested:
        assert isinstance(early, (int, float)) and isinstance(late, (int, float))
        if early > 0 and late > early * 1.5:
            rows.append(
                {
                    "condition": "median TTFB rose over 50% during the run",
                    "observed": f"{early:,.0f} ms -> {late:,.0f} ms",
                    "expected": f"<= {early * 1.5:,.0f} ms",
                }
            )
    else:
        note = f"Response-time drift not tested: {samples:,} timed fetches (needs {_MIN_DRIFT_SAMPLES})."
    return Evidence(
        rows=rows,
        denominator=1,
        scope_complete=drift_tested,
        coverage_complete=context.get("completion_state") == "complete",
        note=note,
        denominator_unit="runs",
    )


ANSWERERS: dict[str, Answerer] = {
    "Q8": Answerer(
        "metadata-basics html lang markup rows",
        _check_kinds("metadata-basics", "missing-html-lang", "invalid-html-lang", "html-lang-self-hreflang-mismatch"),
    ),
    "Q10": Answerer("raw HTML duplicate head elements", _duplicate_head_elements),
    "Q11": Answerer("metadata-duplicates-aliases clusters", _from_check("metadata-duplicates-aliases")),
    "Q12": Answerer(
        "metadata-basics head-only elements inside body",
        _check_kinds("metadata-basics", "head-only-element-in-body"),
    ),
    "Q15": Answerer(
        "metadata-basics H1 and heading-sequence rows",
        _indexable_heading_issues,
    ),
    "Q13": Answerer("orphan-candidates rows", _from_check("orphan-candidates")),
    "Q14": Answerer("internal-authority unique_outlinks above threshold", _excessive_outlinks),
    "Q16": Answerer("schema-parser-diagnostics rows", _from_check("schema-parser-diagnostics")),
    "Q21": Answerer(
        "near-duplicate-content rows on the inventory template",
        _with_template(
            "inventory",
            _from_check(
                "near-duplicate-content",
                scope_note="Near-duplicates only; the thin-content word-count test is not implemented yet.",
                distinct_url=True,
            ),
        ),
    ),
    "Q22": Answerer(
        "internal-link-targets error, redirect, noindex and canonical-target rows",
        _from_check("internal-link-targets"),
    ),
    "Q23": Answerer("supplied pre/post-interaction inventory capture", _from_check("rendered-robots-links")),
    "Q26": Answerer("run_context completeness gate", _run_gate),
    "Q81": Answerer("run_context 429/503 rate-limit count", _rate_limit_gate),
    "Q82": Answerer(
        "discovery-source-provenance sitemap/internal-link rows", _from_check("discovery-source-provenance")
    ),
    "Q30": Answerer("supplied Search Console / URL Inspection records", _from_check("supplied-search-evidence")),
    "Q32": Answerer("locale-html-lang shared-signature rows", _from_check("locale-html-lang")),
    "Q39": Answerer(
        "internal-link-targets error, redirect and non-canonical targets linked from an H2/H3",
        _from_check("internal-link-targets", keep=_heading_target_failure),
    ),
    "Q41": Answerer(
        "hreflang-html-http locale-folder mismatches",
        _check_kinds("hreflang-html-http", "locale-path-language-mismatch"),
    ),
    "Q42": Answerer("soft404-error-routes saved-source candidates", _from_check("soft404-error-routes")),
    "Q44": Answerer("crawl-depth-pages priority depth facts", _crawl_depth),
    "Q72": Answerer(
        "internal-link-targets trailing-slash redirect rows",
        _from_check("internal-link-targets", keep=_trailing_slash_redirect),
    ),
    "Q51": Answerer("semantic-html landmark facts", _semantic_landmarks),
    "Q54": Answerer("semantic-html figure and figcaption facts", _semantic_figure_caption),
    "Q58": Answerer("semantic-html long-page H2 fragment facts", _semantic_toc),
    "Q88": Answerer("performance-pages template p90/p99 facts", _performance_distribution),
    "Q91": Answerer("empty-anchor-links saved HTML facts", _empty_anchors),
    "Q20": Answerer("profile-indexability policy facts", _profile_indexability("Q20")),
    "Q36": Answerer("profile-indexability policy facts", _profile_indexability("Q36")),
    "Q37": Answerer("profile-indexability policy facts", _profile_indexability("Q37")),
    "Q78": Answerer("profile-indexability policy facts", _profile_indexability("Q78")),
    "Q71": Answerer("canonical-declarations missing indexable canonical rows", _missing_indexable_canonical),
    "Q73": Answerer("canonical-target-validation homepage canonical rows", _from_check("canonical-target-validation")),
    "Q80": Answerer(
        "canonical-declarations relative canonical rows", _check_kinds("canonical-declarations", "relative-canonical")
    ),
    "Q87": Answerer("nonhtml-search-assets header inventory", _from_check("nonhtml-search-assets")),
    "Q94": Answerer(
        "indexability-segmentation header/HTML canonical and robots conflicts",
        _header_html_parity,
    ),
}


def answer_questions(
    audit: Json,
    registry: Json,
    site_profile: Json | None = None,
) -> list[dict[str, object]]:
    """Return one answer per registry question, in registry order."""

    questions = [entry for entry in registry["questions"] if isinstance(entry, Mapping)]
    by_id = {str(entry["id"]): entry for entry in questions}
    gates = {qid: _answer_one(by_id[qid], audit, site_profile, gate_ok=True) for qid in ("Q26", "Q81") if qid in by_id}
    # A gate downgrades the other answers only when it answers Yes. A gate that
    # could not be fully tested records its own scope gap and stays below Healthy.
    gate_ok = bool(gates) and not any(gate["answer"] == "Yes" for gate in gates.values())
    gate_notes = [
        f"Run gate {qid} is {gate['status']} rather than Healthy; its scope gap is recorded on {qid} "
        "and does not downgrade this answer."
        for qid, gate in gates.items()
        if gate["answer"] != "Yes" and gate["status"] != "Healthy"
    ]
    answers = []
    for entry in questions:
        qid = str(entry["id"])
        if qid in gates:
            answers.append(gates[qid])  # type: ignore[index]
        else:
            answers.append(_answer_one(entry, audit, site_profile, gate_ok=gate_ok, gate_notes=gate_notes))
    return answers


def _answer_one(
    entry: Json,
    audit: Json,
    profile: Json | None,
    *,
    gate_ok: bool,
    gate_notes: Sequence[str] = (),
) -> dict[str, object]:
    qid = str(entry["id"])
    group = str(entry["group"])
    notes: list[str] = []
    answer: dict[str, Any] = {
        "id": qid,
        "group": group,
        "status": "Pending",
        "answer": "",
        "affected_count": None,
        "denominator": None,
        "denominator_unit": None,
        "notes": notes,
        "rows": [],
        "ticket": False,
        "language_check": None,
        "qualification": None,
    }
    if group == "external":
        notes.append("Outside crawler_cli: " + ", ".join(str(item) for item in entry["requires"]))
        return answer
    answerer = ANSWERERS.get(qid)
    if answerer is None:
        owners = [*entry.get("checks", []), *([entry["new_detector"]] if entry.get("new_detector") else [])]
        notes.append("Not answered by the runner yet; needs " + ", ".join(str(item) for item in owners))
        return answer
    evidence = answerer.answer(audit, entry, profile)
    notes.append(f"Basis: {answerer.basis}.")
    notes.extend(gate_notes)
    if evidence.note:
        notes.append(evidence.note)
    if not evidence.available:
        return answer
    rows = evidence.rows
    affected = len(rows)
    answer.update(
        affected_count=affected,
        denominator=evidence.denominator,
        # Fall back to "items" rather than assume the denominator counts the finding unit.
        denominator_unit=evidence.denominator_unit or answerer.denominator_unit or "items",
        rows=rows,
        language_check=evidence.language_check,
        qualification=evidence.qualification,
    )
    if not rows and evidence.denominator == 0:
        # An empty tested population is not evidence that the rule passed.
        notes.append("No items in the tested population, so the rule could not be tested.")
        answer.update(affected_count=None, denominator=None, denominator_unit=None, rows=[])
        return answer
    matched = _meets_threshold(affected, evidence.denominator, entry.get("threshold"))
    if matched is None:
        notes.append("Share threshold needs a population size the evidence does not give.")
    complete = evidence.coverage_complete and (gate_ok or group == "run-gate")
    if not complete:
        notes.append("Coverage is incomplete for this run, so counts are a lower bound.")
    if matched:
        answer["answer"] = "Yes"
        review = group == "heuristic" or evidence.qualification in {"review_required", "coverage_required"}
        if review:
            answer["status"] = "Needs validation"
            notes.append("Candidates for review, not confirmed defects; confirm before raising a ticket.")
        elif not complete:
            answer["status"] = "Needs validation"
            answer["ticket"] = group != "run-gate"
        else:
            answer["status"] = "Issue"
            answer["ticket"] = group != "run-gate"
        if evidence.qualification == "recheck_required":
            notes.append("Statuses come from the saved crawl; recheck the sample live before assigning.")
    elif matched is None:
        answer["status"] = "Needs validation"
    else:
        if affected:
            notes.append(f"{affected:,} rows found, below the reporting threshold.")
        if complete and evidence.scope_complete:
            answer.update(status="Healthy", answer="No")
        else:
            answer["status"] = "Needs validation"
            answer["answer"] = "No (partial)"
    return answer


def _meets_threshold(affected: int, denominator: int | None, threshold: object) -> bool | None:
    rule = dict(threshold) if isinstance(threshold, Mapping) else {}
    if affected < int(rule.get("min_affected", 1)):
        return False
    share = rule.get("min_share")
    if share is None:
        return True
    if not denominator:
        return None
    return affected / denominator >= float(share)


def question_ticket_rows(
    audit: Json,
    registry: Json,
    answers: Sequence[Json],
    language: Json | None = None,
) -> list[dict[str, str]]:
    """Draft one Tickets row per answer flagged for a ticket.

    Suggested solution and acceptance criteria come from the ticket-language
    entry of the check that supplied the rows, when there is one.  The draft is
    meant for the tech-audit-tickets skill to finish in house style.
    """

    entries = {str(entry["id"]): entry for entry in registry["questions"]}
    language_checks = (language or {}).get("checks", {})
    rows: list[dict[str, str]] = []
    for answer in answers:
        if not answer.get("ticket"):
            continue
        entry = entries[str(answer["id"])]
        evidence = answer.get("rows") or []
        tab = data_tab_name(entry)
        affected = int(answer.get("affected_count") or 0)
        pseudo_check = {
            "id": answer.get("language_check") or answer["id"],
            "affected_count": affected,
            "denominator": answer.get("denominator"),
            "tested_count": answer.get("denominator"),
            "detail_sheet": tab,
            "qualification": answer.get("qualification"),
        }
        values = _placeholders(audit, pseudo_check, evidence)
        values["unit"] = str(entry["unit"])
        denominator_unit = _denominator_unit(answer)
        values["denominator_unit"] = denominator_unit
        source = language_checks.get(answer.get("language_check")) if isinstance(language_checks, Mapping) else None
        source = source if isinstance(source, Mapping) else {}
        classification, priority = _ticket_grade(entry)
        count = unit_label(affected, str(entry["unit"]))
        tested = ""
        if answer.get("denominator"):
            # The denominator counts its own population (pages, hosts, policies...),
            # which need not be the question's finding unit; a share needs both to match.
            same_unit = denominator_unit.casefold() == str(entry["unit"]).casefold()
            share = f" ({values['affected_pct']})" if same_unit and values["affected_pct"] else ""
            tested = f", across {unit_label(int(answer['denominator']), denominator_unit)} tested{share}"
        description = "\n\n".join(
            part
            for part in (
                f"{entry['question']} Yes: {count}{tested} in run {values['run_id']}.",
                f"Rule: {entry['issue_if']}",
                str(entry["why"]),
                f"See the {tab} tab for every row."
                + (f"\n\nExamples:\n{values['sample_urls']}" if values["sample_urls"] else ""),
            )
            if part
        )
        notes = "\n\n".join(
            part
            for part in (
                f"Question {entry['id']} ({entry['theme']} / {entry['area']}).",
                str(entry.get("note") or ""),
                *(str(note) for note in answer.get("notes", []) or []),
            )
            if part
        )
        rows.append(
            {
                "question_id": str(entry["id"]),
                "Label": f"{entry['id']} {entry['area']}: {count}",
                "Description": description,
                "Suggested Solution": _render(source.get("suggested_solution", ""), values),
                "Acceptance Criteria": _render(source.get("acceptance_criteria", ""), values)
                or f"The next crawl answers {entry['id']} with No: {entry['issue_if']}",
                "Ticket Classification": classification,
                "Priority": priority,
                "How to Replicate": (
                    f"Run `crawler-cli technical-audit --crawl-run-id {values['run_id']}` then "
                    f"`crawler-cli technical-audit-questions`, and open the {tab} tab."
                ),
                "Notes / Documentation": notes,
            }
        )
    return rows


def _denominator_unit(answer: Json) -> str:
    return str(answer.get("denominator_unit") or "items")


def _tested_summary(answer: Json) -> str:
    """Tested population with its unit, for the Questions tab notes."""
    denominator = _int_or_none(answer.get("denominator"))
    if denominator is None:
        return ""
    return f"Tested: {unit_label(denominator, _denominator_unit(answer))}."


def _ticket_grade(entry: Json) -> tuple[str, str]:
    classification = str(entry.get("classification") or "Issue")
    priority = str(entry.get("priority") or "Medium")
    if entry.get("group") == "best-practice":
        if classification in {"Error", "Issue"}:
            classification = "Warning"
        if priority == "High":
            priority = "Medium"
    return classification, priority


def data_tab_name(entry: Json) -> str:
    return _TAB_UNSAFE.sub(" ", f"{entry['id']} {entry['area']}")[:50].strip()


def questions_sheet_tables(
    audit: Json,
    registry: Json,
    answers: Sequence[Json],
    tickets: Sequence[Mapping[str, str]],
) -> dict[str, list[list[object]]]:
    """Questions tab with answers, the Tickets tab, and one data tab per Yes answer."""

    entries = {str(entry["id"]): entry for entry in registry["questions"]}
    ticket_numbers: dict[str, int] = {}
    for number, ticket in enumerate(tickets, start=1):
        ticket_numbers[str(ticket["question_id"])] = number
    question_rows: list[list[object]] = [list(QUESTION_SHEET_COLUMNS)]
    data_tabs: dict[str, list[list[object]]] = {}
    for answer in answers:
        entry = entries[str(answer["id"])]
        rows = answer.get("rows") or []
        tab = ""
        if rows and answer.get("answer") == "Yes":
            tab = data_tab_name(entry)
            data_tabs[tab] = _data_table(rows)
        denominator = answer.get("denominator")
        question_rows.append(
            [
                entry["theme"],
                entry["id"],
                entry["area"],
                entry["question"],
                answer.get("answer", ""),
                answer["status"],
                "" if answer.get("affected_count") is None else answer["affected_count"],
                "" if denominator is None else denominator,
                entry["issue_if"],
                entry["why"],
                " ".join(
                    part
                    for part in (_tested_summary(answer), *(str(note) for note in answer.get("notes", []) or []))
                    if part
                ),
                tab,
                ticket_numbers.get(str(entry["id"]), ""),
            ]
        )
    return {"Questions": question_rows, "Tickets": ticket_sheet_table(list(tickets)), **data_tabs}


def _data_table(rows: Sequence[Json]) -> list[list[object]]:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(str(key))
    table: list[list[object]] = [list(columns)]
    for row in rows[:MAX_DATA_TAB_ROWS]:
        table.append([_cell(row.get(column)) for column in columns])
    if len(rows) > MAX_DATA_TAB_ROWS:
        table.append([f"Truncated: {len(rows) - MAX_DATA_TAB_ROWS:,} more rows are in the answers JSON."])
    return table


def _cell(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return "" if value is None else value
    return json.dumps(value, sort_keys=True, default=str)


def _distinct_by_url(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    kept = []
    for row in rows:
        url = _row_url(row)
        if url not in seen:
            seen.add(url)
            kept.append(row)
    return kept


def _row_url(row: Json) -> str:
    samples = _sample_urls([row])
    return samples[0] if samples else ""


# Stream C answerers read run-scoped observation bundles; they live in their own
# module, built on technical_audit_evidence, so they are registered last.
from .technical_audit_observed_answers import OBSERVED_ANSWERERS  # noqa: E402

ANSWERERS.update({qid: answerer for qid, answerer in OBSERVED_ANSWERERS.items() if qid not in ANSWERERS})
