#!/usr/bin/env python3
"""Generate crawler_gui/sample-data.json for the static UI prototype."""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).with_name("sample-data.json")

SEED_URL = "https://whiskipedia.com/"

PAGES_SPEC = [
    # address, status, indexable, title, title_len, meta, meta_len, h1, h1_count, ttfb_ms, ctype
    ("/", 200, True, "Whiskipedia — The Whisky Encyclopedia", 38, "Explore distilleries, regions, and tasting notes.", 48, "Whiskipedia", 1, 412, "text/html"),
    ("/scotland/", 200, True, "Scotch Whisky Regions", 22, "Highland, Speyside, Islay, Lowland, and Campbeltown.", 52, "Scotch Regions", 1, 388, "text/html"),
    ("/scotland/islay/", 200, True, "Islay Whisky", 12, "Peated malts from the Queen of the Hebrides.", 45, "Islay", 1, 501, "text/html"),
    ("/scotland/speyside/", 200, True, "Speyside Distilleries Guide | Whiskipedia Long Title That Warns", 62, "A short meta.", 13, "Speyside", 1, 467, "text/html"),
    ("/distilleries/ardbeg/", 200, True, "Ardbeg Distillery", 17, "History, expressions, and visitor info for Ardbeg.", 50, None, 0, 572, "text/html"),
    ("/distilleries/lagavulin/", 200, True, "Lagavulin Distillery", 20, "16 Year Old and beyond — Islay classic.", 40, "Lagavulin", 1, 445, "text/html"),
    ("/blog/", 200, True, "Whisky Blog", 11, None, 0, "Blog", 1, 390, "text/html"),
    ("/blog/peat-levels/", 200, True, "Understanding Peat Levels in Malt Whisky", 41, "PPM, phenolics, and how peat shapes flavour.", 45, "Peat Levels", 1, 610, "text/html"),
    ("/search?q=islay", 200, False, "Search: islay", 13, "Search results for islay.", 25, "Search", 1, 320, "text/html"),
    ("/old-page/", 301, True, "", 0, None, 0, None, 0, 180, "text/html"),
    ("/gone/", 404, False, "Page not found", 14, None, 0, "Not found", 1, 95, "text/html"),
    ("/assets/logo.png", 200, False, "", 0, None, 0, None, 0, 55, "image/png"),
    ("/robots.txt", 200, False, "", 0, None, 0, None, 0, 40, "text/plain"),
    ("/sitemap.xml", 200, False, "", 0, None, 0, None, 0, 120, "application/xml"),
    ("/japan/", 200, True, "Japanese Whisky", 15, "From Yamazaki to Chichibu — Japanese whisky overview.", 54, "Japanese Whisky", 2, 489, "text/html"),
    ("/usa/bourbon/", 200, True, "Bourbon Guide", 13, "Straight bourbon, rye, and American whiskey primers.", 53, "Bourbon", 1, 433, "text/html"),
    ("/account/login/", 200, False, "Login", 5, None, 0, "Sign in", 1, 210, "text/html"),
    ("/api/health", 200, False, "", 0, None, 0, None, 0, 28, "application/json"),
    ("/ireland/", 503, False, "Temporarily unavailable", 23, None, 0, "Unavailable", 1, 8000, "text/html"),
    ("/scotland/highland/", 200, True, "Highland Whisky", 15, "Vast region covering coastal and inland malts.", 47, "Highlands", 1, 455, "text/html"),
]


def abs_url(path: str) -> str:
    if path.startswith("http"):
        return path
    return SEED_URL.rstrip("/") + path


def status_label(code: int) -> str:
    return {
        200: "OK",
        301: "Moved Permanently",
        302: "Found",
        404: "Not Found",
        503: "Service Unavailable",
    }.get(code, "Unknown")


