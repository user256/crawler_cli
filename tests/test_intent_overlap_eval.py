"""End-to-end eval fixture for the intent-overlap pipeline (ticket 081).

Serves a small fixture site, runs the FULL pipeline against a real Postgres
store — crawl -> signatures -> (deterministic) embeddings -> hreflang groups ->
intent-overlap — and diffs the structured result against a committed golden.
Fails on drift. Uses a deterministic content-hashed embedder instead of a real
model so it is reproducible with no download (the embedding provider seam is
covered separately in test_embeddings_local).

Integration-marked: needs CRAWLER_CLI_TEST_DSN.
"""

from __future__ import annotations

import hashlib
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

np = pytest.importorskip("numpy")
import pytest_asyncio  # noqa: E402

from crawler_cli.config import CrawlConfig  # noqa: E402
from crawler_cli.engine import CrawlEngine  # noqa: E402
from crawler_cli.persistence import AsyncpgStore  # noqa: E402

_DSN = os.environ.get("CRAWLER_CLI_TEST_DSN", "")
pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------
# Fixture site
# --------------------------------------------------------------------------


def _page(title, body, *, hreflang=None, noindex=False):
    alt = ""
    for code, href in hreflang or []:
        alt += f'<link rel="alternate" hreflang="{code}" href="{href}"/>'
    robots = '<meta name="robots" content="noindex">' if noindex else ""
    return (
        f"<html lang='en'><head><title>{title}</title>{robots}{alt}</head>"
        f"<body><h1>{title}</h1><article><p>{body}</p></article></body></html>"
    )


def _fixture_pages(base):
    widgets_body = "Blue widgets for sale. " * 40 + "Buy quality blue widgets online today."
    return {
        "/en/widgets": _page(
            "Blue Widgets",
            widgets_body,
            hreflang=[("en", f"{base}/en/widgets"), ("fr", f"{base}/fr/widgets")],
        ),
        # Near-identical to /en/widgets -> a duplicate.
        "/en/widgets-copy": _page("Blue Widgets Copy", widgets_body),
        # French alternate (mutual hreflang) -> same group as /en/widgets.
        "/fr/widgets": _page(
            "Widgets Bleus",
            "Widgets bleus a vendre. " * 40 + "Achetez des widgets bleus.",
            hreflang=[("en", f"{base}/en/widgets"), ("fr", f"{base}/fr/widgets")],
        ),
        # Unrelated unique content.
        "/en/gadgets": _page("Green Gadgets", "Green gadgets and gizmos. " * 40 + "Totally different topic."),
        # Excluded from pairing.
        "/en/hidden": _page("Hidden", "Secret page content. " * 40, noindex=True),
    }


@pytest_asyncio.fixture
async def fixture_site_and_store():
    if not _DSN:
        pytest.skip("CRAWLER_CLI_TEST_DSN not set")

    holder = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            base = f"http://127.0.0.1:{holder['port']}"
            pages = _fixture_pages(base)
            html = pages.get(self.path)
            if html is None:
                self.send_response(404)
                self.end_headers()
                return
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    holder["port"] = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    store = AsyncpgStore(_DSN)
    await store.initialize()
    await store.truncate_crawl_tables()
    yield holder["port"], store
    await store.truncate_crawl_tables()
    await store.close()
    srv.shutdown()


def _deterministic_encoder(texts):
    """Hashed bag-of-words -> normalized vector. Near-identical texts map to
    near-identical vectors, so duplicates are detectable without a real model."""
    dim = 64
    out = []
    for text in texts:
        vec = np.zeros(dim, dtype=np.float32)
        for word in str(text).lower().split():
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            vec[h % dim] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        out.append(vec.tolist())
    return out


# Committed golden: the structured outcome the pipeline must keep producing.
GOLDEN = {
    "pages_total": 5,
    "pages_excluded": 1,  # the noindex page
    "excluded_by_reason": {"noindex": 1},
    "embedded": 4,  # 5 crawled - 1 noindex
    "duplicate_pages": 2,  # widgets + widgets-copy
    "overlap_pairs": 1,  # the widgets<->widgets-copy pair
    "hreflang_groups": 1,  # en/widgets + fr/widgets
}


@pytest.mark.asyncio
async def test_intent_overlap_eval_fixture_matches_golden(fixture_site_and_store, tmp_path):
    from crawler_cli.intent_signature import backfill_intent_signatures
    from crawler_cli.embeddings import generate_signature_embeddings_for_store
    from crawler_cli.hreflang_groups import build_and_store_identity
    from crawler_cli.intent_overlap import run_intent_overlap

    port, store = fixture_site_and_store
    base = f"http://127.0.0.1:{port}"

    cfg = CrawlConfig(
        user_agent="eval/1.0",
        respect_robots_txt=False,
        same_host_only=True,
        discover_sitemaps=False,
        max_pages=0,
    )
    engine = CrawlEngine(cfg, store=store)
    await engine.crawl_list([f"{base}{p}" for p in _fixture_pages(base)])
    await engine.close()

    await backfill_intent_signatures(store)
    identity = await build_and_store_identity(store)
    await generate_signature_embeddings_for_store(store, model="eval-deterministic", encoder=_deterministic_encoder)

    run = await run_intent_overlap(store, out_dir=str(tmp_path), lang_split=False, run_args={"eval": True})
    s = run.result.summary

    got = {
        "pages_total": s["pages_total"],
        "pages_excluded": s["pages_excluded"],
        "excluded_by_reason": s["excluded_by_reason"],
        "embedded": s["embedded"],
        "duplicate_pages": s["duplicate_pages"],
        "overlap_pairs": s["overlap_pairs"],
        "hreflang_groups": identity.groups,
    }
    assert got == GOLDEN, f"eval drift:\n got={got}\n golden={GOLDEN}"

    # The six CSVs + manifest exist.
    for name in (
        "pages.csv",
        "overlap_pairs.csv",
        "clusters.csv",
        "hreflang_issues.csv",
        "url_variants.csv",
        "similarity_distribution.csv",
        "run_manifest.json",
    ):
        assert (tmp_path / name).exists(), f"missing {name}"
