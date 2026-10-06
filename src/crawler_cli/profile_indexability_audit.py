"""Pure, bounded facts for profile-dependent indexability questions.

The technical-audit runner deliberately does not guess a site's URL policy.
This module is the small policy layer between persisted crawl-page records and
the explicit declarations in a site profile.  It performs no I/O and does not
know about database rows: callers pass JSON-like saved-page records instead.

Supported saved-page fields are intentionally narrow and explicit:

``url`` (str), ``noindex`` (bool), ``status`` (int), ``indexable`` (bool),
``canonical`` (str), ``in_sitemap`` (bool), ``is_navigation_target`` (bool),
``word_count`` (int), ``empty_selector_matched`` (bool), ``template`` (str),
``is_profile_hub`` (bool), and ``inlink_percentile`` (number in 0..1).

The sitemap and navigation flags are optional *inputs*, not false by default.
Their absence is recorded as incomplete evidence so a caller cannot turn an
unknown policy condition into a healthy result.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit


QuestionId = Literal["Q20", "Q36", "Q37", "Q78"]
FactOutcome = Literal["finding", "observed", "unavailable"]


@dataclass(frozen=True)
class ProfileIndexabilityFact:
    """A traceable observation for one saved page and one question."""

    question_id: QuestionId
    url: str
    outcome: FactOutcome
    rule: str
    values: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-ready representation for an audit evidence tab."""

        return {
            "question_id": self.question_id,
            "url": self.url,
            "outcome": self.outcome,
            "rule": self.rule,
            **self.values,
        }


@dataclass(frozen=True)
class ProfileIndexabilityCheck:
    """Facts and coverage state for a single profile-driven question.

    ``available`` says whether the necessary policy exists in the site profile;
    ``complete`` says whether all fields needed to rule out an issue were
    supplied for the relevant saved pages.  They are separate intentionally:
    an audit UI can show retained crawl observations while still returning
    Pending when profile policy is absent.
    """

    question_id: QuestionId
    available: bool
    complete: bool
    denominator: int
    facts: tuple[ProfileIndexabilityFact, ...]
    unavailable_reasons: tuple[str, ...] = ()
    facts_truncated: bool = False

    @property
    def affected(self) -> tuple[ProfileIndexabilityFact, ...]:
        return tuple(fact for fact in self.facts if fact.outcome == "finding")


@dataclass(frozen=True)
class ProfileIndexabilityAudit:
    """The bounded output of :func:`analyse_profile_indexability`."""

    q20: ProfileIndexabilityCheck
    q36: ProfileIndexabilityCheck
    q37: ProfileIndexabilityCheck
    q78: ProfileIndexabilityCheck

    def by_question(self) -> dict[QuestionId, ProfileIndexabilityCheck]:
        return {"Q20": self.q20, "Q36": self.q36, "Q37": self.q37, "Q78": self.q78}


def analyse_profile_indexability(
    pages: Sequence[Mapping[str, object]],
    site_profile: Mapping[str, object] | None,
    *,
    max_facts: int = 500,
) -> ProfileIndexabilityAudit:
    """Evaluate Q20/Q36/Q37/Q78 using only supplied page and policy facts.

    Output ordering follows ``pages`` and each question retains at most
    ``max_facts`` observations.  If that cap is reached, ``complete`` is false
    and ``facts_truncated`` is true; consumers must not report a clean result.
    """

    if max_facts < 1:
        raise ValueError("max_facts must be at least 1")
    saved_pages = tuple(page for page in pages if isinstance(page, Mapping))
    invalid_records = len(saved_pages) != len(pages)
    templates = _templates(site_profile)

    q20_available = templates is not None
    q36_spec = _template(templates, "profile_subtab")
    q37_profile_spec = _template(templates, "profile")
    empty_rule = _mapping_value(site_profile, "empty_profile_rule")
    q78_spec = _template(templates, "taxonomy")

    q20 = _q20(saved_pages, templates, q20_available, max_facts)
    q36 = _q36(saved_pages, q36_spec, max_facts)
    q37 = _q37(saved_pages, q37_profile_spec, empty_rule, max_facts)
    q78 = _q78(saved_pages, q78_spec, max_facts)
    if invalid_records:
        q20 = _with_reason(q20, "invalid_saved_page_record")
        q36 = _with_reason(q36, "invalid_saved_page_record")
        q37 = _with_reason(q37, "invalid_saved_page_record")
        q78 = _with_reason(q78, "invalid_saved_page_record")
    return ProfileIndexabilityAudit(q20=q20, q36=q36, q37=q37, q78=q78)


