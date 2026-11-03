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
import re
import unicodedata
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
NO_REDIRECT_EXPECTED = "no_redirect_expected"
"""An identity mapping (source == target) that correctly did *not* redirect
(ticket 123). Mapping CSVs routinely carry retained URLs alongside moved ones;
verdicting those ``no_redirect`` made every such row fail
``--fail-on redirect_mismatch`` and forced operators to strip them by hand."""

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


_UNRESERVED_CHARACTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_VALID_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")


def _encode_text_run(run: bytes) -> str:
    """Canonicalise one decoded text run (portal ticket 3755).

    Unreserved and literal ASCII stay literal; non-ASCII is NFC-normalised when
    it is valid UTF-8 (never repaired when it is not) and re-encoded as
    uppercase percent escapes. Mirrors the PHP ``encodeTextRun()``."""
    if not run:
        return ""
    if max(run) < 0x80:
        return run.decode("ascii")
    try:
        text = run.decode("utf-8")
    except UnicodeDecodeError:
        # Not valid UTF-8: encode the raw bytes opaquely, no repair.
        return "".join(chr(byte) if byte < 0x80 else f"%{byte:02X}" for byte in run)
    text = unicodedata.normalize("NFC", text)
    return "".join(
        char if ord(char) < 0x80 else "".join(f"%{byte:02X}" for byte in char.encode("utf-8")) for char in text
    )


def _normalize_rfc3986_component(value: str) -> str:
    """RFC 3986 section 6.2.2 spelling normalisation for one URL component.

    Parity contract (portal tickets 3753/3755): matches the semantics of the
    PHP ``MigrationManager_UrlIdentity::normalizeRfc3986Component()`` —
    uppercase valid escape hex, decode escapes of unreserved characters only
    (section 6.2.2.2), percent-encode raw non-ASCII, and NFC-normalise decoded
    UTF-8 (section 6.2.2.3-adjacent, per ticket 3753). Escapes of reserved or
    otherwise-significant ASCII (``%2F`` ``%3F`` ``%23`` ``%25`` ``%20`` …)
    stay opaque, and invalid or dangling ``%`` sequences are left untouched."""
    out: list[str] = []
    run = bytearray()
    index = 0
    length = len(value)
    while index < length:
        char = value[index]
        if char == "%" and _VALID_ESCAPE.match(value, index):
            byte = int(value[index + 1 : index + 3], 16)
            if byte < 0x80 and chr(byte) not in _UNRESERVED_CHARACTERS:
                # Reserved or otherwise-significant ASCII: keep the escape
                # opaque, uppercased. Decoding it would change the URL.
                out.append(_encode_text_run(bytes(run)))
                run.clear()
                out.append(value[index : index + 3].upper())
            else:
                run.append(byte)
            index += 3
            continue
        if char == "%":
            # Invalid or dangling escape: keep it byte-for-byte, no repair.
            out.append(_encode_text_run(bytes(run)))
            run.clear()
            out.append("%")
        else:
            run.extend(char.encode("utf-8"))
        index += 1
    out.append(_encode_text_run(bytes(run)))
    return "".join(out)


def normalize_url_for_match(url: str | None) -> str:
    """Light normalization for redirect-target equality (ticket 122).

    Lowercases scheme+host and drops trailing slashes so ``…/path`` and
    ``…/path/`` match, a bare host matches its ``/`` root, and ``HTTP://Host``
    matches ``http://host``. Percent-encoding spelling is normalised on path
    and query per RFC 3986 section 6.2.2 (portal ticket 3755), in parity with
    Migration Manager's ``UrlIdentity`` v2 normaliser, so ``%c8%99`` matches
    ``%C8%99`` and raw non-ASCII matches its encoded form. Otherwise
    deliberately conservative — query and fragment are preserved."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = _normalize_rfc3986_component(parts.path).rstrip("/")
    query = _normalize_rfc3986_component(parts.query)
    return urlunsplit((scheme, netloc, path, query, parts.fragment))


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

    Precedence: not-crawled → error status → no redirect (or, for an identity
    mapping, no-redirect-expected) → wrong target → temporary (302/303/307 in
    chain) → multi-hop chain → ok.
    """
    if source is None:
        return NOT_CRAWLED
    status = source.status
    if status == 0 or status >= 400:
        return ERROR_STATUS

    is_identity = normalize_url_for_match(pair.source_url) == normalize_url_for_match(pair.target_url)
    chain = source.redirect_chain or []
    redirected = bool(chain) or normalize_url_for_match(source.final_url) != normalize_url_for_match(
        source.requested_url
    )
    if not redirected:
        # A retained URL mapped to itself is behaving correctly by staying put.
        return NO_REDIRECT_EXPECTED if is_identity else NO_REDIRECT

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


