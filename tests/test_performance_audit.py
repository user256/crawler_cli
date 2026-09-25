import asyncio
from types import SimpleNamespace

from crawler_cli import performance_audit as audit


def _page(url, ttfb, total, *, template="product", locale="en", **extra):
    return {
        "url": url,
        "kind": "html",
        "final_status_code": 200,
        "content_extracted": True,
        "challenge": None,
        "overall_indexable": True,
        "canonical_urls_json": [],
        "html_lang": locale,
        "template": template,
        "headers_json": {"ETag": '"real-tag"', "Cache-Control": "public, max-age=60"},
        "ttfb_seconds": ttfb,
        "total_duration_seconds": total,
        "lcp_ms": 1200,
        "cls": 0.01,
        "inp_ms": 30,
        **extra,
    }


def test_timing_quantiles_use_nearest_rank_and_keep_valid_denominators():
    rows = [_page(f"https://example.test/p/{value}", value / 10, value / 5) for value in range(1, 11)]
    rows.append(_page("https://example.test/p/invalid", -1, None))
    coverage, group = audit.performance_inventory_report(rows)
    assert coverage["eligible_canonical_indexable_html_count"] == 11
    assert group["ttfb_seconds"] == {
        "valid_sample_count": 10,
        "excluded_sample_count": 1,
        "mean": 0.55,
        "p90": 0.9,
        "p99": 1.0,
        "worst": 1.0,
    }
    assert group["total_duration_seconds"]["valid_sample_count"] == 10
    assert group["cache_evidence"]["etag"] == 11
    assert group["cwv_source"] == "crawler_lab_only; not_field_or_real_user_data"
    assert coverage["field_cwv"] == "unavailable_not_supplied"


def test_timing_population_excludes_noncanonical_nonindexable_and_challenged_rows():
    rows = [
        _page("https://example.test/self", 0.1, 0.2),
        _page("https://example.test/alias", 0.3, 0.4, canonical_urls_json=["https://example.test/other"]),
        _page("https://example.test/noindex", 0.3, 0.4, overall_indexable=False),
        _page("https://example.test/challenge", 0.3, 0.4, challenge="cloudflare"),
    ]
    coverage, group = audit.performance_inventory_report(rows)
    assert coverage["eligible_canonical_indexable_html_count"] == 1
    assert coverage["excluded_by_reason"] == {
        "canonical_unknown_or_nonself": 1,
        "challenge": 1,
        "not_indexable_or_unknown": 1,
    }
    assert group["eligible_page_count"] == 1


def test_conditional_candidate_sampling_is_repeatable_and_balanced_by_locale_template():
    rows = [
        _page(f"https://example.test/product/{index}", 0.1, 0.2, template="product")
        for index in range(4)
    ] + [_page("https://example.test/article/1", 0.1, 0.2, template="article", locale="fr")]
    first = audit.select_conditional_probe_candidates(rows, max_pages=3)
    second = audit.select_conditional_probe_candidates(rows, max_pages=3)
    assert [row["url"] for row in first] == [row["url"] for row in second]
    assert {row["template"] for row in first} == {"product", "article"}


def _result(status, *, headers=None, body=None, skip_reason=None):
    return SimpleNamespace(
        status=status,
        headers=headers or {},
        raw_html=body,
        challenge=None,
        skip_reason=skip_reason,
        wire_bytes=30 if body else 0,
        decoded_bytes=len(body.encode()) if body else 0,
        ttfb_seconds=0.02,
        total_duration_seconds=0.1,
    )


def _candidate():
    return {"url": "https://example.test/page", "stratum": "en|product", "template": "product", "html_lang": "en"}


