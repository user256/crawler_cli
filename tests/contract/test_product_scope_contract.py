"""Contract test for the documented product boundary (ticket 144).

`crawler_cli` is an evidence crawler for technical SEO, not an evasion crawler
and not a pentest scanner. That boundary is a safety control for later
contributors and agents, so the prohibited-capability list has to stay in the
documentation where they will read it. This test asserts, over the shipped
`README.md` and `SKILL.md`, that the three-way distinction and the out-of-scope
list are still present, so nobody can quietly delete them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
SKILL = REPO_ROOT / "SKILL.md"

DOCS = [README, SKILL]

# The three-way distinction: evasion crawler, security scanner, evidence crawler.
DISTINCTION_PHRASES = [
    "What This Is / What This Is Not",
    "evasion crawler",
    "pentest scanner",
    "evidence crawler for technical SEO",
]

# The prohibited-capability list. These phrases must survive verbatim.
PROHIBITED_CAPABILITY_PHRASES = [
    "This product is not",
    "changes identity or egress until a blocked request returns 200",
    "CAPTCHA solver or a WAF-specific bypass toolkit",
    "injects SQL, XSS, SSTI, command, path-traversal, or SSRF",
    "credential-stuffing, IDOR/BOLA mutation, or",
    "spoofed search-engine User-Agent as evidence",
]

# The ticket's explicit "Out of scope" list.
OUT_OF_SCOPE_PHRASES = [
    "Out of scope",
    "evade rate limits or bot management",
    "WAF or CAPTCHA solving as a goal",
    "Crawling in spite of `Disallow` as the happy path",
    "Injection, XSS, IDOR, credential stuffing, or hidden-admin fuzzing",
]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
@pytest.mark.parametrize("phrase", DISTINCTION_PHRASES)
def test_docs_name_the_three_way_distinction(doc: Path, phrase: str) -> None:
    assert phrase in _text(doc), f"{doc.name} no longer names '{phrase}' (ticket 144)"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
@pytest.mark.parametrize("phrase", PROHIBITED_CAPABILITY_PHRASES)
def test_docs_keep_the_prohibited_capability_list(doc: Path, phrase: str) -> None:
    assert phrase in _text(doc), f"{doc.name} no longer states '{phrase}' (ticket 144)"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
@pytest.mark.parametrize("phrase", OUT_OF_SCOPE_PHRASES)
def test_docs_keep_the_out_of_scope_list(doc: Path, phrase: str) -> None:
    assert phrase in _text(doc), f"{doc.name} no longer lists '{phrase}' (ticket 144)"


def test_readme_constrains_challenge_escalation() -> None:
    """Ticket 137 must not be 'finished' as an identity-success loop."""
    text = _text(README)
    assert "one** alternate-egress attempt" in text
    assert "keeps trying identities until something returns 200" in text


def test_readme_records_the_language_discipline() -> None:
    text = _text(README)
    for term in ("observe", "inventory", "compare", "candidate", "manual review"):
        assert f'"{term}"' in text, f"README no longer requires the term '{term}' (ticket 144)"
