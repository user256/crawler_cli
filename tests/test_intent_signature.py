"""Unit tests for intent-signature extraction (ticket 076).

Mirrors Intent_Overlap's signature unit coverage, including the Sprint 2/3
remediation invariants: one unified hash definition, signature stability, and
the ticket-114 zero-re-embed proof.
"""

from __future__ import annotations

import pytest

from crawler_cli.intent_signature import (
    backfill_intent_signatures,
    detect_boilerplate,
    extract_main_text,
    intent_text,
    resolve_signal_confidence,
    signature_hash,
    signature_text,
    strip_boilerplate_field,
)


# --------------------------------------------------------------------------
# Boilerplate detection
# --------------------------------------------------------------------------

def test_boilerplate_share_threshold_strictly_greater():
    # Suffix "Acme" appears on 2/4 = 0.50 (> 0.30) -> stripped.
    titles = {
        "acme.com": [
            "Widgets | Acme",
            "Gadgets | Acme",
            "About the company",
            "Careers here",
        ]
    }
    patterns = detect_boilerplate(titles, min_share=0.30)
    assert patterns["acme.com"] == (None, "Acme")


def test_boilerplate_not_detected_at_or_below_threshold():
    # Suffix appears on exactly 0.30 share -> NOT stripped (strictly greater).
    titles = {"x.com": ["A | Brand"] + ["B", "C", "D", "E", "F", "G", "H", "I", "J"]}
    # 1/10 = 0.10 share, well below threshold.
    assert "x.com" not in detect_boilerplate(titles, min_share=0.30)


def test_boilerplate_skips_single_title_sites():
    assert detect_boilerplate({"solo.com": ["Only | Page"]}) == {}


def test_strip_boilerplate_prefix_and_suffix():
    assert strip_boilerplate_field("Acme | Widgets", "Acme", None) == "Widgets"
    assert strip_boilerplate_field("Widgets | Acme", None, "Acme") == "Widgets"
    # Title that is exactly the boilerplate collapses to empty.
    assert strip_boilerplate_field("Acme", "Acme", None) == ""


# --------------------------------------------------------------------------
# intent_text / signature composition
# --------------------------------------------------------------------------

def test_intent_text_field_order_and_body_cap():
    row = {
        "site": "acme.com",
        "title": "Buy Widgets",
        "h1": "Widgets For Sale",
        "meta_description": "The best widgets",
        "text": "x" * 3000,
    }
    text = intent_text(row)
    lines = text.split("\n")
    assert lines[0] == "Buy Widgets"
    assert lines[1] == "Widgets For Sale"
    assert lines[2] == "The best widgets"
    # Body text capped at 1500 chars.
    assert len(lines[3]) == 1500


def test_intent_text_drops_empty_fields():
    row = {"site": "a.com", "title": "Only Title", "h1": None, "meta_description": "", "text": None}
    assert intent_text(row) == "Only Title"


def test_intent_text_applies_boilerplate():
    boilerplate = {"acme.com": (None, "Acme")}
    row = {"site": "acme.com", "title": "Widgets | Acme", "h1": "", "meta_description": "", "text": ""}
    assert intent_text(row, boilerplate) == "Widgets"


def test_signature_text_derives_site_from_url():
    # Boilerplate keyed by netloc.lower(); URL uppercase host still matches.
    boilerplate = {"acme.com": (None, "Acme")}
    row = {"url": "https://ACME.com/p", "title": "Widgets | Acme", "h1": "", "meta_description": "", "text": ""}
    assert signature_text(row, boilerplate) == "Widgets"


# --------------------------------------------------------------------------
# Hash contract: one definition, stable, changes with any field
# --------------------------------------------------------------------------

def _row(**over):
    base = {
        "url": "https://acme.com/p",
        "title": "Buy Widgets",
        "h1": "Widgets",
        "meta_description": "Best widgets",
        "text": "Some body copy about widgets.",
    }
    base.update(over)
    return base


def test_signature_hash_is_stable():
    assert signature_hash(_row()) == signature_hash(_row())


@pytest.mark.parametrize("field", ["title", "h1", "meta_description", "text"])
def test_signature_hash_changes_when_any_field_changes(field):
    assert signature_hash(_row()) != signature_hash(_row(**{field: "CHANGED value here"}))


