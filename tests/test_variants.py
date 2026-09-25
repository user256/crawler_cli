from crawler_cli.variants import generate_variants


def test_generate_variants_all_kinds():
    variants = generate_variants("https://example.com/about")
    kinds = {v.kind for v in variants}
    assert kinds == {
        "trailing_slash",
        "suffix_php",
        "suffix_html",
        "suffix_aspx",
        "case",
        "scheme",
        "www_host",
    }


def test_generate_variants_trailing_slash():
    variants = generate_variants("https://example.com/about", kinds={"trailing_slash"})
    assert len(variants) == 1
    assert variants[0].url == "https://example.com/about/"


def test_generate_variants_suffixes():
    variants = generate_variants("https://example.com/about", kinds={"suffix_php", "suffix_html"})
    urls = {v.url for v in variants}
    assert urls == {"https://example.com/about.php", "https://example.com/about.html"}


def test_generate_variants_case_flip():
    variants = generate_variants("https://example.com/about", kinds={"case"})
    assert len(variants) == 1
    assert variants[0].url == "https://example.com/ABOUT"


def test_generate_variants_skips_existing_suffix():
    variants = generate_variants("https://example.com/about.php", kinds={"suffix_php"})
    assert len(variants) == 0


def test_generate_variants_flip_slash_scheme_host_and_query_order_deterministically():
    url = "https://www.example.com/a?z=2&a=&b=3"
    variants = generate_variants(url)

    assert [
        (item.kind, item.url)
        for item in variants
        if item.kind in {"trailing_slash", "scheme", "www_host", "query_order"}
    ] == [
        ("trailing_slash", "https://www.example.com/a/?z=2&a=&b=3"),
        ("scheme", "http://www.example.com/a?z=2&a=&b=3"),
        ("www_host", "https://example.com/a?z=2&a=&b=3"),
        ("query_order", "https://www.example.com/a?a=&b=3&z=2"),
    ]
    assert generate_variants(url) == variants


def test_generate_variants_does_not_invent_plus_as_encoded_space_equivalence():
    urls = {item.url for item in generate_variants("https://example.com/a+b")}

    assert "https://example.com/a%20b" not in urls
