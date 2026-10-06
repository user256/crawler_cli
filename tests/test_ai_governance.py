from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from crawler_cli.ai_governance import (
    AI_CRAWLER_FAMILIES,
    classify_ai_crawlers,
    classify_llms_response,
    collect_ai_governance,
    declared_preference_signals,
    project_ai_governance,
)
from crawler_cli.models import FetchResponse
from crawler_cli.robots import _RobotsRules


BASE = "https://example.com"

MIXED_ROBOTS = """\
User-agent: *
Disallow: /admin

User-agent: GPTBot
Disallow: /

User-agent: ChatGPT-User
Allow: /

User-agent: ClaudeBot
Disallow: /private/

User-agent: anthropic-ai
Disallow: /

User-agent: PerplexityBot
User-agent: Amazonbot
Disallow: /
Allow: /blog/

User-agent: Google-Extended
Disallow: /

User-agent: CCBot
Disallow:

Content-Signal: search=yes, ai-train=no
"""

LLMS_MARKDOWN = b"""# Example Casino Guide

> Independent reviews of licensed operators.

## Reviews
- [Operator A](https://example.com/reviews/a): full review
- [Operator B](https://example.com/reviews/b): full review
"""

HTML_404 = b"""<!DOCTYPE html>
<html><head><title>Page not found | Example</title></head>
<body><h1>Sorry, this page does not exist</h1></body></html>
"""


def _rules(content: str, status: int = 200) -> _RobotsRules:
    return _RobotsRules("example.com", content, status=status)


def _response(path: str, body: bytes, content_type: str | None, status: int = 200) -> FetchResponse:
    url = f"{BASE}{path}"
    return FetchResponse(
        url=url,
        requested_url=url,
        status=status,
        headers={"Content-Type": content_type} if content_type else {},
        body=body,
        text=body.decode("utf-8", errors="replace"),
        wire_bytes=len(body),
        decoded_bytes=len(body),
        elapsed_seconds=0.05,
    )


def _postures(rows):
    return {row["family"]: row["posture"] for row in rows}


def test_mixed_robots_fixture_classifies_all_nine_ai_crawler_families():
    rows = classify_ai_crawlers(_rules(MIXED_ROBOTS))

    assert [row["family"] for row in rows] == [family.id for family in AI_CRAWLER_FAMILIES]
    assert len(rows) == 9
    assert _postures(rows) == {
        "gptbot": "blocked",
        "chatgpt-user": "allowed",
        "claudebot": "partially_blocked",
        "perplexitybot": "partially_blocked",
        "google-extended": "blocked",
        "amazonbot": "partially_blocked",
        "bytespider": "default_wildcard",
        "ccbot": "allowed",
        "applebot-extended": "default_wildcard",
    }
    by_family = {row["family"]: row for row in rows}
    # Wildcard fallback still records what the '*' group actually permits.
    assert by_family["bytespider"]["effective_access"] == "partially_blocked"
    assert by_family["bytespider"]["group_source"] == "wildcard"
    # ClaudeBot governs the family; the legacy anthropic-ai token disagrees.
    assert by_family["claudebot"]["governing_token"] == "ClaudeBot"
    assert by_family["claudebot"]["alias_conflict"] is True
    gpt = by_family["gptbot"]["token_results"][0]
    assert gpt["root_matched_rule"] == "Disallow: /"
    assert gpt["group_rules"] == ["Disallow: /"]


def test_posture_distinguishes_homepage_only_rules_and_allow_ties():
    homepage_only = classify_ai_crawlers(_rules("User-agent: GPTBot\nDisallow: /$\n"))
    tie = classify_ai_crawlers(_rules("User-agent: GPTBot\nDisallow: /\nAllow: /\n"))

    assert _postures(homepage_only)["gptbot"] == "partially_blocked"
    # RFC 9309: Allow wins an equal-length tie, so nothing is blocked.
    assert _postures(tie)["gptbot"] == "allowed"


def test_missing_and_unreachable_robots_are_not_reported_as_explicit_policy():
    missing = classify_ai_crawlers(_rules("", status=404))
    unreachable = classify_ai_crawlers(None)

    assert set(_postures(missing).values()) == {"default_wildcard"}
    assert {row["effective_access"] for row in missing} == {"allowed"}
    assert set(_postures(unreachable).values()) == {"unknown"}


def test_preference_signals_are_recorded_as_declarations():
    assert declared_preference_signals(MIXED_ROBOTS) == ["Content-Signal: search=yes, ai-train=no"]


def test_valid_llms_txt_records_status_type_length_and_title():
    record = classify_llms_response(
        _response("/llms.txt", LLMS_MARKDOWN, "text/markdown; charset=utf-8"), kind="llms_txt"
    )

    assert record["state"] == "valid"
    assert record["http_status"] == 200
    assert record["content_type"] == "text/markdown"
    assert record["byte_size"] == len(LLMS_MARKDOWN)
    assert record["title"] == "Example Casino Guide"
    assert record["summary_blockquote_present"] is True
    assert record["section_count"] == 1
    assert record["markdown_link_count"] == 2
    assert record["final_url"] == f"{BASE}/llms.txt"


def test_html_error_page_served_with_200_is_an_invalid_soft_404():
    as_html = classify_llms_response(_response("/llms.txt", HTML_404, "text/html; charset=utf-8"), kind="llms_txt")
    # A mislabelled HTML body is still a page, not a text manifest.
    mislabelled = classify_llms_response(_response("/llms.txt", HTML_404, "text/plain"), kind="llms_txt")

    for record in (as_html, mislabelled):
        assert record["state"] == "html_soft_404"
        assert record["http_status"] == 200
        assert record["html_title"] == "Page not found | Example"
        assert record["error_phrase_in_body"] is True


