"""CSV URL-pair compare and redirect validation (ticket 122, part C).

``compare-urls`` takes a migration mapping — ``source_url,target_url`` pairs from
a CSV — and, for each pair, validates that the source actually redirects to its
mapped target and diffs the two pages' content. Page data for each side is
resolved in order (saved JSON artifact → PostgreSQL store → live fetch), so an
existing crawl is reused where available and only the gaps are fetched fresh.

This module holds the pure, network-free pieces: CSV parsing, the redirect
verdict matrix, and per-pair row building. The CLI (`__main__._run_compare_urls`)
wires the resolvers (artifact/store/live) and I/O around it.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .comparison import DEFAULT_SIMHASH_THRESHOLD, content_comparison
from .models import CrawlResult
from .remap import Remap

# Redirect verdicts (ticket 122). Ordered by the precedence applied below.
REDIRECT_OK = "redirect_ok"
REDIRECT_WRONG_TARGET = "redirect_wrong_target"
REDIRECT_TEMPORARY = "redirect_temporary"
REDIRECT_CHAIN = "redirect_chain"
NO_REDIRECT = "no_redirect"
ERROR_STATUS = "error_status"
NOT_CRAWLED = "not_crawled"

_TEMPORARY_STATUSES = {302, 303, 307}
_MISMATCH_VERDICTS = {REDIRECT_WRONG_TARGET, NO_REDIRECT, ERROR_STATUS, NOT_CRAWLED}


@dataclass(slots=True)
class UrlPair:
    source_url: str
    target_url: str
    note: str | None = None


@dataclass(slots=True)
class PairParseResult:
    pairs: list[UrlPair]
    skipped: int
    skipped_reasons: list[str]


def normalize_url_for_match(url: str | None) -> str:
    """Light normalization for redirect-target equality (ticket 122).

    Lowercases scheme+host and drops a single trailing slash so ``…/path`` and
    ``…/path/`` match, and ``HTTP://Host`` matches ``http://host``. Deliberately
    conservative — query and fragment are preserved."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, parts.fragment))


