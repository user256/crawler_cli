from crawler_cli.archive import _clean_url, _normalize_url


def test_normalize_url_strips_double_prefix():
    result = _normalize_url("https://example.com/https://other.com/page")
    assert result == "https://other.com/page"


def test_normalize_url_returns_none_for_empty():
    assert _normalize_url("   ") is None
    assert _normalize_url("") is None


def test_clean_url_drops_mailto():
    assert _clean_url("mailto:foo@example.com") is None


def test_clean_url_drops_asset_extensions():
    assert _clean_url("https://example.com/style.css") is None
    assert _clean_url("https://example.com/image.jpg") is None
    assert _clean_url("https://example.com/font.woff2") is None


def test_clean_url_drops_well_known():
    assert _clean_url("https://example.com/.well-known/security.txt") is None


def test_clean_url_keeps_html():
    result = _clean_url("https://example.com/page.html")
    assert result == "https://example.com/page.html"


def test_clean_url_strips_port():
    result = _clean_url("https://example.com:8080/page")
    assert result == "https://example.com/page"


def test_clean_url_force_https():
    result = _clean_url("http://example.com/page", force_https=True)
    assert result == "https://example.com/page"


def test_clean_url_force_www():
    result = _clean_url("https://example.com/page", force_www=True)
    assert result == "https://www.example.com/page"
