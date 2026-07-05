"""Ticket 026: custom data extraction (CSS / XPath / regex)."""

import json

import pytest

from crawler_cli.custom_extract import (
    CustomExtractor,
    ExtractionRule,
    load_extraction_rules,
)

HTML = """
<html><body>
  <span class="price">$19.99</span>
  <div id="sku">ABC-123</div>
  <a class="author" href="/a/jane">Jane</a>
  <a class="author" href="/a/john">John</a>
  <p>Call us on +1 555 1234567 today.</p>
  <meta property="og:image" content="https://cdn.example/img.png">
</body></html>
"""


def test_css_single_text():
    extractor = CustomExtractor([ExtractionRule(name="price", type="css", selector=".price")])
    assert extractor.extract(HTML) == {"price": "$19.99"}


def test_css_multiple():
    extractor = CustomExtractor([ExtractionRule(name="authors", type="css", selector="a.author", multiple=True)])
    assert extractor.extract(HTML) == {"authors": ["Jane", "John"]}


def test_css_attribute():
    extractor = CustomExtractor(
        [ExtractionRule(name="links", type="css", selector="a.author", attr="href", multiple=True)]
    )
    assert extractor.extract(HTML) == {"links": ["/a/jane", "/a/john"]}


def test_xpath_text():
    extractor = CustomExtractor([ExtractionRule(name="sku", type="xpath", selector="//*[@id='sku']/text()")])
    assert extractor.extract(HTML) == {"sku": "ABC-123"}


def test_xpath_attribute_node():
    extractor = CustomExtractor(
        [ExtractionRule(name="img", type="xpath", selector="//meta[@property='og:image']", attr="content")]
    )
    assert extractor.extract(HTML) == {"img": "https://cdn.example/img.png"}


def test_regex():
    extractor = CustomExtractor([ExtractionRule(name="phone", type="regex", pattern=r"\+?\d[\d ]{7,}\d")])
    assert extractor.extract(HTML) == {"phone": "+1 555 1234567"}


def test_missing_match_returns_none():
    extractor = CustomExtractor([ExtractionRule(name="nope", type="css", selector=".does-not-exist")])
    assert extractor.extract(HTML) == {"nope": None}


def test_missing_match_multiple_returns_empty_list():
    extractor = CustomExtractor([ExtractionRule(name="nope", type="css", selector=".x", multiple=True)])
    assert extractor.extract(HTML) == {"nope": []}


def test_rule_validation_errors():
    with pytest.raises(ValueError):
        ExtractionRule(name="bad", type="regex")  # no pattern
    with pytest.raises(ValueError):
        ExtractionRule(name="bad", type="css")  # no selector


def test_load_rules_file(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            {
                "rules": [
                    {"name": "price", "type": "css", "selector": ".price"},
                    {"name": "sku", "type": "xpath", "selector": "//*[@id='sku']/text()"},
                ]
            }
        )
    )
    rules = load_extraction_rules(path)
    assert [r.name for r in rules] == ["price", "sku"]
    assert rules[0].type == "css"


def test_combined_rules():
    extractor = CustomExtractor(
        [
            ExtractionRule(name="price", type="css", selector=".price"),
            ExtractionRule(name="sku", type="xpath", selector="//*[@id='sku']/text()"),
            ExtractionRule(name="phone", type="regex", pattern=r"\+?\d[\d ]{7,}\d"),
        ]
    )
    result = extractor.extract(HTML)
    assert result == {"price": "$19.99", "sku": "ABC-123", "phone": "+1 555 1234567"}
