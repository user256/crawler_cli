import pytest

from crawler_cli import CrawlConfig
from crawler_cli.models import CrawlResult
from crawler_cli.variants import UrlVariant, generate_variants, probe_variant


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


@pytest.mark.asyncio
async def test_probe_variant_records_a_custom_check_source():
    class _Store:
        def __init__(self) -> None:
            self.records: list[tuple[str, str, str]] = []

        async def record_source_by_url(self, url: str, source: str, detail: str) -> None:
            self.records.append((url, source, detail))

    class _Engine:
        def __init__(self) -> None:
            self.config = CrawlConfig()
            self.store = _Store()

        async def crawl(self, url: str) -> CrawlResult:
            return CrawlResult(
                requested_url=url,
                final_url=url,
                status=404,
                headers={},
                content_type="text/html",
                fetch_backend="test",
                extracted=None,
                raw_html=None,
            )

    engine = _Engine()
    variant = UrlVariant("https://example.com/page.html", "suffix_html")

    result = await probe_variant(engine, "https://example.com/page", variant)

    assert result.verdict == "absent"
    assert engine.store.records == [(variant.url, "custom_check", "url_variant:suffix_html")]