def _q20(
    pages: Sequence[Mapping[str, object]], templates: Mapping[str, object] | None, available: bool, max_facts: int
) -> ProfileIndexabilityCheck:
    facts: list[ProfileIndexabilityFact] = []
    reasons: set[str] = set()
    truncated = False
    if templates is None:
        reasons.add("missing_profile_templates")
    for page in pages:
        url = _url(page)
        if url is None:
            reasons.add("missing_url")
            continue
        noindex = _bool(page, "noindex")
        if noindex is None:
            reasons.add("missing_noindex")
            continue
        if not noindex:
            continue
        template = _matching_template(page, templates)
        template_indexable = _template_indexable(templates, template)
        in_sitemap = _bool(page, "in_sitemap")
        in_navigation = _bool(page, "is_navigation_target")
        if in_sitemap is None:
            reasons.add("missing_in_sitemap_flag")
        if in_navigation is None:
            reasons.add("missing_navigation_target_flag")
        finding = template_indexable is True or in_sitemap is True or in_navigation is True
        truncated = (
            _append(
                facts,
                ProfileIndexabilityFact(
                    "Q20",
                    url,
                    "finding" if finding else "observed",
                    "noindex page matches an indexable template, sitemap, or navigation target",
                    {
                        "noindex": True,
                        "template": template,
                        "template_indexable": template_indexable,
                        "in_sitemap": in_sitemap,
                        "is_navigation_target": in_navigation,
                    },
                ),
                max_facts,
            )
            or truncated
        )
    return _check("Q20", available, not reasons, len(pages), facts, reasons, truncated)


def _q36(pages: Sequence[Mapping[str, object]], spec: object | None, max_facts: int) -> ProfileIndexabilityCheck:
    facts: list[ProfileIndexabilityFact] = []
    reasons: set[str] = set()
    truncated = False
    matched = 0
    if spec is None:
        return _unavailable("Q36", len(pages), "missing_profile_template:profile_subtab")
    for page in pages:
        if not _matches_template(page, "profile_subtab", spec):
            continue
        matched += 1
        url = _url(page)
        if url is None:
            reasons.add("missing_url")
            continue
        status = _int(page, "status")
        indexable = _bool(page, "indexable")
        canonical = _str(page, "canonical")
        if status is None:
            reasons.add("missing_status")
        if indexable is None:
            reasons.add("missing_indexable")
        if canonical is None:
            reasons.add("missing_canonical")
        self_canonical = _same_url(url, canonical) if canonical is not None else None
        finding = status == 200 and indexable is True and self_canonical is True
        truncated = (
            _append(
                facts,
                ProfileIndexabilityFact(
                    "Q36",
                    url,
                    "finding" if finding else "observed",
                    "profile sub-tab is 200, indexable, and self-canonical",
                    {
                        "status": status,
                        "indexable": indexable,
                        "canonical": canonical,
                        "self_canonical": self_canonical,
                    },
                ),
                max_facts,
            )
            or truncated
        )
    return _check("Q36", True, not reasons, matched, facts, reasons, truncated)


def _q37(
    pages: Sequence[Mapping[str, object]],
    profile_spec: object | None,
    empty_rule: Mapping[str, object] | None,
    max_facts: int,
) -> ProfileIndexabilityCheck:
    facts: list[ProfileIndexabilityFact] = []
    reasons: set[str] = set()
    truncated = False
    matched = 0
    if profile_spec is None:
        return _unavailable("Q37", len(pages), "missing_profile_template:profile")
    if empty_rule is None:
        return _unavailable("Q37", len(pages), "missing_profile_empty_rule")
    max_words = _int(empty_rule, "max_main_content_words")
    selector_configured = isinstance(empty_rule.get("empty_state_selector"), str)
    if max_words is None and not selector_configured:
        return _unavailable("Q37", len(pages), "invalid_profile_empty_rule")
    for page in pages:
        if not _matches_template(page, "profile", profile_spec):
            continue
        matched += 1
        url = _url(page)
        if url is None:
            reasons.add("missing_url")
            continue
        words = _int(page, "word_count")
        selector = _bool(page, "empty_selector_matched")
        empty: bool | None
        if selector is True or (max_words is not None and words is not None and words <= max_words):
            empty = True
        elif (not selector_configured or selector is False) and (
            max_words is None or (words is not None and words > max_words)
        ):
            empty = False
        else:
            empty = None
            reasons.add("missing_empty_profile_fact")
        if empty is not True:
            continue
        indexable = _bool(page, "indexable")
        in_sitemap = _bool(page, "in_sitemap")
        if indexable is None:
            reasons.add("missing_indexable")
        if in_sitemap is None:
            reasons.add("missing_in_sitemap_flag")
        finding = indexable is True or in_sitemap is True
        truncated = (
            _append(
                facts,
                ProfileIndexabilityFact(
                    "Q37",
                    url,
                    "finding" if finding else "observed",
                    "empty profile is indexable or listed in a sitemap",
                    {
                        "word_count": words,
                        "empty_selector_matched": selector,
                        "empty": True,
                        "indexable": indexable,
                        "in_sitemap": in_sitemap,
                    },
                ),
                max_facts,
            )
            or truncated
        )
    return _check("Q37", True, not reasons, matched, facts, reasons, truncated)


