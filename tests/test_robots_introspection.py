import pytest

from crawler_cli.robots import RobotsDecision, _RobotsRules


@pytest.mark.asyncio
async def test_check_returns_matched_disallow_rule():
    rules = _RobotsRules("example.com", "User-agent: *\nDisallow: /wp-admin/\n")
    decision = rules.check("/wp-admin/foo", "*")
    assert decision.allowed is False
    assert decision.matched_rule == "Disallow: /wp-admin/"
    assert decision.matched_user_agent == "*"
    assert decision.source_url == "https://example.com/robots.txt"


@pytest.mark.asyncio
async def test_check_returns_allow_override():
    rules = _RobotsRules("example.com", "User-agent: *\nDisallow: /\nAllow: /public/\n")
    decision = rules.check("/public/page", "*")
    assert decision.allowed is True
    assert decision.matched_rule == "Allow: /public/"


@pytest.mark.asyncio
async def test_check_wildcard_rule():
    rules = _RobotsRules("example.com", "User-agent: *\nDisallow: /*.pdf\n")
    decision = rules.check("/file.pdf", "*")
    assert decision.allowed is False
    assert "*.pdf" in (decision.matched_rule or "")


@pytest.mark.asyncio
async def test_check_no_match_defaults_allowed():
    rules = _RobotsRules("example.com", "User-agent: *\nDisallow: /private/\n")
    decision = rules.check("/public/page", "*")
    assert decision.allowed is True
    assert decision.matched_rule is None
