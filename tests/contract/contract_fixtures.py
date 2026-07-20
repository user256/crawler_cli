"""Deterministic fixture data for the portal integration contract suite (ticket 3344).

Everything in this module is chosen so that every derived value — sha256,
simhash64, Hamming distances, verdicts — is stable across runs and platforms.
The golden files under ``tests/contract/golden/`` are generated from these
fixtures and checked in; they ARE the frozen contract that downstream
consumers (the portal Migration Manager) build against.

Regenerating goldens: run the suite with ``CONTRACT_GOLDEN_UPDATE=1`` and
review the diff. A golden diff is a contract change and must be called out in
the changelog (and, if backward-incompatible, bump the schema version).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from crawler_cli.models import CrawlResult, DiscoveredLink, ExtractedContent, RobotsDirectives
from crawler_cli.serialization import serialize_crawl_result

GOLDEN_DIR = Path(__file__).parent / "golden"

# --- Deterministic page content ------------------------------------------------
# Chosen (and verified in test_hashing_contract.py) so that:
#   simhash_distance(HTML_ALPHA, HTML_ALPHA_NEAR) == 1  -> "near" at default threshold 4
#   simhash_distance(HTML_ALPHA, HTML_CHANGED)    == 27 -> "changed"
HTML_ALPHA = (
    "<html><body><h1>Alpha</h1><p>the quick brown fox jumps over the lazy dog "
    "near the quiet river bank today</p></body></html>"
)
HTML_ALPHA_NEAR = (
    "<html><body><h1>Alpha</h1><p>the quick brown fox jumps over the lazy dog "
    "near the quiet river bank tonight</p></body></html>"
)
HTML_CHANGED = (
    "<html><body><h1>Alpha</h1><p>a completely different page about industrial "
    "refrigeration compressors and maintenance schedules</p></body></html>"
)

# A fingerprint with the 64th bit set: exercises the signed BIGINT mapping.
# simhash64 of "<p>apple cedar ember</p>" — see test_hashing_contract.py.
SIMHASH_HIGHBIT_UNSIGNED = 11490990246049860681
SIMHASH_HIGHBIT_SIGNED = -6955753827659690935


def make_extracted(
    *,
    title: str | None,
    h1: str | None = None,
    meta_description: str | None = None,
    canonical: str | None = None,
    word_count: int = 18,
) -> ExtractedContent:
    return ExtractedContent(
        title=title,
        meta_description=meta_description,
        meta_robots=RobotsDirectives(),
        x_robots_tag=RobotsDirectives(),
        canonical=canonical,
        x_canonical=None,
        hreflang_links=[],
        html_lang="en",
        headings={"h1": [h1] if h1 else [], "h2": []},
        text="",
        word_count=word_count,
        metadata={},
    )


def make_result(
    requested: str,
    final: str,
    *,
    status: int = 200,
    chain: list[dict[str, object]] | None = None,
    raw_html: str | None = HTML_ALPHA,
    extracted: ExtractedContent | None = None,
    sha256: str | None = None,
    simhash: int | None = None,
    hash_content: bool = True,
    links: list[DiscoveredLink] | None = None,
) -> CrawlResult:
    """Build a deterministic CrawlResult.

    With ``hash_content`` (default), sha256/simhash are computed from
    ``raw_html`` exactly the way ``--content-hashing`` does during a crawl.
    Pass explicit ``sha256``/``simhash`` with ``hash_content=False`` to model
    store-loaded rows that carry stored hashes but no raw HTML.
    """
    from crawler_cli.hashing import sha256_hash, simhash64

    if hash_content and raw_html is not None:
        sha256 = sha256_hash(raw_html)
        simhash = simhash64(raw_html)
    return CrawlResult(
        requested_url=requested,
        final_url=final,
        status=status,
        headers={},
        content_type="text/html" if status != 404 else None,
        fetch_backend="aiohttp",
        extracted=extracted,
        raw_html=raw_html,
        content_hash_sha256=sha256,
        content_hash_simhash=simhash,
        discovered_links=links or [],
        redirect_chain=chain or [],
    )


def write_artifact(path: Path, results: list[CrawlResult]) -> None:
    """Write a saved-crawl JSON artifact in the documented dict format."""
    payload = {
        "schema_version": "crawler-cli/crawl-artifact/1",
        "mode": "list",
        "seed_urls": [],
        "results": [serialize_crawl_result(result) for result in results],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def assert_matches_golden(name: str, actual: str) -> None:
    """Byte-compare *actual* against the checked-in golden file.

    Set ``CONTRACT_GOLDEN_UPDATE=1`` to (re)write goldens instead — the diff is
    then reviewed and committed as an explicit contract change.
    """
    golden_path = GOLDEN_DIR / name
    if os.environ.get("CONTRACT_GOLDEN_UPDATE") == "1":
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(actual, encoding="utf-8")
        return
    assert golden_path.is_file(), f"missing golden file {golden_path}; run with CONTRACT_GOLDEN_UPDATE=1 to create it"
    expected = golden_path.read_text(encoding="utf-8")
    assert actual == expected, (
        f"output no longer matches frozen contract golden {name}; if this change is intentional, "
        "regenerate with CONTRACT_GOLDEN_UPDATE=1, review the diff, and document the contract change"
    )


# --- compare-urls fixture site -------------------------------------------------

OLD = "https://old.example"
NEW = "https://new.example"


def compare_urls_source_results() -> list[CrawlResult]:
    return [
        # /a: clean permanent redirect, identical content.
        make_result(
            f"{OLD}/a",
            f"{NEW}/a",
            chain=[{"url": f"{OLD}/a", "status": 301}],
            extracted=make_extracted(title="Alpha", h1="Alpha"),
        ),
        # /b: two-hop permanent chain, near-duplicate content.
        make_result(
            f"{OLD}/b",
            f"{NEW}/b",
            chain=[{"url": f"{OLD}/b", "status": 301}, {"url": f"{OLD}/b-interim", "status": 301}],
            extracted=make_extracted(title="Beta", h1="Beta"),
        ),
        # /c: temporary (302) redirect, changed content.
        make_result(
            f"{OLD}/c",
            f"{NEW}/c",
            chain=[{"url": f"{OLD}/c", "status": 302}],
            extracted=make_extracted(title="Gamma", h1="Gamma"),
        ),
        # /d: no redirect at all.
        make_result(
            f"{OLD}/d",
            f"{OLD}/d",
            extracted=make_extracted(title="Delta", h1="Delta"),
        ),
        # /e: redirects, but to the wrong target.
        make_result(
            f"{OLD}/e",
            f"{NEW}/elsewhere",
            chain=[{"url": f"{OLD}/e", "status": 301}],
            extracted=make_extracted(title="Epsilon", h1="Epsilon"),
        ),
        # /f: source errored (404) — no content available.
        make_result(
            f"{OLD}/f",
            f"{OLD}/f",
            status=404,
            raw_html=None,
            hash_content=False,
        ),
        # /g deliberately absent -> not_crawled.
        # /h: fine source redirect, but the target side is missing.
        make_result(
            f"{OLD}/h",
            f"{NEW}/h",
            chain=[{"url": f"{OLD}/h", "status": 301}],
            extracted=make_extracted(title="Eta", h1="Eta"),
        ),
        # /i: store-loaded row shape — stored hashes only, no raw HTML, simhash
        # in the SIGNED PostgreSQL BIGINT representation.
        make_result(
            f"{OLD}/i",
            f"{NEW}/i",
            chain=[{"url": f"{OLD}/i", "status": 301}],
            raw_html=None,
            hash_content=False,
            sha256="sha-source-i",
            simhash=SIMHASH_HIGHBIT_SIGNED,
            extracted=make_extracted(title="Iota", h1="Iota"),
        ),
    ]


def compare_urls_target_results() -> list[CrawlResult]:
    return [
        make_result(f"{NEW}/a", f"{NEW}/a", extracted=make_extracted(title="Alpha", h1="Alpha")),
        make_result(
            f"{NEW}/b",
            f"{NEW}/b",
            raw_html=HTML_ALPHA_NEAR,
            extracted=make_extracted(title="Beta", h1="Beta"),
        ),
        make_result(
            f"{NEW}/c",
            f"{NEW}/c",
            raw_html=HTML_CHANGED,
            extracted=make_extracted(title="Gamma Rewritten", h1="Gamma", word_count=11),
        ),
        make_result(f"{NEW}/d", f"{NEW}/d", extracted=make_extracted(title="Delta", h1="Delta")),
        make_result(f"{NEW}/e", f"{NEW}/e", extracted=make_extracted(title="Epsilon", h1="Epsilon")),
        make_result(f"{NEW}/f", f"{NEW}/f", extracted=make_extracted(title="Zeta", h1="Zeta")),
        # /h target deliberately absent -> content_verdict "missing".
        # /i: same page loaded with the UNSIGNED simhash representation.
        make_result(
            f"{NEW}/i",
            f"{NEW}/i",
            raw_html=None,
            hash_content=False,
            sha256="sha-target-i",
            simhash=SIMHASH_HIGHBIT_UNSIGNED,
            extracted=make_extracted(title="Iota", h1="Iota"),
        ),
    ]


PAIRS_CSV = (
    "source_url,target_url,note\n"
    f"{OLD}/a,{NEW}/a,homepage\n"
    f"{OLD}/b,{NEW}/b,\n"
    f"{OLD}/c,{NEW}/c,\n"
    f"{OLD}/d,{NEW}/d,\n"
    f"{OLD}/e,{NEW}/e,\n"
    f"{OLD}/f,{NEW}/f,\n"
    f"{OLD}/g,{NEW}/g,\n"
    f"{OLD}/h,{NEW}/h,\n"
    f"{OLD}/i,{NEW}/i,\n"
)


# --- compare (site-level) fixture site -----------------------------------------


def compare_baseline_results() -> list[CrawlResult]:
    return [
        make_result(
            f"{OLD}/",
            f"{OLD}/",
            extracted=make_extracted(title="Home", h1="Home", canonical=f"{OLD}/"),
            links=[DiscoveredLink(href=f"{OLD}/about", anchor_text="About", xpath="/html/body/a[1]", is_image=False)],
        ),
        make_result(
            f"{OLD}/about",
            f"{OLD}/about",
            extracted=make_extracted(title="About Us", h1="About", canonical=f"{OLD}/about"),
        ),
        make_result(
            f"{OLD}/gone",
            f"{OLD}/gone",
            extracted=make_extracted(title="Gone", h1="Gone"),
        ),
        make_result(
            f"{OLD}/old-path",
            f"{OLD}/new-path",
            chain=[{"url": f"{OLD}/old-path", "status": 301}],
            extracted=make_extracted(title="Moved", h1="Moved"),
        ),
    ]


def compare_candidate_results() -> list[CrawlResult]:
    return [
        make_result(
            f"{NEW}/",
            f"{NEW}/",
            raw_html=HTML_ALPHA_NEAR,
            extracted=make_extracted(title="Home", h1="Home", canonical=f"{NEW}/"),
            links=[
                DiscoveredLink(href=f"{NEW}/about", anchor_text="About", xpath="/html/body/a[1]", is_image=False),
                DiscoveredLink(href=f"{NEW}/fresh", anchor_text="Fresh", xpath="/html/body/a[2]", is_image=False),
            ],
        ),
        make_result(
            f"{NEW}/about",
            f"{NEW}/about",
            extracted=make_extracted(title="About Us, Rebranded", h1="About", canonical=f"{NEW}/about"),
        ),
        make_result(
            f"{NEW}/fresh",
            f"{NEW}/fresh",
            extracted=make_extracted(title="Fresh", h1="Fresh"),
        ),
        make_result(
            f"{NEW}/new-path",
            f"{NEW}/new-path",
            extracted=make_extracted(title="Moved", h1="Moved"),
        ),
    ]