def _robots_directives(result: CrawlResult | None, attribute: str) -> list[str] | None:
    """Return saved robots directives without treating a missing page as clean.

    ``CrawlResult.allowed_by_robots`` describes the robots.txt decision made by
    the crawler.  Meta and X-Robots-Tag directives are page evidence, so they
    are deliberately separate in the comparison contract.  Keeping them as
    lists also avoids silently collapsing an unknown observation into an empty
    string in CSV output.
    """
    if result is None or result.extracted is None:
        return None
    directives = getattr(result.extracted, attribute)
    return list(directives.raw)


def _has_noindex(directives: list[str] | None) -> bool:
    """Identify a noindex token from saved directive strings.

    Saved artifacts retain the raw directives rather than the parsed boolean
    flags, so this must work after an artifact round trip too.
    """
    if directives is None:
        return False
    return any(token.strip().lower() == "noindex" for value in directives for token in value.split(","))


def _canonical_state(result: CrawlResult | None) -> tuple[str, str | None, bool | None]:
    """Return canonical state, declared canonical and explicit self-state.

    ``missing`` and ``unobserved`` are intentionally different.  A consumer
    must not infer that an absent observation or absent canonical is healthy.
    HTML canonical takes precedence over X-Canonical where both are present,
    while both raw values remain in the row for diagnosis.
    """
    if result is None:
        return "unobserved", None, None
    if result.extracted is None:
        return "unavailable", None, None
    canonical = result.extracted.canonical or result.extracted.x_canonical
    if not canonical:
        return "missing", None, None
    is_self = normalize_url_for_match(canonical) == normalize_url_for_match(result.final_url)
    return ("self" if is_self else "cross"), canonical, is_self


def _evidence_state(result: CrawlResult | None) -> str:
    """Machine-readable observation state for one side of a mapping."""
    if result is None:
        return "unobserved"
    if result.status == 0:
        return "fetch_error"
    if result.status >= 400:
        return "http_error"
    if result.extracted is None:
        return "page_evidence_unavailable"
    return "observed"


def _target_migration_verdict(result: CrawlResult | None) -> str:
    """Summarise target indexability without overloading redirect verdicts."""
    state = _evidence_state(result)
    if state != "observed":
        return f"target_{state}"
    assert result is not None and result.extracted is not None  # narrowed by state
    if result.allowed_by_robots is False:
        return "target_robots_disallowed"
    meta = _robots_directives(result, "meta_robots")
    x_robots = _robots_directives(result, "x_robots_tag")
    if _has_noindex(meta) or _has_noindex(x_robots):
        return "target_noindex"
    canonical_state, _, _ = _canonical_state(result)
    if canonical_state == "cross":
        return "target_cross_canonical"
    if canonical_state == "missing":
        return "target_canonical_missing"
    if result.allowed_by_robots is None:
        return "target_robots_allowance_unknown"
    return "target_indexability_healthy"


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
    for side, result in (("source", source), ("target", target)):
        canonical_state, canonical_url, self_canonical = _canonical_state(result)
        extracted = result.extracted if result is not None else None
        row.update(
            {
                f"{side}_evidence_state": _evidence_state(result),
                f"{side}_final_url": result.final_url if result is not None else None,
                f"{side}_canonical_url": canonical_url,
                f"{side}_html_canonical_url": extracted.canonical if extracted is not None else None,
                f"{side}_x_canonical_url": extracted.x_canonical if extracted is not None else None,
                f"{side}_canonical_state": canonical_state,
                f"{side}_self_canonical": self_canonical,
                f"{side}_meta_robots": _robots_directives(result, "meta_robots"),
                f"{side}_x_robots_tag": _robots_directives(result, "x_robots_tag"),
                f"{side}_robots_allowed": result.allowed_by_robots if result is not None else None,
            }
        )
    row["target_migration_verdict"] = _target_migration_verdict(target)
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
