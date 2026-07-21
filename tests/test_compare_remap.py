"""Ticket 122: near-site compare with host remapping + simhash tolerance."""

from crawler_cli.comparison import compare_deep, comparison_rows
from crawler_cli.hashing import sha256_hash, simhash64
from crawler_cli.models import CrawlResult, DiscoveredLink, ExtractedContent, RobotsDirectives
from crawler_cli.remap import Remap


def _result(url, *, raw_html, canonical=None, title=None, links=None, requested=None):
    extracted = ExtractedContent(
        title=title,
        meta_description=None,
        meta_robots=RobotsDirectives(),
        x_robots_tag=RobotsDirectives(),
        canonical=canonical,
        x_canonical=None,
        hreflang_links=[],
        html_lang=None,
        headings={"h1": [], "h2": []},
        text="",
        word_count=len(raw_html.split()),
        metadata={},
    )
    return CrawlResult(
        requested_url=requested or url,
        final_url=url,
        status=200,
        headers={},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=extracted,
        raw_html=raw_html,
        content_hash_sha256=sha256_hash(raw_html),
        content_hash_simhash=simhash64(raw_html),
        discovered_links=links or [],
    )


DEV = "https://dev.example.com"
PROD = "https://example.com"


def _dev_prod_pair():
    # "/" — identical apart from the host mentioned in visible text, the
    # canonical, and an internal link. Pure host noise.
    home_dev = _result(
        f"{DEV}/",
        raw_html="<html><body><h1>Home</h1><p>Welcome to dev.example.com</p></body></html>",
        canonical=f"{DEV}/",
        links=[DiscoveredLink(f"{DEV}/about", "About", "/a", False)],
    )
    home_prod = _result(
        f"{PROD}/",
        raw_html="<html><body><h1>Home</h1><p>Welcome to example.com</p></body></html>",
        canonical=f"{PROD}/",
        links=[DiscoveredLink(f"{PROD}/about", "About", "/a", False)],
    )
    # "/about" — a real-length page whose only dev difference is a staging
    # banner: a small, material-looking change that should land as "near"
    # against a low threshold (not a hard "changed").
    about_para = (
        "We are a small independent studio based in Berlin building tools for "
        "photographers and small design teams around the world. Our mission is "
        "to make professional editing approachable without sacrificing depth or "
        "control for the people who rely on it every single day of the working week."
    )
    about_dev = _result(
        f"{DEV}/about",
        raw_html=f"<html><body><h1>About</h1><p>{about_para}</p>"
        "<div>Staging preview environment do not index this build</div></body></html>",
        canonical=f"{DEV}/about",
    )
    about_prod = _result(
        f"{PROD}/about",
        raw_html=f"<html><body><h1>About</h1><p>{about_para}</p></body></html>",
        canonical=f"{PROD}/about",
    )
    return [home_dev, about_dev], [home_prod, about_prod]


def test_remap_removes_host_derived_false_positives():
    baseline, candidate = _dev_prod_pair()
    remap = Remap.from_specs(["dev.example.com=example.com"])
    diff = compare_deep(baseline, candidate, remap=remap, simhash_threshold=4)

    # Host + link + canonical noise all gone.
    assert diff.missing_urls == []
    assert diff.new_urls == []
    assert diff.canonical_changes == {}
    assert diff.link_changes == {}

    rows = comparison_rows(diff)
    # content_verdict present on every row.
    assert all("content_verdict" in row for row in rows)
    verdicts = {row["path"]: row["content_verdict"] for row in rows}
    assert verdicts["/"] == "identical"
    assert verdicts["/about"] == "near"
    # No row is a hard "changed" once host noise is remapped away.
    assert all(row["content_verdict"] != "changed" for row in rows)


