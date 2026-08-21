import json

import pytest
from bs4 import BeautifulSoup

from crawler_cli.__main__ import _json_ld_compatibility_counts
from crawler_cli.extract import extract_page_data
from crawler_cli.models import CrawlJobResult, CrawlResult
from crawler_cli.schema import (
    JSON_LD_PARSER_MODE,
    extract_json_ld,
    extract_schema_data,
    identify_schema_relationships,
)


def _json_ld_name_item(source_value: str):
    html = f"""
    <script type="application/ld+json">
      {{"@context":"https://schema.org","@type":"Thing","name":"{source_value}"}}
    </script>
    """
    items = extract_schema_data(html, "https://example.com/")
    assert len(items) == 1
    return items[0]


@pytest.mark.parametrize(
    ("source_value", "expected_value", "diagnostic_code"),
    [
        ("A & B", "A & B", None),
        ("A &amp; B", "A & B", None),
        ("A &amp;amp; B", "A &amp; B", "jsonld_possible_double_escape"),
        ("Done &amp;#10004;", "Done &#10004;", "jsonld_possible_double_escape"),
        ("Done &amp;#x2714;", "Done &#x2714;", "jsonld_possible_double_escape"),
        ("A &AMP;amp; B", "A &amp; B", "jsonld_possible_double_escape"),
        ("A &#38;amp; B", "A &amp; B", "jsonld_possible_double_escape"),
        (r"A \u0026 B", "A & B", None),
        (r"Done \u2714", "Done ✔", None),
        (r"A \"B\"", 'A "B"', None),
    ],
)
def test_json_ld_uses_exactly_one_html_unescape_pass(source_value, expected_value, diagnostic_code):
    item = _json_ld_name_item(source_value)
    assert item["parser_mode"] == JSON_LD_PARSER_MODE
    assert item["raw_data"].find(source_value) >= 0
    assert json.loads(item["parsed_data"])["name"] == expected_value
    assert item["is_valid"] is True
    diagnostics = item["compatibility_diagnostics"]
    assert [diagnostic["code"] for diagnostic in diagnostics] == ([diagnostic_code] if diagnostic_code else [])
    if diagnostics:
        assert diagnostics[0]["json_pointer"] == "/name"
        assert diagnostics[0]["location_kind"] == "value"
        assert len(diagnostics[0]["source_evidence"]) <= 120


def test_json_ld_invalid_after_unescape_has_no_raw_fallback_or_duplicate():
    item = _json_ld_name_item("A &quot;B&quot;")
    assert item["type"] == "InvalidJSON"
    assert item["parsed_data"] is None
    assert item["is_valid"] is False
    assert item["parser_mode"] == JSON_LD_PARSER_MODE
    assert "after one HTML-unescape pass" in item["validation_errors"][0]
    assert [diagnostic["code"] for diagnostic in item["compatibility_diagnostics"]] == [
        "jsonld_invalid_after_html_unescape"
    ]


def test_json_ld_graph_diagnostics_are_attached_only_to_the_affected_entity():
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
      {"@type":"Thing","name":"A &amp;amp; B"},
      {"@type":"Thing","name":"Clean"}
    ]}
    </script>
    """
    items = extract_schema_data(html, "https://example.com/")
    assert len(items) == 2
    assert [len(item["compatibility_diagnostics"]) for item in items] == [1, 0]
    diagnostic = items[0]["compatibility_diagnostics"][0]
    assert diagnostic["json_pointer"] == "/@graph/0/name"
    assert diagnostic["schema_type"] == "Thing"


def test_json_ld_member_name_diagnostic_uses_json_pointer_escaping():
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Thing","a/b&amp;amp;key":"value"}
    </script>
    """
    item = extract_schema_data(html, "https://example.com/")[0]
    diagnostic = item["compatibility_diagnostics"][0]
    assert diagnostic["location_kind"] == "member_name"
    assert diagnostic["json_pointer"] == "/a~1b&amp;key"


@pytest.mark.parametrize("parser", ["lxml", "html.parser"])
def test_json_ld_direct_and_preparsed_entry_points_match(parser):
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Thing","name":"A &amp;amp; B"}
    </script>
    """
    soup = BeautifulSoup(html, parser)
    direct = extract_json_ld(soup, "https://example.com/")
    through_page = extract_schema_data(html, "https://example.com/", soup=soup)
    assert direct == through_page


def test_json_ld_cli_counts_deduplicate_graph_entities_by_script_block():
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
      {"@type":"Thing","name":"A &amp;amp; B"},
      {"@type":"Thing","name":"C &amp;amp; D"}
    ]}
    </script>
    """
    result = CrawlResult(
        requested_url="https://example.com/",
        final_url="https://example.com/",
        status=200,
        headers={},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=extract_page_data(html, "https://example.com/", {}),
        raw_html=html,
    )
    job = CrawlJobResult(mode="list", seed_urls=[result.final_url], results=[result])
    assert _json_ld_compatibility_counts(job) == (1, 0, 1)


def test_extract_json_ld_graph_expands_entities():
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebPage",
                "@id": "https://example.com/page#webpage",
                "url": "https://example.com/page",
                "name": "Example Page",
            },
            {
                "@type": "Organization",
                "@id": "https://example.com/#org",
                "name": "Example Org",
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://example.com/"},
                    {"@type": "ListItem", "position": 2, "name": "Page", "item": "https://example.com/page"},
                ],
            },
        ],
    }
    html = f"""
    <html>
      <head>
        <script type="application/ld+json">{json.dumps(graph)}</script>
      </head>
      <body><h1>Example</h1></body>
    </html>
    """

    items = extract_schema_data(html, "https://example.com/page")
    json_ld = [item for item in items if item.get("format") == "json-ld" and item.get("is_valid")]
    types = {item["type"] for item in json_ld}

    assert {"WebPage", "Organization", "BreadcrumbList"}.issubset(types)
    assert len(json_ld) >= 3

    relationships = identify_schema_relationships(json_ld)
    assert relationships["main_entity"] is not None
    assert relationships["main_entity"]["type"] in {"WebPage", "Article", "WebSite"}


def test_extract_page_data_includes_schema_data():
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "Article", "headline": "Test", "author": "Jane"}
        </script>
      </head>
      <body><p>Body</p></body>
    </html>
    """
    extracted = extract_page_data(html, "https://example.com/article", {})
    assert extracted.schema_data
    assert any(item.get("type") == "Article" for item in extracted.schema_data)


def test_extract_microdata_and_rdfa():
    close_div = "</" + "div" + ">"
    html = f"""
    <html><body>
      <div itemscope itemtype="https://schema.org/Product">
        <span itemprop="name">Widget</span>
        <span itemprop="offers">9.99</span>
      {close_div}
      <div typeof="https://schema.org/Organization">
        <span property="name">Acme</span>
      {close_div}
    </body></html>
    """
    items = extract_schema_data(html, "https://example.com/products/widget")
    formats = {item.get("format") for item in items if item.get("is_valid")}
    assert "microdata" in formats
    assert "rdfa" in formats
    assert all(item["parser_mode"] is None for item in items)
    assert all(item["compatibility_diagnostics"] == [] for item in items)
