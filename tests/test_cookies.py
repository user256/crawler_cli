"""Ticket 028: session cookie parsing + injection."""

import json

from crawler_cli.backends import _request_headers
from crawler_cli.config import CrawlConfig
from crawler_cli.cookies import (
    Cookie,
    build_cookie_header,
    build_scoped_cookie_header,
    cookies_for_url,
    load_cookies_file,
    load_scoped_cookies_file,
    parse_cookie_pairs,
    scoped_cookies_from_pairs,
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


# --- ticket 048: per-domain / per-path scoping ---


def test_cookie_domain_match_exact_and_subdomain():
    c = Cookie(name="s", value="1", domain=".example.com")
    assert c.matches("https://example.com/")
    assert c.matches("https://www.example.com/")
    assert not c.matches("https://other.com/")


def test_cookie_host_only_when_no_domain_matches_any_host():
    # The --cookie name=value form has no domain; preserves all-host behaviour.
    c = Cookie(name="s", value="1")
    assert c.matches("https://anything.test/")


def test_cookie_path_match():
    c = Cookie(name="s", value="1", domain="example.com", path="/admin")
    assert c.matches("https://example.com/admin")
    assert c.matches("https://example.com/admin/users")
    assert not c.matches("https://example.com/admintools")
    assert not c.matches("https://example.com/public")


def test_cookie_secure_requires_https():
    c = Cookie(name="s", value="1", domain="example.com", secure=True)
    assert c.matches("https://example.com/")
    assert not c.matches("http://example.com/")


def test_cookies_for_url_selects_matching():
    cookies = [
        Cookie(name="a", value="1", domain="example.com"),
        Cookie(name="b", value="2", domain="other.com"),
        Cookie(name="c", value="3", domain="example.com", path="/admin"),
    ]
    selected = cookies_for_url(cookies, "https://example.com/admin/x")
    names = {c.name for c in selected}
    assert names == {"a", "c"}


def test_build_scoped_cookie_header_filters_by_host():
    cookies = [
        Cookie(name="a", value="1", domain="example.com"),
        Cookie(name="b", value="2", domain="other.com"),
    ]
    assert build_scoped_cookie_header(cookies, "https://example.com/") == "a=1"
    assert build_scoped_cookie_header(cookies, "https://other.com/") == "b=2"


def test_load_scoped_netscape_retains_attributes(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text(
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tFALSE\t0\tsession\tabc\n"
        "#HttpOnly_.shop.example.com\tTRUE\t/cart\tTRUE\t0\tcart\txyz\n"
    )
    cookies = load_scoped_cookies_file(path)
    by_name = {c.name: c for c in cookies}
    assert by_name["session"].domain == ".example.com"
    assert by_name["session"].secure is False
    assert by_name["cart"].domain == ".shop.example.com"
    assert by_name["cart"].path == "/cart"
    assert by_name["cart"].secure is True
    assert by_name["cart"].httponly is True


def test_load_scoped_json_retains_attributes(tmp_path):
    path = tmp_path / "cookies.json"
    path.write_text(json.dumps([
        {"name": "s", "value": "1", "domain": ".example.com", "path": "/", "secure": True, "httpOnly": True},
    ]))
    cookies = load_scoped_cookies_file(path)
    assert cookies[0].domain == ".example.com"
    assert cookies[0].secure is True
    assert cookies[0].httponly is True


def test_request_headers_uses_scoped_cookies_per_host():
    config = CrawlConfig(
        scoped_cookies=[
            Cookie(name="a", value="1", domain="example.com"),
            Cookie(name="b", value="2", domain="other.com"),
        ]
    )
    h_example = _request_headers(config, "https://example.com/")
    h_other = _request_headers(config, "https://other.com/")
    assert h_example["Cookie"] == "a=1"
    assert h_other["Cookie"] == "b=2"


def test_request_headers_scoped_takes_precedence_over_flat():
    config = CrawlConfig(
        cookies={"flat": "9"},
        scoped_cookies=[Cookie(name="a", value="1", domain="example.com")],
    )
    headers = _request_headers(config, "https://example.com/")
    assert headers["Cookie"] == "a=1"
    assert "flat" not in headers["Cookie"]


def test_scoped_cookies_from_pairs_are_host_only():
    cookies = scoped_cookies_from_pairs(["s=1", "t=2"])
    assert all(c.domain == "" for c in cookies)
    # host-less → sent to every host
    assert build_scoped_cookie_header(cookies, "https://any.test/") == "s=1; t=2"