def load_url_pairs(
    path: str | Path,
    *,
    source_column: str = "source_url",
    target_column: str = "target_url",
    note_column: str = "note",
) -> PairParseResult:
    """Parse a mapping CSV into ``(pairs, skipped, reasons)``.

    Requires a header row with the source/target columns. Rows with an empty
    source or target, or a duplicate source, are skipped and counted (with a
    reason) rather than failing the whole run.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"pairs CSV not found: {file_path}")

    text = file_path.read_text(encoding="utf-8")
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames or source_column not in reader.fieldnames or target_column not in reader.fieldnames:
        raise ValueError(
            f"pairs CSV must have a header with {source_column!r} and {target_column!r} columns; "
            f"got {reader.fieldnames}"
        )
    has_note = note_column in (reader.fieldnames or [])

    pairs: list[UrlPair] = []
    seen: set[str] = set()
    skipped = 0
    reasons: list[str] = []
    for line_no, row in enumerate(reader, start=2):
        source = (row.get(source_column) or "").strip()
        target = (row.get(target_column) or "").strip()
        if not source:
            skipped += 1
            reasons.append(f"line {line_no}: empty source")
            continue
        if not target:
            skipped += 1
            reasons.append(f"line {line_no}: empty target for {source}")
            continue
        if source in seen:
            skipped += 1
            reasons.append(f"line {line_no}: duplicate source {source}")
            continue
        seen.add(source)
        note = (row.get(note_column) or "").strip() if has_note else None
        pairs.append(UrlPair(source_url=source, target_url=target, note=note or None))
    return PairParseResult(pairs=pairs, skipped=skipped, skipped_reasons=reasons)


def classify_redirect(pair: UrlPair, source: CrawlResult | None) -> str:
    """Verdict the source page's redirect behaviour against its mapped target.

    Precedence: not-crawled → error status → no redirect → wrong target →
    temporary (302/303/307 in chain) → multi-hop chain → ok.
    """
    if source is None:
        return NOT_CRAWLED
    status = source.status
    if status == 0 or status >= 400:
        return ERROR_STATUS

    chain = source.redirect_chain or []
    redirected = bool(chain) or normalize_url_for_match(source.final_url) != normalize_url_for_match(source.requested_url)
    if not redirected:
        return NO_REDIRECT

    if normalize_url_for_match(source.final_url) != normalize_url_for_match(pair.target_url):
        return REDIRECT_WRONG_TARGET

    hop_statuses = [hop.get("status") for hop in chain]
    if any(code in _TEMPORARY_STATUSES for code in hop_statuses if isinstance(code, int)):
        return REDIRECT_TEMPORARY
    if len(chain) > 1:
        return REDIRECT_CHAIN
    return REDIRECT_OK


def _field(result: CrawlResult | None, name: str) -> object:
    if result is None or result.extracted is None:
        return None
    extracted = result.extracted
    if name == "title":
        return extracted.title
    if name == "h1":
        headings = extracted.headings.get("h1") or []
        return headings[0] if headings else None
    if name == "meta_description":
        return extracted.meta_description
    if name == "word_count":
        return extracted.word_count
    return None


def build_pair_row(
    pair: UrlPair,
    source: CrawlResult | None,
    target: CrawlResult | None,
    *,
    remap: Remap | None = None,
    simhash_threshold: int = DEFAULT_SIMHASH_THRESHOLD,
) -> dict[str, object]:
    """Build one ``compare-urls`` output row for a single mapping pair."""
    redirect_verdict = classify_redirect(pair, source)
    if source is not None and target is not None:
        content = content_comparison(source, target, remap=remap, simhash_threshold=simhash_threshold)
        sha256_equal: bool | None = content.sha256_equal
        simhash_distance = content.simhash_distance
        content_verdict = content.verdict
    else:
        sha256_equal = None
        simhash_distance = None
        content_verdict = "missing"

    field_deltas: dict[str, dict[str, object]] = {}
    for name in ("title", "h1", "meta_description", "word_count"):
        base_value = _field(source, name)
        cand_value = _field(target, name)
        field_deltas[name] = {
            "source": base_value,
            "target": cand_value,
            "changed": base_value != cand_value,
        }

    row: dict[str, object] = {
        "source_url": pair.source_url,
        "target_url": pair.target_url,
        "source_status": source.status if source is not None else None,
        "target_status": target.status if target is not None else None,
        "source_final_url": source.final_url if source is not None else None,
        "redirect_verdict": redirect_verdict,
        "redirect_chain": source.redirect_chain if source is not None else [],
        "sha256_equal": sha256_equal,
        "simhash_distance": simhash_distance,
        "content_verdict": content_verdict,
        "field_deltas": field_deltas,
    }
    if pair.note is not None:
        row["note"] = pair.note
    return row


def build_pair_rows(
    pairs: list[UrlPair],
    source_resolver: Callable[[str], CrawlResult | None],
    target_resolver: Callable[[str], CrawlResult | None],
    *,
    remap: Remap | None = None,
    simhash_threshold: int = DEFAULT_SIMHASH_THRESHOLD,
) -> list[dict[str, object]]:
    return [
        build_pair_row(
            pair,
            source_resolver(pair.source_url),
            target_resolver(pair.target_url),
            remap=remap,
            simhash_threshold=simhash_threshold,
        )
        for pair in pairs
    ]


def rows_failing(rows: list[dict[str, object]], mode: str) -> list[dict[str, object]]:
    """Rows that trip ``--fail-on`` (ticket 122).

    - ``redirect_mismatch``: any non-OK redirect verdict (wrong target, no
      redirect, error, not crawled).
    - ``content_changed``: content verdict is ``changed`` (near/identical pass).
    - ``any``: either of the above.
    """
    def is_redirect_mismatch(row: dict[str, object]) -> bool:
        return row.get("redirect_verdict") in _MISMATCH_VERDICTS

    def is_content_changed(row: dict[str, object]) -> bool:
        return row.get("content_verdict") == "changed"

    if mode == "redirect_mismatch":
        predicate = is_redirect_mismatch
    elif mode == "content_changed":
        predicate = is_content_changed
    elif mode == "any":
        def predicate(row: dict[str, object]) -> bool:
            return is_redirect_mismatch(row) or is_content_changed(row)
    else:
        raise ValueError(f"unknown --fail-on mode: {mode!r}")
    return [row for row in rows if predicate(row)]
