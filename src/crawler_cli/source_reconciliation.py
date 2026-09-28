"""Multi-source discovery provenance reconciliation (ticket 262).

Joins one stored crawl run's internal link graph with XML sitemaps, a Search
Console URL export and a backlink URL export, and places every in-scope URL in
exactly one provenance segment. The classification is a pure function of its
inputs so the emitted JSON is deterministic for the same run and files.

URL identity is exact (surrounding whitespace aside), matching the existing
orphan / known-URL inventory contract: evidence is never silently rewritten, so
``/a`` and ``/a/`` remain different URLs.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from .csv_urls import load_urls_from_csv
from .orphan_sources import is_absolute_http_url
from .reports import _build_link_graph, _canonical_state, _json_list
from .sitemap import SitemapParser


SCHEMA_VERSION = 1

# Ticket 262's five named segments first, then the two remainders that make
# the partition exhaustive. Order is also the row sort order.
SEGMENTS = (
    "graph_and_sitemap",
    "sitemap_orphan",
    "unmapped_in_sitemap",
    "backlink_dead_end",
    "gsc_unlinked",
    "linked_not_in_sitemap_other",
    "crawled_unlinked_no_source",
)

SEGMENT_DEFINITIONS = {
    "graph_and_sitemap": "Listed in an XML sitemap and has at least one observed inlink from another crawled page.",
    "sitemap_orphan": "Listed in an XML sitemap but has no observed inlink from another crawled page.",
    "unmapped_in_sitemap": "Has observed inlinks, returned 200 and is indexable, but no sitemap lists it.",
    "backlink_dead_end": (
        "In the backlink export and not in a sitemap, and either returned 404/410 or has no observed inlink."
    ),
    "gsc_unlinked": "In the Search Console export, not in a sitemap or backlink dead end, with no observed inlink.",
    "linked_not_in_sitemap_other": (
        "Has observed inlinks and no sitemap lists it, but is not a 200 indexable page "
        "(redirect, error, noindex, or not fetched in this run)."
    ),
    "crawled_unlinked_no_source": "Crawled in this run (e.g. a seed) with no observed inlink and in no supplied source.",
}

# Source groups used for the overlap (Venn) counts. Labels map onto groups so
# that several sitemap inputs still count as one "sitemap" set.
SOURCE_GROUPS = ("link_graph", "sitemap", "gsc", "backlinks")
SITEMAP_LABELS = frozenset({"sitemap_file", "current_sitemap", "crawl_sitemap"})
_LABEL_GROUP = {
    "sitemap_file": "sitemap",
    "current_sitemap": "sitemap",
    "crawl_sitemap": "sitemap",
    "gsc_export": "gsc",
    "backlinks_export": "backlinks",
}

# Candidate URL-column names, matched ignoring case, whitespace and a BOM.
GSC_URL_COLUMNS = ("url", "top pages", "page", "pages", "landing page", "address")
BACKLINK_URL_COLUMNS = ("url", "target url", "page url", "target", "address")

_REJECTED_SAMPLE_SIZE = 5
_DEAD_STATUSES = frozenset({404, 410})


@dataclass(slots=True)
class SourceInput:
    """One labelled URL inventory joined against the crawl graph.

    ``urls`` maps each URL to the sorted source details (e.g. the sitemap
    document that listed it). ``metadata`` is emitted verbatim in ``sources``.
    """

    label: str
    urls: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _header_key(value: str) -> str:
    return value.replace("﻿", "").strip().lower()


def _rejected_sample(values: Iterable[str]) -> list[str]:
    sample: list[str] = []
    for value in values:
        parsed = urlsplit(value) if "://" in value else None
        try:
            has_credentials = bool(parsed and (parsed.username or parsed.password))
        except ValueError:
            has_credentials = False
        sample.append("[credentials redacted]" if has_credentials else value[:120])
        if len(sample) >= _REJECTED_SAMPLE_SIZE:
            break
    return sample


def load_url_list(
    path: str | Path,
    *,
    label: str,
    column: str | None = None,
    default_columns: Sequence[str] = ("url",),
) -> SourceInput:
    """Load a URL-list export (CSV with a URL column, or one URL per line).

    Delegates row reading to ``load_urls_from_csv``. The column is resolved
    here first, ignoring case, whitespace and a UTF-8 BOM, because that loader
    otherwise joins whole rows when the column name does not match exactly. A
    header row with no matching column is an error that lists the headers.

    This is the generic seam for ticket 256 (Semrush Organic Pages) and ticket
    217 (Ahrefs/Semrush backlink adapters): those loaders can return the same
    ``SourceInput`` with richer per-URL metrics in ``metadata``.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"URL export not found: {file_path}")
    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{file_path}: export is not UTF-8 (UTF-16 Ahrefs exports need re-saving as UTF-8 CSV)"
        ) from exc
    first_row = next(csv.reader(text.splitlines()), [])
    first_cell = first_row[0].replace("﻿", "").strip() if first_row else ""
    resolved_column = "url"
    headerless = not first_row or is_absolute_http_url(first_cell)
    if not headerless:
        wanted = [column] if column else list(default_columns)
        by_key = {_header_key(header): header.strip() for header in first_row}
        match = next((by_key[_header_key(name)] for name in wanted if _header_key(name) in by_key), None)
        if match is None:
            found = ", ".join(repr(header.replace("﻿", "").strip()) for header in first_row)
            requested = ", ".join(repr(name) for name in wanted)
            raise ValueError(f"{file_path}: no URL column matching {requested}; headers found: {found}")
        resolved_column = match
    values = load_urls_from_csv(file_path, column=resolved_column)
    accepted = sorted({value for value in values if is_absolute_http_url(value)})
    rejected = [value for value in values if not is_absolute_http_url(value)]
    return SourceInput(
        label=label,
        urls={url: [] for url in accepted},
        metadata={
            "label": label,
            "input": file_path.name,
            "input_sha256": _file_digest(file_path),
            "url_column": None if headerless else resolved_column.replace("﻿", ""),
            "row_count": len(values),
            "unique_url_count": len(accepted),
            "rejected_count": len(rejected),
            "rejected_sample": _rejected_sample(rejected),
            "complete": True,
        },
    )


