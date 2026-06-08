"""Ticket 028: session cookie parsing + injection."""

import json

from crawler_cli.backends import _request_headers
from crawler_cli.config import CrawlConfig
from crawler_cli.cookies import (
    build_cookie_header,
    load_cookies_file,
    parse_cookie_pairs,
)


def test_parse_simple_pairs():
    assert parse_cookie_pairs(["session=abc", "csrf=xyz"]) == {
        "session": "abc",
        "csrf": "xyz",
    }


def test_parse_semicolon_joined():
    assert parse_cookie_pairs(["a=1; b=2; c=3"]) == {"a": "1", "b": "2", "c": "3"}


def test_parse_value_with_equals():
    assert parse_cookie_pairs(["token=ab=cd=ef"]) == {"token": "ab=cd=ef"}


def test_parse_ignores_malformed():
    assert parse_cookie_pairs(["", "noequals", "  ", "k=v"]) == {"k": "v"}


def test_build_cookie_header():
    assert build_cookie_header({"a": "1", "b": "2"}) == "a=1; b=2"


def test_load_json_array_file(tmp_path):
    path = tmp_path / "cookies.json"
    path.write_text(json.dumps([
        {"name": "session", "value": "abc", "domain": ".example.com"},
        {"name": "lang", "value": "en"},
    ]))
    assert load_cookies_file(path) == {"session": "abc", "lang": "en"}


def test_load_storagestate_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "cookies": [{"name": "sid", "value": "999"}],
        "origins": [],
    }))
    assert load_cookies_file(path) == {"sid": "999"}


def test_load_netscape_file(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text(
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tFALSE\t0\tsession\tabc\n"
        "#HttpOnly_.example.com\tTRUE\t/\tTRUE\t0\tsecure_tok\txyz\n"
    )
    assert load_cookies_file(path) == {"session": "abc", "secure_tok": "xyz"}


def test_request_headers_injects_cookie():
    config = CrawlConfig(cookies={"session": "abc", "csrf": "xyz"})
    headers = _request_headers(config, "https://example.com/")
    assert headers["Cookie"] == "session=abc; csrf=xyz"


def test_request_headers_no_cookie_when_empty():
    config = CrawlConfig()
    headers = _request_headers(config, "https://example.com/")
    assert "Cookie" not in headers
