from __future__ import annotations

import json

import pytest

from crawler_cli.audit_html_signals import (
    HTML_SIGNALS_VERSION,
    SPAM_PATTERNS,
    TRACKING_PRELOAD_PATTERNS,
    page_html_signals,
)

PAGE = "https://www.example.com/guide/"

EXPECTED_KEYS = {
    "url",
    "is_https",
    "mixed_content",
    "insecure_internal_links",
    "forms",
    "tracking_preloads",
    "font_face_rules",
    "font_faces_without_swap",
    "font_preloads",
    "head_blocking_stylesheets",
    "head_sync_scripts",
    "preconnect_origins",
    "spam_matches",
    "hidden_links",
    "hreflang_alternates",
    "linked_alternates",
    "followed_external_links",
    "footer_links",
}


def _doc(head: str = "", body: str = "") -> str:
    return f"<!doctype html><html><head>{head}</head><body>{body}</body></html>"


def test_constants_and_exact_keys_are_json_serialisable() -> None:
    assert HTML_SIGNALS_VERSION == "crawler-cli/html-signals/1"
    assert "googletagmanager.com" in TRACKING_PRELOAD_PATTERNS
    assert set(SPAM_PATTERNS) == {"pharma", "essay", "crypto_scam", "casino_spam"}
    record = page_html_signals(PAGE, _doc())
    assert set(record) == EXPECTED_KEYS
    assert record["url"] == PAGE
    assert record["is_https"] is True
    json.dumps(record)


def test_mixed_content_on_https_page() -> None:
    body = """
      <img src="http://cdn.example.net/a.png" srcset="//cdn.example.net/b.png 1x, http://cdn.example.net/c.png 2x">
      <img src="//cdn.example.net/protocol-relative.png">
      <img src="https://cdn.example.net/ok.png">
      <script src="http://js.example.net/app.js"></script>
      <iframe src="http://frame.example.net/"></iframe>
      <video src="http://media.example.net/v.mp4"><source src="http://media.example.net/v.webm">
        <track src="http://media.example.net/t.vtt"></video>
      <audio src="http://media.example.net/a.mp3"></audio>
      <embed src="http://media.example.net/e.swf">
      <object data="http://media.example.net/o.swf"></object>
    """
    head = """
      <link rel="stylesheet" href="http://css.example.net/s.css">
      <link rel="preload" as="script" href="http://css.example.net/p.js">
      <link rel="icon" href="http://css.example.net/favicon.ico">
    """
    mixed = page_html_signals(PAGE, _doc(head, body))["mixed_content"]
    pairs = {(item["tag"], item["attribute"], item["url"]) for item in mixed}
    assert ("img", "src", "http://cdn.example.net/a.png") in pairs
    assert ("img", "srcset", "http://cdn.example.net/c.png") in pairs
    assert ("script", "src", "http://js.example.net/app.js") in pairs
    assert ("link", "href", "http://css.example.net/s.css") in pairs
    assert ("link", "href", "http://css.example.net/p.js") in pairs
    assert ("iframe", "src", "http://frame.example.net/") in pairs
    assert ("source", "src", "http://media.example.net/v.webm") in pairs
    assert {"video", "audio", "track", "embed", "object"} <= {tag for tag, _, _ in pairs}
    urls = {url for _, _, url in pairs}
    assert "http://css.example.net/favicon.ico" not in urls
    assert not any("protocol-relative" in url or "b.png" in url for url in urls)


def test_http_page_has_no_mixed_content_or_insecure_links() -> None:
    html = _doc(body='<img src="http://cdn.example.net/a.png"><a href="http://www.example.com/x">x</a>')
    record = page_html_signals("http://www.example.com/", html)
    assert record["is_https"] is False
    assert record["mixed_content"] == []
    assert record["insecure_internal_links"] == []


def test_insecure_internal_links_with_www_equivalence_and_site_hosts() -> None:
    body = """
      <a href="http://example.com/a#top">a</a>
      <a href="http://WWW.example.com/a">dup</a>
      <a href="http://blog.example.org/b">b</a>
      <a href="http://other.net/c">external</a>
      <a href="https://example.com/d">secure</a>
    """
    record = page_html_signals(PAGE, _doc(body=body), site_hosts=["www.blog.example.org"])
    # Fragments are dropped and hosts lower-cased; www. stays part of the reported URL.
    assert record["insecure_internal_links"] == [
        "http://example.com/a",
        "http://www.example.com/a",
        "http://blog.example.org/b",
    ]