def load_sitemap_files(paths: Sequence[str | Path]) -> SourceInput:
    """Parse local XML / text / gzip sitemap files with the crawler's ``SitemapParser``.

    Sitemap-index children are not fetched: they are counted as unresolved and
    the source is marked incomplete unless the child documents are also
    supplied as files.
    """
    parser = SitemapParser()
    urls: dict[str, set[str]] = {}
    documents: list[dict[str, object]] = []
    children: set[str] = set()
    rejected: list[str] = []
    for raw_path in paths:
        file_path = Path(raw_path)
        if not file_path.is_file():
            raise FileNotFoundError(f"sitemap file not found: {file_path}")
        body = file_path.read_bytes()
        try:
            document = parser.parse(file_path.name, body)
        except Exception as exc:  # noqa: BLE001 - defusedxml/gzip raise several types
            raise ValueError(f"{file_path}: could not parse sitemap ({type(exc).__name__})") from exc
        documents.append(
            {
                "input": file_path.name,
                "input_sha256": hashlib.sha256(body).hexdigest(),
                "kind": document.kind,
                "url_count": len(document.urls),
                "child_count": len(document.children),
            }
        )
        children.update(document.children)
        for item in document.urls:
            if is_absolute_http_url(item.loc):
                urls.setdefault(item.loc, set()).add(file_path.name)
            else:
                rejected.append(item.loc)
    unresolved = sorted(children)
    return SourceInput(
        label="sitemap_file",
        urls={url: sorted(details) for url, details in sorted(urls.items())},
        metadata={
            "label": "sitemap_file",
            "documents": sorted(documents, key=lambda row: (str(row["input"]), str(row["input_sha256"]))),
            "unique_url_count": len(urls),
            "rejected_count": len(rejected),
            "rejected_sample": _rejected_sample(rejected),
            "unresolved_index_child_count": len(unresolved),
            "unresolved_index_children_sample": unresolved[:_REJECTED_SAMPLE_SIZE],
            "complete": not unresolved,
        },
    )


