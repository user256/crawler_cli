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