def test_forms() -> None:
    body = """
      <form><input></form>
      <form action="http://example.com/login" method="POST"></form>
      <form action="/search" method=""></form>
      <form action="javascript:void(0)"></form>
      <form action="mailto:a@example.com"></form>
    """
    forms = page_html_signals(PAGE, _doc(body=body))["forms"]
    assert forms[0] == {"action": "", "resolved_action": PAGE, "method": "get", "insecure": False}
    assert forms[1] == {
        "action": "http://example.com/login",
        "resolved_action": "http://example.com/login",
        "method": "post",
        "insecure": True,
    }
    assert forms[2]["resolved_action"] == "https://www.example.com/search"
    assert forms[2]["method"] == "get"
    assert forms[3] == {"action": "javascript:void(0)", "resolved_action": "", "method": "get", "insecure": False}
    assert forms[4]["resolved_action"] == "" and forms[4]["insecure"] is False


def test_form_on_http_page_without_action_is_insecure() -> None:
    forms = page_html_signals("http://example.com/", _doc(body="<form></form>"))["forms"]
    assert forms == [{"action": "", "resolved_action": "http://example.com/", "method": "get", "insecure": True}]


def test_tracking_preloads() -> None:
    head = """
      <link rel="preload" as="script" href="https://www.googletagmanager.com/gtm.js?id=GTM-1">
      <link rel="modulepreload" href="https://www.clarity.ms/tag/abc">
      <link rel="preload" as="script" href="/assets/analytics.js">
      <link rel="preload" as="script" href="https://cdn.example.net/app.js">
      <link rel="preconnect" href="https://www.google-analytics.com">
      <link rel="preload" as="script" href="https://notclarity.ms.example.net/x.js">
    """
    assert page_html_signals(PAGE, _doc(head))["tracking_preloads"] == [
        "https://www.googletagmanager.com/gtm.js?id=GTM-1",
        "https://www.clarity.ms/tag/abc",
        "https://www.example.com/assets/analytics.js",
    ]


def test_font_faces_and_font_preloads() -> None:
    head = """
      <style>
        /* @font-face { font-family: Commented; } */
        @font-face { font-family: "Swap Sans"; src: url(a.woff2); font-display: swap; }
        @font-face { font-family: 'Block Serif'; src: url(b.woff2); font-display: BLOCK !important; }
        @font-face { src: url(c.woff2) }
      </style>
      <style>@FONT-FACE{font-family:Mono;font-display:optional}</style>
      <link rel="preload" as="font" href="/f.woff2" crossorigin>
      <link rel="preload" as="style" href="/s.css">
    """
    record = page_html_signals(PAGE, _doc(head))
    assert record["font_face_rules"] == 4
    assert record["font_faces_without_swap"] == [
        {"family": "Block Serif", "font_display": "block"},
        {"family": "", "font_display": None},
    ]
    assert record["font_preloads"] == 1


def test_head_blocking_stylesheets_and_sync_scripts() -> None:
    head = """
      <link rel="stylesheet" href="/main.css">
      <link rel="stylesheet" href="/print.css" media="print">
      <link rel="stylesheet" href="/off.css" disabled>
      <script src="/sync.js"></script>
      <script src="/typed.js" type="text/javascript"></script>
      <script src="/async.js" async></script>
      <script src="/defer.js" defer></script>
      <script src="/module.js" type="module"></script>
      <script src="/data.json" type="application/ld+json"></script>
      <script src="/tpl.html" type="text/template"></script>
      <script>inline()</script>
    """
    body = '<link rel="stylesheet" href="/body.css"><script src="/body.js"></script>'
    record = page_html_signals(PAGE, _doc(head, body))
    assert record["head_blocking_stylesheets"] == ["https://www.example.com/main.css"]
    assert record["head_sync_scripts"] == ["https://www.example.com/sync.js", "https://www.example.com/typed.js"]


def test_preconnect_origins() -> None:
    head = """
      <link rel="preconnect" href="https://fonts.gstatic.com/some/path" crossorigin>
      <link rel="preconnect" href="https://fonts.gstatic.com">
      <link rel="dns-prefetch preconnect" href="//cdn.example.net:8443/x">
      <link rel="dns-prefetch" href="https://ignored.example.net">
    """
    assert page_html_signals(PAGE, _doc(head))["preconnect_origins"] == [
        "https://fonts.gstatic.com",
        "https://cdn.example.net:8443",
    ]


def test_spam_matches_visible_text_only_on_word_boundaries() -> None:
    body = """
      <p>Buy  VIAGRA online, write my
      essay today, slot88 bonus.</p>
      <p>Cialisx is not a match; nor is viagraonline.</p>
      <script>var t = "double your bitcoin";</script>
      <style>.judi-online{}</style>
      <noscript>agen togel</noscript>
      <template>crypto giveaway</template>
      <!-- slot gacor -->
    """
    matches = page_html_signals(PAGE, _doc(body=body))["spam_matches"]
    assert matches == [
        {"category": "pharma", "term": "viagra"},
        {"category": "essay", "term": "write my essay"},
        {"category": "casino_spam", "term": "slot88"},
    ]


