"""Helpers for preserving and comparing explicit robots declarations."""

from __future__ import annotations

from collections.abc import Iterable

from .models import RobotsDirectiveEvidence


def directive_conflicts(evidence: Iterable[RobotsDirectiveEvidence]) -> list[dict[str, object]]:
    """Return explicit index/noindex contradictions for overlapping scopes.

    Missing declarations are deliberately not represented as ``index``. A
    generic declaration applies to a named crawler, while two distinct named
    agents do not conflict with one another.
    """
    declarations = list(evidence)
    conflicts: list[dict[str, object]] = []
    for left in declarations:
        left_directives = set(left.directives)
        if "index" in left_directives and "noindex" in left_directives:
            conflicts.append(_conflict(left, left))

    for index, left in enumerate(declarations):
        for right in declarations[index + 1 :]:
            if not _scopes_overlap(left.user_agent, right.user_agent):
                continue
            left_directives, right_directives = set(left.directives), set(right.directives)
            contradictory = ("index" in left_directives and "noindex" in right_directives) or (
                "noindex" in left_directives and "index" in right_directives
            )
            if contradictory:
                conflicts.append(_conflict(left, right))
    return conflicts


def _conflict(left: RobotsDirectiveEvidence, right: RobotsDirectiveEvidence) -> dict[str, object]:
    declarations = [left] if left is right else [left, right]
    return {
        "channels": [item.channel for item in declarations],
        "user_agents": [item.user_agent for item in declarations],
        "declarations": [
            {
                "channel": item.channel,
                "user_agent": item.user_agent,
                "raw_value": item.raw_value,
                "directives": item.directives,
            }
            for item in declarations
        ],
        "effective_indexing": "noindex",
    }


def _scopes_overlap(left: str, right: str) -> bool:
    return left == right or left == "*" or right == "*"