def build_pages() -> list[dict]:
    pages: list[dict] = []
    html_addrs = [abs_url(p[0]) for p in PAGES_SPEC if p[1] == 200 and p[10] == "text/html"]

    for i, spec in enumerate(PAGES_SPEC, start=1):
        path, code, indexable, title, tlen, meta, mlen, h1, h1c, ttfb, ctype = spec
        address = abs_url(path)
        redirect = abs_url("/scotland/islay/") if code == 301 else None

        # Fake a few inlinks from other HTML pages
        inlinks = []
        if ctype == "text/html" and code == 200:
            for src in html_addrs[:4]:
                if src != address:
                    inlinks.append(
                        {
                            "sourceUrl": src,
                            "anchorText": title or path.strip("/") or "Home",
                            "follow": True,
                            "hashlink": False,
                        }
                    )
                    if len(inlinks) >= 3:
                        break

        outlinks = []
        if path == "/":
            outlinks = [
                {"targetUrl": abs_url("/scotland/"), "anchorText": "Scotland", "follow": True, "external": False},
                {"targetUrl": abs_url("/japan/"), "anchorText": "Japan", "follow": True, "external": False},
                {"targetUrl": "https://example.com/partner", "anchorText": "Partner", "follow": True, "external": True},
            ]
        elif path.startswith("/scotland"):
            outlinks = [
                {"targetUrl": abs_url("/scotland/islay/"), "anchorText": "Islay", "follow": True, "external": False},
                {"targetUrl": abs_url("/distilleries/ardbeg/"), "anchorText": "Ardbeg", "follow": True, "external": False},
            ]

        indexability = "Indexable" if indexable else "Non-Indexable"
        index_status = ""
        if not indexable:
            if "search" in path or "login" in path:
                index_status = "noindex"
            elif ctype.startswith("image/") or ctype.startswith("text/plain") or "xml" in ctype or "json" in ctype:
                index_status = "Non-HTML"
            elif code >= 400:
                index_status = f"HTTP {code}"

        pages.append(
            {
                "id": i,
                "address": address,
                "path": path,
                "contentType": ctype,
                "statusCode": code,
                "status": status_label(code),
                "indexability": indexability,
                "indexabilityStatus": index_status,
                "title": title,
                "titleLength": tlen,
                "metaDescription": meta,
                "metaDescriptionLength": mlen,
                "h1": h1,
                "h1Count": h1c,
                "responseTimeMs": ttfb,
                "redirectUrl": redirect,
                "internalInlinks": len(inlinks),
                "externalInlinks": 0 if ctype == "text/html" else 0,
                "wordCount": max(0, (tlen or 0) * 12 + (mlen or 0) * 3),
                "canonical": address if code == 200 and ctype == "text/html" else None,
                "robots": "noindex, follow" if not indexable and ctype == "text/html" and code == 200 else "index, follow",
                "headers": {
                    "content-type": ctype,
                    "server": "nginx",
                    "x-robots-tag": "noindex" if index_status == "noindex" else None,
                    "cache-control": "public, max-age=600",
                },
                "structuredData": (
                    [{"type": "Organization", "name": "Whiskipedia"}, {"type": "WebSite", "name": "Whiskipedia"}]
                    if path == "/"
                    else ([{"type": "Article", "headline": title}] if path.startswith("/blog/") and title else [])
                ),
                "inlinks": inlinks,
                "outlinks": outlinks,
                "categoryHints": _hints(path, code, ctype, indexable, title, meta, h1c),
            }
        )
    return pages


def _hints(path, code, ctype, indexable, title, meta, h1c) -> list[str]:
    hints = ["internal"]
    if ctype != "text/html":
        hints.append("url")
    if code != 200:
        hints.append("response-codes")
    if not indexable:
        hints.append("directives")
    if ctype == "text/html":
        hints.extend(["page-titles", "meta-description", "h1", "content", "canonicals", "links"])
        if path.startswith("/blog"):
            hints.append("content")
    if "sitemap" in path:
        hints.append("sitemaps")
    if ctype.startswith("image/"):
        hints.append("images")
    if not title and ctype == "text/html" and code == 200:
        hints.append("page-titles")
    if meta is None and ctype == "text/html" and code == 200:
        hints.append("meta-description")
    if h1c == 0 and ctype == "text/html" and code == 200:
        hints.append("h1")
    return sorted(set(hints))