def _q78(pages: Sequence[Mapping[str, object]], spec: object | None, max_facts: int) -> ProfileIndexabilityCheck:
    facts: list[ProfileIndexabilityFact] = []
    reasons: set[str] = set()
    truncated = False
    matched = 0
    if spec is None:
        return _unavailable("Q78", len(pages), "missing_profile_template:taxonomy")
    for page in pages:
        if not _matches_template(page, "taxonomy", spec):
            continue
        matched += 1
        url = _url(page)
        if url is None:
            reasons.add("missing_url")
            continue
        noindex = _bool(page, "noindex")
        if noindex is None:
            reasons.add("missing_noindex")
            continue
        if not noindex:
            continue
        profile_hub = _bool(page, "is_profile_hub")
        percentile = _percentile(page.get("inlink_percentile"))
        if profile_hub is None and percentile is None:
            reasons.add("missing_taxonomy_hub_fact")
        if page.get("inlink_percentile") is not None and percentile is None:
            reasons.add("invalid_inlink_percentile")
        is_hub = profile_hub is True or (percentile is not None and percentile >= 0.9)
        truncated = (
            _append(
                facts,
                ProfileIndexabilityFact(
                    "Q78",
                    url,
                    "finding" if is_hub else "observed",
                    "noindex taxonomy archive is a profile hub or top-decile internal-link target",
                    {"noindex": True, "is_profile_hub": profile_hub, "inlink_percentile": percentile, "is_hub": is_hub},
                ),
                max_facts,
            )
            or truncated
        )
    return _check("Q78", True, not reasons, matched, facts, reasons, truncated)


def _templates(profile: Mapping[str, object] | None) -> Mapping[str, object] | None:
    return _mapping_value(profile, "templates")


def _template(templates: Mapping[str, object] | None, name: str) -> object | None:
    return templates.get(name) if templates is not None else None


def _mapping_value(source: Mapping[str, object] | None, key: str) -> Mapping[str, object] | None:
    if source is None:
        return None
    value = source.get(key)
    return value if isinstance(value, Mapping) else None


def _matching_template(page: Mapping[str, object], templates: Mapping[str, object] | None) -> str | None:
    if templates is None:
        return None
    explicit = _str(page, "template")
    if explicit in templates:
        return explicit
    for name, spec in templates.items():
        if _matches_template(page, str(name), spec):
            return str(name)
    return None


def _matches_template(page: Mapping[str, object], name: str, spec: object) -> bool:
    if _str(page, "template") == name:
        return True
    if not isinstance(spec, Mapping):
        return False
    pattern = spec.get("pattern")
    url = _url(page)
    if not isinstance(pattern, str) or url is None:
        return False
    parsed = urlsplit(url)
    path_and_query = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    try:
        return re.search(pattern, path_and_query) is not None
    except re.error:
        return False


def _template_indexable(templates: Mapping[str, object] | None, name: str | None) -> bool | None:
    if templates is None or name is None:
        return None
    spec = templates.get(name)
    return _bool(spec, "indexable") if isinstance(spec, Mapping) else None


def _url(page: Mapping[str, object]) -> str | None:
    return _str(page, "url")


def _str(source: Mapping[str, object], key: str) -> str | None:
    value = source.get(key)
    return value if isinstance(value, str) and value else None


def _bool(source: Mapping[str, object], key: str) -> bool | None:
    value = source.get(key)
    return value if isinstance(value, bool) else None


def _int(source: Mapping[str, object], key: str) -> int | None:
    value = source.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _percentile(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if 0 <= result <= 1 else None


def _same_url(left: str, right: str) -> bool:
    def without_fragment(value: str) -> str:
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))

    return without_fragment(left) == without_fragment(right)


def _append(facts: list[ProfileIndexabilityFact], fact: ProfileIndexabilityFact, max_facts: int) -> bool:
    if len(facts) < max_facts:
        facts.append(fact)
        return False
    return True


def _check(
    question_id: QuestionId,
    available: bool,
    complete: bool,
    denominator: int,
    facts: list[ProfileIndexabilityFact],
    reasons: set[str],
    truncated: bool,
) -> ProfileIndexabilityCheck:
    if truncated:
        reasons.add("facts_truncated")
    return ProfileIndexabilityCheck(
        question_id=question_id,
        available=available,
        complete=complete and not truncated,
        denominator=denominator,
        facts=tuple(facts),
        unavailable_reasons=tuple(sorted(reasons)),
        facts_truncated=truncated,
    )


def _unavailable(question_id: QuestionId, denominator: int, reason: str) -> ProfileIndexabilityCheck:
    return ProfileIndexabilityCheck(question_id, False, False, denominator, (), (reason,))


def _with_reason(check: ProfileIndexabilityCheck, reason: str) -> ProfileIndexabilityCheck:
    return ProfileIndexabilityCheck(
        question_id=check.question_id,
        available=check.available,
        complete=False,
        denominator=check.denominator,
        facts=check.facts,
        unavailable_reasons=tuple(sorted({*check.unavailable_reasons, reason})),
        facts_truncated=check.facts_truncated,
    )
