"""Shared answer model for the technical-audit question runner.

The question runner (``technical_audit_questions``) and the observed-evidence
answerers (``technical_audit_observed_answers``) both build on these types and
helpers.  They live in this leaf module so that either side imports cleanly on
its own; the runner registers the observed answerers after both are loaded.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


# Registry entries, audits and answers are JSON documents.
Json = Mapping[str, Any]

# A link inside an H2 or H3 heading, matched against its saved XPath.  The
# pattern is valid both as a Python ``re`` and as a PostgreSQL ``~*`` regex, so
# the Q39 answerer and the heading-link population count agree on the rule.
HEADING_LINK_XPATH_PATTERN = r"/h[23](\[[0-9]+\])?(/|$)"


@dataclass(frozen=True)
class Evidence:
    """What an answerer observed for one question."""

    rows: list[dict[str, object]] = field(default_factory=list)
    denominator: int | None = None
    available: bool = True
    # False when the answerer tests only part of what the question asks.
    scope_complete: bool = True
    coverage_complete: bool = True
    qualification: str | None = None
    note: str = ""
    language_check: str | None = None
    # Plural noun for what the denominator counts (pages, hosts, host-agent
    # policies...).  It often differs from the question's finding unit.
    denominator_unit: str | None = None


@dataclass(frozen=True)
class Answerer:
    basis: str
    answer: Callable[[Json, Json, Json | None], Evidence]
    # Fallback denominator unit when the evidence does not name one.
    denominator_unit: str | None = None


def unit_label(count: int, unit: str) -> str:
    """``count`` with ``unit`` (a plural noun phrase) in singular or plural form."""

    return f"{count:,} {unit if count != 1 else singular_unit(unit)}"


def singular_unit(unit: str) -> str:
    """Singular form of a plural unit noun phrase: "host-agent policies" -> "host-agent policy"."""

    head, _, last = unit.rpartition(" ")
    if last.endswith("ies") and len(last) > 3:
        last = last[:-3] + "y"
    elif last.endswith("s") and not last.endswith("ss"):
        last = last[:-1]
    return f"{head} {last}" if head else last


def _profile_value(profile: Mapping[str, object], dotted_key: str) -> object | None:
    value: object = profile
    for part in dotted_key.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _path_and_query(url: str) -> str:
    match = re.match(r"^[a-z]+://[^/?#]*", url, re.IGNORECASE)
    rest = url[match.end() :] if match else url
    return rest or "/"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