def overview_from_pages(pages: list[dict]) -> dict:
    total = len(pages)
    indexable = sum(1 for p in pages if p["indexability"] == "Indexable")
    non = total - indexable
    https = sum(1 for p in pages if p["address"].startswith("https://"))
    html = sum(1 for p in pages if p["contentType"] == "text/html")
    c2 = sum(1 for p in pages if 200 <= p["statusCode"] < 300)
    c3 = sum(1 for p in pages if 300 <= p["statusCode"] < 400)
    c4 = sum(1 for p in pages if 400 <= p["statusCode"] < 500)
    c5 = sum(1 for p in pages if p["statusCode"] >= 500)
    missing_title = sum(1 for p in pages if p["contentType"] == "text/html" and p["statusCode"] == 200 and not p["title"])
    missing_meta = sum(1 for p in pages if p["contentType"] == "text/html" and p["statusCode"] == 200 and not p["metaDescription"])
    missing_h1 = sum(1 for p in pages if p["contentType"] == "text/html" and p["statusCode"] == 200 and p["h1Count"] == 0)

    def pct(n: int) -> float:
        return round(100.0 * n / total, 1) if total else 0.0

    return {
        "summary": [
            {"label": "Total URLs Crawled", "count": total, "pct": 100.0},
            {"label": "Indexable", "count": indexable, "pct": pct(indexable)},
            {"label": "Non-Indexable", "count": non, "pct": pct(non)},
            {"label": "HTTPS", "count": https, "pct": pct(https)},
            {"label": "HTTP", "count": total - https, "pct": pct(total - https)},
        ],
        "responseCodes": [
            {"label": "2xx OK", "count": c2, "pct": pct(c2), "tone": "ok"},
            {"label": "3xx Redirect", "count": c3, "pct": pct(c3), "tone": "warn"},
            {"label": "4xx Client Error", "count": c4, "pct": pct(c4), "tone": "bad"},
            {"label": "5xx Server Error", "count": c5, "pct": pct(c5), "tone": "bad"},
        ],
        "content": [
            {"label": "HTML", "count": html, "pct": pct(html)},
            {"label": "Missing Title", "count": missing_title, "pct": pct(missing_title), "tone": "warn" if missing_title else "ok"},
            {"label": "Missing Meta Description", "count": missing_meta, "pct": pct(missing_meta), "tone": "warn" if missing_meta else "ok"},
            {"label": "Missing H1", "count": missing_h1, "pct": pct(missing_h1), "tone": "warn" if missing_h1 else "ok"},
        ],
    }