def test_near_row_distance_within_threshold():
    baseline, candidate = _dev_prod_pair()
    remap = Remap.from_specs(["dev.example.com=example.com"])
    diff = compare_deep(baseline, candidate, remap=remap, simhash_threshold=4)
    assert diff.content_verdicts["/about"] == "near"
    assert 0 < diff.simhash_distances["/about"] <= 4


def test_without_remap_host_noise_shows_up():
    baseline, candidate = _dev_prod_pair()
    diff = compare_deep(baseline, candidate)
    # Canonicals and links differ by host when not remapped.
    assert diff.canonical_changes
    assert diff.link_changes


def test_tight_threshold_promotes_near_to_changed():
    baseline, candidate = _dev_prod_pair()
    remap = Remap.from_specs(["dev.example.com=example.com"])
    diff = compare_deep(baseline, candidate, remap=remap, simhash_threshold=0)
    # With zero tolerance the banner difference is "changed", not "near".
    assert diff.content_verdicts["/about"] == "changed"


def test_missing_verdict_for_one_sided_paths():
    baseline, candidate = _dev_prod_pair()
    # Drop /about from candidate -> it exists only on baseline.
    diff = compare_deep(baseline, candidate[:1], remap=Remap.from_specs(["dev.example.com=example.com"]))
    rows = {row["path"]: row for row in comparison_rows(diff)}
    assert rows["/about"]["content_verdict"] == "missing"
    assert rows["/about"]["exists_on_candidate"] is False


# --- ticket 123: flag-less behaviour + remap fallback ----------------------


def _hashless(url, raw_html):
    """A page as crawled without --content-hashing: HTML but no stored hashes."""
    result = _result(url, raw_html=raw_html)
    result.content_hash_sha256 = None
    result.content_hash_simhash = None
    return result


def test_flagless_compare_on_hashless_artifacts_reports_no_mismatches():
    # Ticket 123 A: pre-122 behaviour. Without --replace, compare must not
    # implicitly re-hash raw_html — hash-less crawls yield no content signal.
    baseline = [_hashless("https://a/p", "<html><body><p>one</p></body></html>")]
    candidate = [_hashless("https://a/p", "<html><body><p>two totally different</p></body></html>")]
    diff = compare_deep(baseline, candidate)
    assert diff.content_hash_mismatches == {}


def test_flagless_compare_on_hashless_artifacts_verdict_is_unknown():
    # ...but the verdict says "unknown", not "identical": two hash-less pages
    # are not evidence of sameness.
    baseline = [_hashless("https://a/p", "<html><body><p>one</p></body></html>")]
    candidate = [_hashless("https://a/p", "<html><body><p>two totally different</p></body></html>")]
    diff = compare_deep(baseline, candidate)
    assert diff.content_verdicts["/p"] == "unknown"
    rows = comparison_rows(diff)
    assert rows[0]["content_verdict"] == "unknown"


def test_stored_hashes_still_drive_flagless_verdicts():
    baseline, candidate = _dev_prod_pair()
    diff = compare_deep(baseline, candidate)
    # Fixtures carry real stored hashes, so flag-less compare still verdicts.
    assert diff.content_verdicts["/"] == "changed"  # host differs in visible text
    assert diff.content_hash_mismatches


def test_remap_fallback_is_recorded_when_side_has_no_html():
    # Ticket 123 B: a store-loaded row (no raw_html, empty text) cannot be
    # remapped; the diff must record the fallback rather than pass silently.
    baseline, candidate = _dev_prod_pair()
    stripped = candidate[0]
    stripped.raw_html = None
    stripped.extracted.text = ""
    diff = compare_deep(baseline[:1], [stripped], remap=Remap.from_specs(["dev.example.com=example.com"]))
    assert diff.remap_fallback_paths == ["/"]


def test_no_remap_fallback_when_html_present():
    baseline, candidate = _dev_prod_pair()
    diff = compare_deep(baseline, candidate, remap=Remap.from_specs(["dev.example.com=example.com"]))
    assert diff.remap_fallback_paths == []