def test_hidden_links() -> None:
    body = """
      <div style="DISPLAY : none !important"><span><a href="https://spam.net/a">a</a></span></div>
      <div hidden><a href="https://spam.net/b">b</a></div>
      <a href="https://spam.net/c" style="visibility:hidden">c</a>
      <p style="font-size: 0px"><a href="https://spam.net/d">d</a></p>
      <p style="font-size:0.5em"><a href="https://spam.net/small">small</a></p>
      <a href="https://spam.net/e" aria-hidden="true">e</a>
      <div style="display:none"><a href="/internal">internal</a></div>
      <a href="https://spam.net/visible">visible</a>
    """
    assert page_html_signals(PAGE, _doc(body=body))["hidden_links"] == [
        "https://spam.net/a",
        "https://spam.net/b",
        "https://spam.net/c",
        "https://spam.net/d",
    ]


def test_hreflang_alternates_and_linked_alternates() -> None:
    head = """
      <link rel="alternate" hreflang="en" href="https://www.example.com/guide">
      <link rel="alternate" hreflang="de" href="/de/guide/">
      <link rel="alternate" hreflang="fr" href="https://www.example.com/fr/guide/">
      <link rel="alternate" type="application/rss+xml" href="/feed">
    """
    body = '<a href="/de/guide#x">Deutsch</a><a href="/es/guide/">Espanol</a>'
    record = page_html_signals(PAGE, _doc(head, body))
    assert record["hreflang_alternates"] == [
        "https://www.example.com/de/guide/",
        "https://www.example.com/fr/guide/",
    ]
    assert record["linked_alternates"] == ["https://www.example.com/de/guide/"]


def test_followed_external_links() -> None:
    body = """
      <a href="https://partner.net/a">a</a>
      <a href="https://partner.net/a#again">dup</a>
      <a href="https://partner.net/nf" rel="nofollow">nf</a>
      <a href="https://partner.net/sp" rel="Sponsored noopener">sp</a>
      <a href="https://partner.net/ugc" rel="ugc">ugc</a>
      <a href="https://example.com/internal">internal via www equivalence</a>
      <a href="mailto:hi@partner.net">mail</a>
      <a href="ftp://partner.net/file">ftp</a>
    """
    assert page_html_signals(PAGE, _doc(body=body))["followed_external_links"] == ["https://partner.net/a"]


def test_footer_links() -> None:
    body = """
      <a href="/outside">outside</a>
      <footer><a href="/about">About</a><a href="tel:123">call</a><a href="/about#team">dup</a></footer>
      <div role="contentinfo"><a href="https://partner.net/">Partner</a></div>
    """
    assert page_html_signals(PAGE, _doc(body=body))["footer_links"] == [
        "https://www.example.com/about",
        "https://partner.net/",
    ]


def test_base_href_is_respected() -> None:
    head = '<base href="https://static.example.com/root/"><link rel="stylesheet" href="s.css">'
    body = '<a href="page">p</a><footer><a href="f">f</a></footer><form action="submit"></form>'
    record = page_html_signals(PAGE, _doc(head, body))
    assert record["head_blocking_stylesheets"] == ["https://static.example.com/root/s.css"]
    assert record["footer_links"] == ["https://static.example.com/root/f"]
    assert record["forms"][0]["resolved_action"] == "https://static.example.com/root/submit"
    assert record["followed_external_links"] == [
        "https://static.example.com/root/page",
        "https://static.example.com/root/f",
    ]


@pytest.mark.parametrize(
    "html",
    [
        "",
        "<html><head><link rel=stylesheet href='http://[bad'><body><a href='http://[::1'>x",
        "<a href='javascript:alert(1)'><img src='data:image/png;base64,AAAA'><a href='tel:+1'>",
        "<div><p><form action='http://a:notaport/'><style>@font-face { font-family: x",
        "\x00�<<<>>>&&&",
    ],
)
def test_malformed_html_does_not_raise(html: str) -> None:
    record = page_html_signals(PAGE, html, site_hosts=["", "https://www.example.com/path"])
    assert set(record) == EXPECTED_KEYS
    json.dumps(record)


def test_non_http_page_url_does_not_raise() -> None:
    record = page_html_signals("mailto:someone@example.com", _doc(body='<a href="https://x.net/">x</a>'))
    assert record["is_https"] is False
    assert record["followed_external_links"] == ["https://x.net/"]