def test_llms_response_edge_states():
    plain_no_title = b"Site: example\n- [A](https://example.com/a)\n"

    assert classify_llms_response(_response("/llms.txt", b"", "text/plain", 404), kind="llms_txt")["state"] == "absent"
    assert classify_llms_response(_response("/llms.txt", b"", "text/plain", 503), kind="llms_txt")["state"] == (
        "http_error"
    )
    assert classify_llms_response(_response("/llms.txt", b"  \n", "text/plain"), kind="llms_txt")["state"] == "empty"
    assert (
        classify_llms_response(_response("/llms.txt", plain_no_title, "text/plain"), kind="llms_txt")["state"]
        == "missing_h1_title"
    )
    # llms-full.txt carries full content and has no required H1.
    assert (
        classify_llms_response(_response("/llms-full.txt", plain_no_title, "text/plain"), kind="llms_full_txt")["state"]
        == "valid"
    )
    assert (
        classify_llms_response(_response("/llms.txt", LLMS_MARKDOWN, "application/octet-stream"), kind="llms_txt")[
            "state"
        ]
        == "unexpected_content_type"
    )


class _Robots:
    def __init__(self, rules: _RobotsRules | None) -> None:
        self.rules = rules

    async def get_rules(self, _url: str) -> _RobotsRules | None:
        return self.rules

    async def check(self, url: str):
        assert self.rules is not None
        return self.rules.check(urlsplit(url).path or "/", "crawler_cli/0.1")


class _Engine:
    def __init__(self, responses: dict[str, FetchResponse], rules: _RobotsRules | None) -> None:
        self.responses = responses
        self.fetched: list[str] = []
        self._robots = _Robots(rules)
        self.config = SimpleNamespace(user_agent_for=lambda _url: "crawler_cli/0.1")

    async def _bounded_fetch_response(self, url: str):
        self.fetched.append(url)
        return self.responses.get(url)


@pytest.mark.asyncio
async def test_collector_is_bounded_and_never_fetches_robots_disallowed_context_files():
    rules = _rules(MIXED_ROBOTS + "\nUser-agent: *\nDisallow: /llms-full.txt\n")
    engine = _Engine(
        {
            f"{BASE}/.well-known/llms.txt": _response("/.well-known/llms.txt", b"", "text/html", 404),
            f"{BASE}/llms.txt": _response("/llms.txt", HTML_404, "text/html"),
        },
        rules,
    )

    collected = await collect_ai_governance(engine, seed_origins=[f"{BASE}/", BASE])

    assert engine.fetched == [f"{BASE}/.well-known/llms.txt", f"{BASE}/llms.txt"]
    assert collected["complete"] is True
    assert collected["origin_count"] == 1
    assert collected["tested_count"] == 9 + 3
    states = {row["path"]: row["state"] for row in collected["llms_files"]}
    assert states == {
        "/.well-known/llms.txt": "absent",
        "/llms.txt": "html_soft_404",
        "/llms-full.txt": "robots_disallowed_not_fetched",
    }
    assert collected["robots_documents"][0]["declared_preference_signals"] == [
        "Content-Signal: search=yes, ai-train=no"
    ]

    rows = project_ai_governance(collected)
    assert rows[0]["record_type"] == "coverage"
    assert "bot_posture" not in rows[0] and "llms_files" not in rows[0]
    candidate_types = sorted(row["candidate_type"] for row in rows if row["record_type"] == "candidate")
    assert candidate_types == [
        "ai_crawler_access_restricted",  # gptbot
        "ai_crawler_access_restricted",  # claudebot
        "ai_crawler_access_restricted",  # perplexitybot
        "ai_crawler_access_restricted",  # google-extended
        "ai_crawler_access_restricted",  # amazonbot
        "ai_crawler_alias_conflict",
        "llms_file_html_soft_404",
    ]
    json.dumps(rows)


@pytest.mark.asyncio
async def test_unreachable_robots_leaves_posture_unknown_and_fetches_nothing():
    engine = _Engine({}, None)

    collected = await collect_ai_governance(engine, seed_origins=[BASE])

    assert engine.fetched == []
    assert collected["complete"] is False
    assert {row["posture"] for row in collected["bot_posture"]} == {"unknown"}
    assert {row["state"] for row in collected["llms_files"]} == {"robots_unavailable_not_fetched"}


@pytest.mark.asyncio
async def test_absent_manifests_are_informational_and_origin_budget_is_recorded():
    engine = _Engine(
        {f"{BASE}{path}": _response(path, b"", "text/html", 404) for path in ("/.well-known/llms.txt", "/llms.txt")},
        _rules("", status=404),
    )

    collected = await collect_ai_governance(engine, seed_origins=[BASE, "https://other.example.com"], max_origins=1)
    rows = project_ai_governance(collected)

    assert collected["complete"] is False
    assert collected["skipped_origins"] == ["https://other.example.com"]
    candidates = [row for row in rows if row["record_type"] == "candidate"]
    # /llms-full.txt returned nothing from the fake engine: fetch unavailable.
    assert [row["candidate_type"] for row in candidates] == ["llms_txt_absent"]
    assert candidates[0]["qualification"] == "absence_is_not_a_defect_llms_txt_is_a_proposal"