def crawl_sitemap_source(rows: Sequence[Mapping[str, object]]) -> SourceInput:
    """Build the sitemap source from ticket 013 ``url_sources`` provenance rows."""
    urls: dict[str, set[str]] = {}
    for row in rows:
        url = str(row.get("url") or "").strip()
        if url and is_absolute_http_url(url):
            detail = str(row.get("detail") or "")
            urls.setdefault(url, set()).update({detail} if detail else set())
    return SourceInput(
        label="crawl_sitemap",
        urls={url: sorted(details) for url, details in sorted(urls.items())},
        metadata={
            "label": "crawl_sitemap",
            "unique_url_count": len(urls),
            "scope": "url_sources sitemap provenance (database-wide) intersected with the selected run's frontier",
            "qualification": (
                "records sitemap discovery by the crawl; a URL first seen in a sitemap by an earlier run in the "
                "same database and re-queued by this run still counts"
            ),
            "complete": None,
        },
    )


def current_sitemap_source(graph_urls: Sequence[Mapping[str, str]], coverage: Mapping[str, object]) -> SourceInput:
    """Build the sitemap source from ``collect_current_site_files`` graph-join rows."""
    urls: dict[str, set[str]] = {}
    for row in graph_urls:
        url = str(row.get("url") or "").strip()
        if url:
            detail = str(row.get("source_sitemap") or "")
            urls.setdefault(url, set()).update({detail} if detail else set())
    return SourceInput(
        label="current_sitemap",
        urls={url: sorted(details) for url, details in sorted(urls.items())},
        metadata={
            "label": "current_sitemap",
            "unique_url_count": len(urls),
            "observed_at": coverage.get("observed_at"),
            "sitemap_document_count": coverage.get("sitemap_document_count"),
            "complete": coverage.get("complete"),
        },
    )


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value)) if value is not None else None
    except ValueError:
        return None


def _coverage(context: Mapping[str, object], graph_complete: bool, html_count: int) -> dict[str, object]:
    queued = _as_int(context.get("frontier_queued")) or 0
    pending = _as_int(context.get("frontier_pending")) or 0
    unfetched = queued + pending
    run_status = str(context.get("run_status") or "unknown")
    complete = graph_complete and run_status == "complete" and unfetched == 0
    reasons = []
    if run_status != "complete":
        reasons.append(f"crawl run status is {run_status!r}")
    if unfetched:
        reasons.append(f"{unfetched} discovered URLs were never fetched")
    if not graph_complete:
        reasons.append("link extraction or render discovery is incomplete for at least one crawled page")
    return {
        "run_status": run_status,
        "crawled_html_count": html_count,
        "frontier_done": _as_int(context.get("frontier_done")),
        "frontier_queued": queued,
        "frontier_pending": pending,
        "discovered_unfetched_count": unfetched,
        "link_graph_complete": graph_complete,
        "complete": complete,
        "unlinked_label": "orphan_complete_graph" if complete else "no_inlinks_from_crawled_pages",
        "statement": (
            "The crawl fetched every discovered URL and extracted links from every crawled page; "
            "URLs without inlinks have no internal links in the crawled site."
            if complete
            else "Crawl coverage is incomplete ("
            + "; ".join(reasons)
            + "). 'sitemap_orphan', 'gsc_unlinked' and unlinked 'backlink_dead_end' rows mean "
            "'no inlinks from crawled pages', not confirmed orphans."
        ),
    }


