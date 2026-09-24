from crawler_cli.extract import extract_page_data
from crawler_cli.indexability import directive_conflicts


def _evidence(html: str, header: str | None = None):
    headers = {"X-Robots-Tag": header} if header is not None else {}
    return extract_page_data(html, "https://example.test/page", headers).robots_directive_evidence


def test_meta_only_noindex_is_not_a_conflict():
    evidence = _evidence('<meta name="robots" content="noindex">')
    assert directive_conflicts(evidence) == []


def test_header_only_noindex_is_not_a_conflict():
    evidence = _evidence("<html></html>", "noindex")
    assert directive_conflicts(evidence) == []


def test_absent_directives_are_not_a_conflict():
    assert directive_conflicts(_evidence("<html></html>")) == []


def test_non_robot_meta_tags_are_not_misread_as_robot_directives():
    evidence = _evidence('<meta name="description" content="index">')
    assert evidence == []


def test_matching_noindex_declarations_are_not_a_conflict():
    evidence = _evidence('<meta name="robots" content="noindex">', "noindex")
    assert directive_conflicts(evidence) == []


def test_explicit_index_noindex_conflict_preserves_both_declarations():
    evidence = _evidence('<meta name="robots" content="index, follow">', "noindex")
    conflicts = directive_conflicts(evidence)
    assert len(conflicts) == 1
    assert conflicts[0]["effective_indexing"] == "noindex"
    declarations = conflicts[0]["declarations"]
    assert [item["channel"] for item in declarations] == ["html_meta", "http_header"]
    assert declarations[0]["raw_value"] == "index, follow"


def test_contradictory_meta_tags_for_the_same_agent_are_reported():
    evidence = _evidence('<meta name="robots" content="index"><meta name="robots" content="noindex">')
    assert len(directive_conflicts(evidence)) == 1


def test_unrelated_agent_scopes_do_not_conflict():
    evidence = _evidence('<meta name="bingbot" content="index">', "googlebot: noindex")
    assert directive_conflicts(evidence) == []


def test_specific_agent_contradicts_applicable_general_declaration():
    evidence = _evidence('<meta name="robots" content="index">', "googlebot: noindex")
    assert directive_conflicts(evidence)[0]["user_agents"] == ["*", "googlebot"]


def test_multiple_user_agent_header_declarations_keep_distinct_scope():
    evidence = _evidence("<html></html>", "googlebot: noindex, nofollow, bingbot: index")
    assert [(item.user_agent, item.directives) for item in evidence] == [
        ("googlebot", ["noindex", "nofollow"]),
        ("bingbot", ["index"]),
    ]


def test_meta_none_means_noindex_and_nofollow():
    extracted = extract_page_data('<meta name="robots" content="none">', "https://example.test/", {})
    assert extracted.meta_robots.noindex is True
    assert extracted.meta_robots.nofollow is True
