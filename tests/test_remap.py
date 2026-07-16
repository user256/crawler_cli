"""Ticket 122: compare-time Remap helper."""

import pytest

from crawler_cli.hashing import sha256_hash, simhash64
from crawler_cli.remap import Remap


def test_from_specs_parses_ordered_replacements():
    remap = Remap.from_specs(["dev.example.com=example.com", "https://dev.=https://"])
    assert remap.replacements == [
        ("dev.example.com", "example.com"),
        ("https://dev.", "https://"),
    ]


def test_from_specs_allows_equals_in_target():
    remap = Remap.from_specs(["a=b=c"])
    assert remap.replacements == [("a", "b=c")]


def test_from_specs_rejects_missing_equals():
    with pytest.raises(ValueError):
        Remap.from_specs(["no-equals-here"])


def test_from_specs_rejects_empty_from():
    with pytest.raises(ValueError):
        Remap.from_specs(["=to"])


def test_from_specs_empty_is_falsy():
    assert not Remap.from_specs([])
    assert not Remap.from_specs(None)
    assert Remap.from_specs(["a=b"])


def test_apply_is_ordered():
    # Second replacement operates on the result of the first.
    remap = Remap.from_specs(["one=two", "two=three"])
    assert remap.apply_to_text("one") == "three"


def test_apply_to_text_and_url_none_passthrough():
    remap = Remap.from_specs(["a=b"])
    assert remap.apply_to_text(None) is None
    assert remap.apply_to_url(None) is None
    assert remap.apply_to_url("https://a/a") == "https://b/b"


def test_rehash_applies_replacement_before_hashing():
    remap = Remap.from_specs(["dev.example.com=example.com"])
    dev_html = "<html><body><p>Visit dev.example.com now</p></body></html>"
    prod_html = "<html><body><p>Visit example.com now</p></body></html>"

    sha, sim = remap.rehash(raw_html=dev_html, text=None)
    # Remapped dev content hashes identically to the untouched prod content.
    assert sha == sha256_hash(prod_html)
    assert sim == simhash64(prod_html)


def test_rehash_falls_back_to_text_when_no_raw_html():
    remap = Remap.from_specs(["dev=prod"])
    sha, sim = remap.rehash(raw_html=None, text="hello dev world")
    assert sha == sha256_hash("hello prod world")
    assert sim is not None


def test_rehash_empty_content_signals_no_hash():
    remap = Remap.from_specs(["a=b"])
    assert remap.rehash(raw_html=None, text=None) == (None, None)
    assert remap.rehash(raw_html=None, text="   ") == (None, None)