def test_missing_validator_is_not_testable_and_never_synthesizes_one(monkeypatch):
    class OrdinaryEngine:
        async def crawl(self, url, *, purpose):
            return _result(200, headers={"Content-Type": "text/html"}, body="page")

        async def close(self):
            return None

    class NeverConditional:
        def __init__(self, *args, **kwargs):
            raise AssertionError("conditional request must not be made without a server validator")

    monkeypatch.setattr(audit, "CrawlEngine", lambda config: OrdinaryEngine())
    monkeypatch.setattr(audit, "_ConditionalCrawlEngine", NeverConditional)
    observations = asyncio.run(
        audit.collect_conditional_get_evidence([_candidate()], allowed_hosts=["example.test"], scope_predicate=None)
    )
    assert observations[0]["outcome"] == "not_testable_no_server_validator"
    coverage = audit.conditional_get_report(observations, candidate_population=1, sample_size=1)[0]
    assert coverage["state"] == "not_testable"
    assert coverage["not_testable_count"] == 1
    assert coverage["not_modified_304_rate"] is None


def test_unchanged_200_after_real_validator_is_an_efficiency_candidate(monkeypatch):
    class OrdinaryEngine:
        async def crawl(self, url, *, purpose):
            return _result(
                200,
                headers={"ETag": 'W/"opaque"', "Last-Modified": "Wed, 21 Oct 2015 07:28:00 GMT"},
                body="page",
            )

        async def close(self):
            return None

    seen_headers = {}

    class ConditionalEngine:
        def __init__(self, config, url, headers):
            seen_headers.update(headers)

        async def crawl(self, url, *, purpose):
            return _result(200, headers={"ETag": 'W/"opaque"'}, body="page")

        async def close(self):
            return None

    monkeypatch.setattr(audit, "CrawlEngine", lambda config: OrdinaryEngine())
    monkeypatch.setattr(audit, "_ConditionalCrawlEngine", ConditionalEngine)
    observations = asyncio.run(
        audit.collect_conditional_get_evidence([_candidate()], allowed_hosts=["example.test"], scope_predicate=None)
    )
    assert seen_headers == {
        "If-None-Match": 'W/"opaque"',
        "If-Modified-Since": "Wed, 21 Oct 2015 07:28:00 GMT",
    }
    assert observations[0]["record_type"] == "candidate"
    assert observations[0]["outcome"] == "validator_not_honored_unchanged_200"
    assert observations[0]["representation_equal"] is True


def test_changed_200_is_not_promoted_to_validator_defect(monkeypatch):
    class OrdinaryEngine:
        async def crawl(self, url, *, purpose):
            return _result(200, headers={"ETag": '"r1"'}, body="old")

        async def close(self):
            return None

    class ConditionalEngine:
        def __init__(self, config, url, headers):
            assert headers == {"If-None-Match": '"r1"'}

        async def crawl(self, url, *, purpose):
            return _result(200, headers={"ETag": '"r2"'}, body="new")

        async def close(self):
            return None

    monkeypatch.setattr(audit, "CrawlEngine", lambda config: OrdinaryEngine())
    monkeypatch.setattr(audit, "_ConditionalCrawlEngine", ConditionalEngine)
    observations = asyncio.run(
        audit.collect_conditional_get_evidence([_candidate()], allowed_hosts=["example.test"], scope_predicate=None)
    )
    assert observations[0]["record_type"] == "observation"
    assert observations[0]["outcome"] == "changed_or_uncomparable_200_no_validator_defect"


def test_304_contributes_to_eligible_validator_rate(monkeypatch):
    class OrdinaryEngine:
        async def crawl(self, url, *, purpose):
            return _result(200, headers={"ETag": '"r1"'}, body="old")

        async def close(self):
            return None

    class ConditionalEngine:
        def __init__(self, config, url, headers):
            pass

        async def crawl(self, url, *, purpose):
            return _result(304, headers={"ETag": '"r1"'})

        async def close(self):
            return None

    monkeypatch.setattr(audit, "CrawlEngine", lambda config: OrdinaryEngine())
    monkeypatch.setattr(audit, "_ConditionalCrawlEngine", ConditionalEngine)
    observations = asyncio.run(
        audit.collect_conditional_get_evidence([_candidate()], allowed_hosts=["example.test"], scope_predicate=None)
    )
    coverage = audit.conditional_get_report(observations, candidate_population=1, sample_size=1)[0]
    assert observations[0]["outcome"] == "not_modified_304"
    assert coverage["not_modified_304_rate"] == 1.0
    assert coverage["validator_eligible_count"] == 1