def _action(segment: str, row: Mapping[str, object], coverage_complete: bool) -> str:
    status = _as_int(row.get("http_status"))
    indexable = row.get("overall_indexable")
    canonical = row.get("canonical_state")
    crawled = row.get("crawled") is True
    verify = "" if coverage_complete else " Crawl coverage is incomplete: confirm with a fuller crawl first."
    if segment == "graph_and_sitemap":
        if not crawled:
            return "Linked and in sitemap but not fetched in this run; recrawl to confirm status."
        if status != 200:
            return "Sitemap lists a non-200 URL; replace it with the final 200 URL or remove it."
        if indexable is False:
            return "Sitemap lists a non-indexable URL; remove it or make the page indexable."
        if canonical == "noncanonical":
            return "Sitemap lists a non-canonical URL; list the declared canonical instead."
        return "None: linked internally and declared in the sitemap."
    if segment == "sitemap_orphan":
        if crawled and status not in (None, 200):
            return "Sitemap lists a non-200 URL with no internal links; remove it from the sitemap." + verify
        return "Add internal links to this page, or remove it from the sitemap if it should not rank." + verify
    if segment == "unmapped_in_sitemap":
        if canonical == "noncanonical":
            return "Indexable but declares another canonical; review the canonical before adding it to the sitemap."
        return "Add this indexable, internally linked page to the XML sitemap."
    if segment == "backlink_dead_end":
        if status in _DEAD_STATUSES:
            return "Backlinked URL returns 404/410; 301-redirect it to the closest live equivalent."
        if not crawled:
            return "Backlinked URL is outside the crawl graph and sitemaps; fetch it to confirm status." + verify
        return "Backlinked URL has no internal links and is not in a sitemap; link it or redirect it." + verify
    if segment == "gsc_unlinked":
        return (
            "Google knows this URL but the site does not link it; link it, redirect it, or return 404/410 if retired."
            + verify
        )
    if segment == "linked_not_in_sitemap_other":
        if not crawled:
            return "Linked internally but not fetched in this run; recrawl to classify."
        if status is not None and 300 <= status < 400:
            return "Internal links point at a redirect; update them to the final URL."
        if status is not None and status >= 400:
            return "Internal links point at an error URL; fix or remove those links."
        return "Linked but not indexable; no sitemap entry needed unless it should be indexable."
    return "Crawled with no inlinks and in no supplied source; confirm whether it should be linked." + verify


def _segment(*, linked: bool, in_sitemap: bool, in_gsc: bool, in_backlinks: bool, row: Mapping[str, object]) -> str:
    statuses = {row.get("http_status"), row.get("final_status")}
    dead = bool(statuses & _DEAD_STATUSES)
    if in_sitemap:
        return "graph_and_sitemap" if linked else "sitemap_orphan"
    if linked and row.get("http_status") == 200 and row.get("overall_indexable") is True:
        return "unmapped_in_sitemap"
    if in_backlinks and (dead or not linked):
        return "backlink_dead_end"
    if in_gsc and not linked:
        return "gsc_unlinked"
    if linked:
        return "linked_not_in_sitemap_other"
    return "crawled_unlinked_no_source"