def build_fixture() -> dict:
    pages = build_pages()
    total = len(pages)
    data = {
        "meta": {
            "brand": "crawler_cli",
            "uiName": "crawler_gui",
            "prototype": True,
            "note": "Static fixture for crawler_gui layout exploration. Not live API output.",
        },
        "nav": [
            {"id": "dashboard", "label": "Dashboard", "enabled": False},
            {"id": "crawler", "label": "Crawler", "enabled": True},
            {"id": "lighthouse", "label": "Lighthouse", "enabled": False},
            {"id": "schedule", "label": "Schedule", "enabled": True},
        ],
        "categoryTabs": [
            {"id": "internal", "label": "Internal"},
            {"id": "external", "label": "External"},
            {"id": "security", "label": "Security"},
            {"id": "response-codes", "label": "Response Codes"},
            {"id": "url", "label": "URL"},
            {"id": "page-titles", "label": "Page Titles"},
            {"id": "meta-description", "label": "Meta Description"},
            {"id": "h1", "label": "H1"},
            {"id": "h2", "label": "H2"},
            {"id": "content", "label": "Content"},
            {"id": "images", "label": "Images"},
            {"id": "canonicals", "label": "Canonicals"},
            {"id": "directives", "label": "Directives"},
            {"id": "links", "label": "Links"},
            {"id": "structured-data", "label": "Structured Data"},
            {"id": "javascript", "label": "JavaScript"},
            {"id": "hreflang", "label": "Hreflang"},
            {"id": "sitemaps", "label": "Sitemaps"},
        ],
        "sidebarTabs": [
            {"id": "overview", "label": "Overview"},
            {"id": "issues", "label": "Issues"},
            {"id": "structure", "label": "Site Structure"},
            {"id": "live", "label": "Live"},
        ],
        "detailTabs": [
            {"id": "url-details", "label": "URL Details"},
            {"id": "inlinks", "label": "Inlinks"},
            {"id": "outlinks", "label": "Outlinks"},
            {"id": "serp", "label": "SERP Snippet"},
            {"id": "headers", "label": "HTTP Headers"},
            {"id": "structured-data", "label": "Structured Data"},
        ],
        "crawl": {
            "id": "crawl_whiskipedia_demo",
            "url": SEED_URL,
            "mode": "Spider",
            "status": "complete",
            "statusLabel": "Spider Mode: Complete",
            "progress": {"completed": total, "total": total, "pct": 100.0, "remaining": 0},
            "speed": {"average": 2.3, "current": 0.0},
            "startedAt": "2026-07-15T14:02:11Z",
            "finishedAt": "2026-07-15T14:08:04Z",
        },
        "history": [
            {
                "id": "crawl_whiskipedia_demo",
                "domain": "whiskipedia.com",
                "url": SEED_URL,
                "status": "complete",
                "viewing": True,
                "urls": total,
                "htmlStored": total - 3,
                "date": "2026-07-15",
            },
            {
                "id": "crawl_ibiza_20260706",
                "domain": "ibizasummervillas.com",
                "url": "https://www.ibizasummervillas.com/",
                "status": "complete",
                "viewing": False,
                "urls": 412,
                "htmlStored": 390,
                "date": "2026-07-06",
            },
            {
                "id": "crawl_thompsons_20260715",
                "domain": "thompsons-scotland.co.uk",
                "url": "https://www.thompsons-scotland.co.uk/",
                "status": "complete",
                "viewing": False,
                "urls": 3942,
                "htmlStored": 0,
                "date": "2026-07-15",
            },
        ],
        "configDefaults": {
            "maxPages": 200,
            "concurrency": 5,
            "delay": 0.2,
            "respectRobots": True,
            "useJs": False,
            "ignoreNoFollow": False,
            "crawlImages": False,
            "userAgent": "Mozilla/5.0 (compatible; crawler_gui/1.0; +https://example.com/bot)",
            "backend": "aiohttp",
        },
        "overview": overview_from_pages(pages),
        "issues": [
            {"severity": "high", "label": "5xx responses", "count": sum(1 for p in pages if p["statusCode"] >= 500)},
            {"severity": "medium", "label": "Missing H1", "count": sum(1 for p in pages if p["contentType"] == "text/html" and p["statusCode"] == 200 and p["h1Count"] == 0)},
            {"severity": "medium", "label": "Missing meta description", "count": sum(1 for p in pages if p["contentType"] == "text/html" and p["statusCode"] == 200 and not p["metaDescription"])},
            {"severity": "low", "label": "Title length warnings", "count": sum(1 for p in pages if p["titleLength"] and (p["titleLength"] < 15 or p["titleLength"] > 60))},
        ],
        "pages": pages,
    }

    return data


def render_fixture() -> str:
    return json.dumps(build_fixture(), indent=2) + "\n"


def main() -> None:
    expected = render_fixture()
    if "--check" in sys.argv[1:]:
        actual = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if actual != expected:
            print(f"{OUT} is out of date; run python3 {Path(__file__).name}", file=sys.stderr)
            raise SystemExit(1)
        print(f"{OUT} is current")
        return

    OUT.write_text(expected, encoding="utf-8")
    print(f"Wrote {OUT} ({len(build_fixture()['pages'])} pages)")


if __name__ == "__main__":
    main()
