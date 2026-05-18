from crawler_cli.variants import generate_variants


def test_generate_variants_all_kinds():
    variants = generate_variants("https://example.com/about")
    kinds = {v.kind for v in variants}
    assert kinds == {"trailing_slash", "suffix_php", "suffix_html", "suffix_aspx", "case"}


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