def test_signature_hash_matches_manual_sha256():
    import hashlib

    row = _row()
    expected = hashlib.sha256(signature_text(row).encode("utf-8")).hexdigest()
    assert signature_hash(row) == expected


# --------------------------------------------------------------------------
# Extraction + confidence
# --------------------------------------------------------------------------

def test_extract_main_text_fallback_or_trafilatura():
    html = "<html><body><article><p>" + ("Real content here. " * 40) + "</p></article></body></html>"
    text, method = extract_main_text(html)
    assert text is not None
    assert "Real content" in text
    assert method in {"trafilatura", "fallback"}


def test_extract_main_text_strips_scripts_in_fallback():
    # Minimal markup trafilatura tends to reject -> exercises fallback path.
    html = "<html><body><script>evil()</script><div>hi</div></body></html>"
    text, method = extract_main_text(html)
    assert text is None or "evil" not in text
    assert method in {"trafilatura", "fallback", "none"}


def test_extract_main_text_none_on_empty():
    text, method = extract_main_text("<html><body></body></html>")
    assert text is None
    assert method == "none"


def test_resolve_signal_confidence():
    assert resolve_signal_confidence(100, "trafilatura", min_words=50) == "high"
    assert resolve_signal_confidence(10, "trafilatura", min_words=50) == "low"
    assert resolve_signal_confidence(100, "fallback", min_words=50) == "low"
    assert resolve_signal_confidence(None, "trafilatura", min_words=50) == "low"


# --------------------------------------------------------------------------
# Zero-re-embed proof against a fake store (no DB, CI-safe)
# --------------------------------------------------------------------------

class FakeSignatureStore:
    """In-memory stand-in exercising the backfill contract without Postgres."""

    def __init__(self, pages):
        self._pages = pages
        self.signatures: dict[int, dict] = {}

    async def fetch_pages_for_signatures(self, *, urls=None):
        if urls is None:
            return [dict(p) for p in self._pages]
        return [dict(p) for p in self._pages if p["url"] in urls]

    async def existing_signature_hashes(self):
        return {uid: row["signature_hash"] for uid, row in self.signatures.items()}

    async def store_intent_signatures_bulk(self, rows):
        for r in rows:
            self.signatures[r["url_id"]] = dict(r)


def _page(url_id, url, title, body):
    html = f"<html><body><article><p>{body}</p></article></body></html>"
    return {"url_id": url_id, "url": url, "html": html, "title": title, "h1": title, "meta_description": ""}


@pytest.mark.asyncio
async def test_backfill_zero_reembed_on_unchanged_crawl():
    pages = [
        _page(1, "https://acme.com/a", "Alpha Widgets", "Content about alpha widgets. " * 30),
        _page(2, "https://acme.com/b", "Beta Gadgets", "Content about beta gadgets. " * 30),
    ]
    store = FakeSignatureStore(pages)

    first = await backfill_intent_signatures(store)
    assert first.processed == 2
    assert first.updated == 2
    assert first.unchanged == 0

    # Re-running on an unchanged crawl must rewrite zero hashes (ticket-114).
    second = await backfill_intent_signatures(store)
    assert second.processed == 2
    assert second.updated == 0
    assert second.unchanged == 2


@pytest.mark.asyncio
async def test_backfill_reembeds_only_changed_page():
    pages = [
        _page(1, "https://acme.com/a", "Alpha Widgets", "Content about alpha widgets. " * 30),
        _page(2, "https://acme.com/b", "Beta Gadgets", "Content about beta gadgets. " * 30),
    ]
    store = FakeSignatureStore(pages)
    await backfill_intent_signatures(store)

    # Change page 2's title -> only that signature changes.
    pages[1]["title"] = "Beta Gizmos Rebranded"
    result = await backfill_intent_signatures(store)
    assert result.updated == 1
    assert result.unchanged == 1


@pytest.mark.asyncio
async def test_backfill_dry_run_writes_nothing():
    pages = [_page(1, "https://acme.com/a", "Alpha", "Content here. " * 30)]
    store = FakeSignatureStore(pages)
    result = await backfill_intent_signatures(store, dry_run=True)
    assert result.updated == 1
    assert store.signatures == {}
