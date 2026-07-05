"""Custom data extraction rules (ticket 026).

Lets operators pull arbitrary data points (prices, SKUs, authors, ...) out of
crawled pages beyond the standard SEO tags, via CSS selectors, XPath, or regex.

Rule file format (``--extraction-rules rules.json``)::

    {
      "rules": [
        {"name": "price",  "type": "css",   "selector": ".price",   "attr": "text"},
        {"name": "sku",    "type": "xpath", "selector": "//*[@id='sku']/text()"},
        {"name": "authors","type": "css",   "selector": "a.author", "attr": "text",
         "multiple": true},
        {"name": "phone",  "type": "regex", "pattern": "\\\\+?\\\\d[\\\\d ]{7,}\\\\d"}
      ]
    }

Each rule yields one key in the per-page ``custom_data`` JSON object. ``multiple``
rules return a list; otherwise the first match (or null) is returned. ``attr``
(css/xpath) selects an element attribute; ``"text"`` (default) takes text content.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from bs4 import BeautifulSoup
from lxml import html as lxml_html

RuleType = Literal["css", "xpath", "regex"]


@dataclass(slots=True)
class ExtractionRule:
    name: str
    type: RuleType
    selector: str = ""  # css selector or xpath expression
    pattern: str = ""  # regex pattern
    attr: str = "text"  # element attribute, or "text" for text content
    multiple: bool = False
    _compiled_regex: re.Pattern[str] | None = None

    def __post_init__(self) -> None:
        if self.type == "regex":
            if not self.pattern:
                raise ValueError(f"regex rule {self.name!r} requires 'pattern'")
            self._compiled_regex = re.compile(self.pattern)
        elif not self.selector:
            raise ValueError(f"{self.type} rule {self.name!r} requires 'selector'")


def load_extraction_rules(path: str | Path) -> list[ExtractionRule]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_rules = data.get("rules", data) if isinstance(data, dict) else data
    rules: list[ExtractionRule] = []
    for raw in raw_rules:
        rules.append(
            ExtractionRule(
                name=raw["name"],
                type=raw["type"],
                selector=raw.get("selector", ""),
                pattern=raw.get("pattern", ""),
                attr=raw.get("attr", "text"),
                multiple=bool(raw.get("multiple", False)),
            )
        )
    return rules


class CustomExtractor:
    """Evaluates a set of rules against page HTML, returning a name->value map."""

    def __init__(self, rules: list[ExtractionRule]) -> None:
        self.rules = rules
        self._needs_soup = any(r.type == "css" for r in rules)
        self._needs_lxml = any(r.type == "xpath" for r in rules)

    def extract(self, html: str) -> dict[str, object]:
        soup = BeautifulSoup(html, "lxml") if self._needs_soup else None
        tree = lxml_html.fromstring(html) if (self._needs_lxml and html.strip()) else None

        result: dict[str, object] = {}
        for rule in self.rules:
            if rule.type == "css":
                values = self._eval_css(rule, soup)
            elif rule.type == "xpath":
                values = self._eval_xpath(rule, tree)
            else:
                values = self._eval_regex(rule, html)
            result[rule.name] = values if rule.multiple else (values[0] if values else None)
        return result

    @staticmethod
    def _eval_css(rule: ExtractionRule, soup: BeautifulSoup | None) -> list[str]:
        if soup is None:
            return []
        out: list[str] = []
        for el in soup.select(rule.selector):
            if rule.attr == "text":
                out.append(el.get_text(strip=True))
            else:
                value = el.get(rule.attr)
                if value is not None:
                    out.append(value if isinstance(value, str) else " ".join(value))
        return out

    @staticmethod
    def _eval_xpath(rule: ExtractionRule, tree: object) -> list[str]:
        if tree is None:
            return []
        out: list[str] = []
        for node in tree.xpath(rule.selector):  # type: ignore[attr-defined]
            if isinstance(node, str):
                text = node.strip()
                if text:
                    out.append(text)
            elif rule.attr == "text":
                text = node.text_content().strip()
                if text:
                    out.append(text)
            else:
                value = node.get(rule.attr)
                if value:
                    out.append(value)
        return out

    def _eval_regex(self, rule: ExtractionRule, html: str) -> list[str]:
        assert rule._compiled_regex is not None
        matches = rule._compiled_regex.findall(html)
        # findall returns tuples when the pattern has groups; join them.
        return [m if isinstance(m, str) else "".join(m) for m in matches]