def reconcile_sources(
    *,
    run_id: str,
    context: Mapping[str, object],
    pages: Sequence[Mapping[str, object]],
    sources: Sequence[SourceInput],
) -> dict[str, object]:
    """Partition every in-scope URL into exactly one provenance segment.

    ``pages`` are the selected run's snapshots (any kind); HTML rows form the
    same-run link graph through ``reports._build_link_graph``. A URL is
    "linked" when another crawled HTML page links to it. Supplied URLs whose
    host is not a crawled HTML host are out of scope: they are listed
    separately and never join the graph.
    """
    html_pages = [dict(page) for page in pages if page.get("kind") == "html"]
    crawled_hosts = {urlsplit(str(page["url"])).hostname for page in html_pages}
    by_url = {str(page["url"]): page for page in pages}

    labels_by_url: dict[str, set[str]] = {}
    details_by_url: dict[str, dict[str, list[str]]] = {}
    out_of_scope: dict[str, set[str]] = {}
    for source in sources:
        for url, details in source.urls.items():
            if urlsplit(url).hostname not in crawled_hosts:
                out_of_scope.setdefault(url, set()).add(source.label)
                continue
            labels_by_url.setdefault(url, set()).add(source.label)
            if details:
                details_by_url.setdefault(url, {})[source.label] = sorted(details)

    graph = _build_link_graph(html_pages, known_urls=[{"url": url} for url in sorted(labels_by_url)])
    inbound: dict[str, int] = graph["inbound"]
    coverage = _coverage(context, bool(graph["complete"]), len(html_pages))

    universe = sorted({str(page["url"]) for page in html_pages} | set(labels_by_url))
    rows: list[dict[str, object]] = []
    for url in universe:
        page = by_url.get(url)
        labels = labels_by_url.get(url, set())
        inlinks = inbound.get(url, 0)
        linked = inlinks > 0
        canonicals = _json_list(page.get("canonical_urls_json")) if page else []
        initial = _as_int(page.get("initial_status_code")) if page else None
        final = _as_int(page.get("final_status_code")) if page else None
        row: dict[str, object] = {
            "url": url,
            "crawled": page is not None,
            "content_kind": page.get("kind") if page else None,
            "observed_inlink_count": inlinks,
            "linkage": "observed_inlinks" if linked else coverage["unlinked_label"],
            "http_status": initial if initial is not None else final,
            "final_status": final,
            "overall_indexable": page.get("overall_indexable") if page else None,
            "canonical_state": _canonical_state(url, page.get("canonical_urls_json")) if page else "unknown",
            "canonical_url": str(canonicals[0]) if canonicals else None,
        }
        in_sitemap = bool(labels & SITEMAP_LABELS)
        groups = {_LABEL_GROUP[label] for label in labels if label in _LABEL_GROUP}
        if linked:
            groups.add("link_graph")
        segment = _segment(
            linked=linked,
            in_sitemap=in_sitemap,
            in_gsc="gsc_export" in labels,
            in_backlinks="backlinks_export" in labels,
            row=row,
        )
        row["segment"] = segment
        row["discovery_sources"] = [group for group in SOURCE_GROUPS if group in groups]
        row["source_labels"] = sorted(labels)
        row["source_details"] = details_by_url.get(url, {})
        row["recommended_action"] = _action(segment, row, bool(coverage["complete"]))
        rows.append(row)

    order = {segment: index for index, segment in enumerate(SEGMENTS)}
    rows.sort(key=lambda item: (order[str(item["segment"])], str(item["url"])))
    segment_counts = {segment: 0 for segment in SEGMENTS}
    overlap: dict[str, int] = {}
    for row in rows:
        segment_counts[str(row["segment"])] += 1
        key = "+".join(row["discovery_sources"]) or "crawled_only"  # type: ignore[arg-type]
        overlap[key] = overlap.get(key, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "report": "reconcile-sources",
        "run_id": run_id,
        "coverage": coverage,
        "sources": sorted((dict(source.metadata) for source in sources), key=lambda item: str(item.get("label"))),
        "segment_definitions": dict(SEGMENT_DEFINITIONS),
        "summary": {
            "total_urls": len(rows),
            "segment_counts": segment_counts,
            "source_overlap_counts": dict(sorted(overlap.items())),
            "out_of_scope_count": len(out_of_scope),
        },
        "urls": rows,
        "out_of_scope": [
            {"url": url, "source_labels": sorted(labels), "reason": "host_not_crawled_in_run"}
            for url, labels in sorted(out_of_scope.items())
        ],
    }


CSV_FIELDS = (
    "segment",
    "url",
    "discovery_sources",
    "source_labels",
    "crawled",
    "observed_inlink_count",
    "linkage",
    "http_status",
    "final_status",
    "overall_indexable",
    "canonical_state",
    "canonical_url",
    "recommended_action",
)


def write_reconciliation_csv(path: str | Path, rows: Sequence[Mapping[str, object]]) -> None:
    """Write the per-URL breakdown as CSV; list cells are joined with ``|``."""
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    name: "|".join(str(item) for item in value)
                    if isinstance((value := row.get(name)), list)
                    else ("" if value is None else value)
                    for name in CSV_FIELDS
                }
            )
