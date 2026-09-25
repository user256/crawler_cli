"""Bounded current robots.txt and XML sitemap evidence collection."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import TYPE_CHECKING, Mapping, Sequence
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from .extract import extract_page_data
from .authorisation import ScopeDecision, ScopeManifestDenied
from .redaction import redact_url_without_digest
from .sitemap import SitemapParser, discover_sitemap_paths

if TYPE_CHECKING:
    from .engine import CrawlEngine


class _HostScope:
    """Narrow live-audit requests to persisted run origins and allowed hosts."""

    def __init__(self, origins: Sequence[str], allowed_hosts: set[str], delegate=None) -> None:
        self.origins = {_origin(value).lower() for value in origins}
        self.allowed_hosts = {host.lower() for host in allowed_hosts}
        self.delegate = delegate

    def decide(self, url: str, *, purpose: str = "discovered", method: str = "GET") -> ScopeDecision:
        parsed = urlsplit(url)
        netloc = parsed.netloc.lower()
        allowed = parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname) and "@" not in netloc
        allowed = allowed and (_origin(url).lower() in self.origins or netloc in self.allowed_hosts)
        if not allowed:
            return ScopeDecision(False, "origin", url)
        if self.delegate is not None:
            return self.delegate.decide(url, purpose=purpose, method=method)
        return ScopeDecision(True, None, url)

    def require(self, url: str, *, purpose: str = "discovered", method: str = "GET") -> None:
        decision = self.decide(url, purpose=purpose, method=method)
        if not decision.allowed:
            raise ScopeManifestDenied(url, decision.reason or "origin")


def build_site_file_scope(seed_origins: Sequence[str], allowed_hosts: set[str], delegate=None) -> _HostScope:
    """Combine explicit run-host boundaries with an optional authorization manifest."""
    return _HostScope(seed_origins, allowed_hosts, delegate)


async def collect_current_site_files(
    engine: CrawlEngine,
    *,
    seed_origins: Sequence[str],
    allowed_hosts: set[str],
    historical_pages: Mapping[str, Mapping[str, object]],
    max_sitemaps: int = 100,
    max_urls: int = 100_000,
    max_live_samples: int = 25,
    max_depth: int = 3,
) -> dict[str, object]:
    """Collect current robots/sitemap evidence without fetching robots-denied URLs.

    All outbound requests pass through ``CrawlEngine``'s guarded fetch path.
    Robots-disallowed sitemap documents and page samples are recorded as
    unavailable with the matching rule, and are never requested.
    """
    if not seed_origins or max_sitemaps < 1 or max_urls < 1 or max_live_samples < 0 or max_depth < 0:
        raise ValueError("site-file collection requires origins and positive bounded budgets")
    parser = SitemapParser()
    robots_records: dict[str, dict[str, object]] = {}
    robots_rules: dict[str, object] = {}

    async def get_rules(url: str):
        origin = _origin(url)
        if origin not in robots_rules:
            rules = await engine._robots.get_rules(origin)
            robots_rules[origin] = rules
            if rules is None:
                robots_records[origin] = {
                    "source_url": _safe_url(f"{origin}/robots.txt"),
                    "state": "unavailable_or_unreachable",
                    "http_status": None,
                    "matched_controls": [],
                    "sitemaps": [],
                }
            else:
                raw = str(getattr(rules, "raw_content", ""))
                controls = _robots_controls(rules, origin, engine.config.user_agent_for(origin))
                directives = list(rules.sitemaps())
                malformed = [_safe_url(line.strip()) for line in raw.splitlines() if _looks_like_bare_sitemap(line)]
                robots_records[origin] = {
                    "source_url": _safe_url(str(rules.source_url)),
                    "state": "fetched",
                    "http_status": getattr(rules, "http_status", None),
                    "content_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                    "line_count": len(raw.splitlines()),
                    "matched_controls": controls,
                    "sitemaps": [_safe_url(value) for value in directives],
                    "malformed_bare_sitemap_lines": malformed,
                }
        return robots_rules[origin]

    sitemap_urls: list[tuple[str, str, int]] = []
    rejected_sitemaps: list[dict[str, object]] = []
    for seed in seed_origins:
        rules = await get_rules(seed)
        if rules is None or getattr(rules, "http_status", None) == 0:
            continue
        declared = list(rules.sitemaps())
        raw = str(getattr(rules, "raw_content", ""))
        bare = [line.strip() for line in raw.splitlines() if _looks_like_bare_sitemap(line)]
        for url in [*declared, *bare, *discover_sitemap_paths(seed)]:
            sitemap_urls.append(
                (
                    url,
                    "robots_declared"
                    if url in declared
                    else ("malformed_bare_line" if url in bare else "well_known_path"),
                    0,
                )
            )

    # Bound work before the first request too: a robots file can declare an
    # arbitrarily large number of sitemap roots, and one index can fan out to
    # an arbitrarily large number of children.
    if len(sitemap_urls) > max_sitemaps:
        rejected_sitemaps.extend(
            {"url": _safe_url(url), "reason": "max_sitemaps_budget"}
            for url, _source, _depth in sitemap_urls[max_sitemaps:]
        )
        sitemap_urls = sitemap_urls[:max_sitemaps]

    fetched: set[str] = set()
    documents: list[dict[str, object]] = []
    sitemap_entries: list[dict[str, object]] = []
    queue = sitemap_urls
    complete = not rejected_sitemaps
    while queue:
        url, discovery_source, depth = queue.pop(0)
        if url in fetched:
            continue
        if len(fetched) >= max_sitemaps:
            complete = False
            rejected_sitemaps.append({"url": _safe_url(url), "reason": "max_sitemaps_budget"})
            continue
        fetched.add(url)
        reason = engine._sitemap_url_reject_reason(url, list(seed_origins), check_path=False)
        if reason:
            rejected_sitemaps.append({"url": _safe_url(url), "reason": reason})
            continue
        rules = await get_rules(url)
        if rules is None:
            documents.append(
                {"url": _safe_url(url), "state": "robots_unavailable", "discovery_source": discovery_source}
            )
            complete = False
            continue
        decision = await engine._robots.check(url)
        if not decision.allowed:
            documents.append(
                {
                    "url": _safe_url(url),
                    "state": "robots_disallowed_not_fetched",
                    "matched_rule": decision.matched_rule,
                    "matched_user_agent": decision.matched_user_agent,
                    "discovery_source": discovery_source,
                }
            )
            complete = False
            continue
        response = await engine._bounded_fetch_response(url)
        if response is None:
            documents.append(
                {"url": _safe_url(url), "state": "fetch_unavailable", "discovery_source": discovery_source}
            )
            complete = False
            continue
        document = {
            "url": _safe_url(url),
            "final_url": _safe_url(response.url),
            "http_status": response.status,
            "content_type": response.headers.get("Content-Type"),
            "wire_bytes": response.wire_bytes,
            "decoded_bytes": response.decoded_bytes,
            "elapsed_seconds": response.elapsed_seconds,
            "redirect_chain": [
                {"url": _safe_url(str(hop.get("url") or "")), "status": hop.get("status")}
                for hop in response.redirect_chain
                if isinstance(hop, Mapping)
            ],
            "response_headers": _safe_headers(response.headers),
            "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "discovery_source": discovery_source,
        }
        if response.status != 200:
            document["state"] = (
                "not_found" if response.status == 404 and discovery_source == "well_known_path" else "http_error"
            )
            documents.append(document)
            if document["state"] != "not_found":
                complete = False
            continue
        try:
            parsed = parser.parse(url, response.body, response.headers.get("Content-Type"))
        except Exception as exc:
            document["state"] = "parse_error"
            document["parse_error_type"] = type(exc).__name__
            documents.append(document)
            complete = False
            continue
        document["state"] = "parsed"
        document["kind"] = parsed.kind
        document["url_count"] = len(parsed.urls)
        document["child_count"] = len(parsed.children)
        document["content_sha256"] = hashlib.sha256(response.body).hexdigest()
        documents.append(document)
        if parsed.kind == "sitemap_index":
            if depth >= max_depth and parsed.children:
                complete = False
                rejected_sitemaps.extend(
                    {"url": _safe_url(child), "reason": "max_sitemap_depth"} for child in parsed.children
                )
            else:
                available = max(0, max_sitemaps - len(fetched) - len(queue))
                accepted_children = parsed.children[:available]
                queue.extend((child, "sitemap_index_child", depth + 1) for child in accepted_children)
                if len(accepted_children) < len(parsed.children):
                    complete = False
                    rejected_sitemaps.extend(
                        {"url": _safe_url(child), "reason": "max_sitemaps_budget"}
                        for child in parsed.children[len(accepted_children) :]
                    )
            continue
        for item in parsed.urls:
            if len(sitemap_entries) >= max_urls:
                complete = False
                break
            url_reason = engine._sitemap_url_reject_reason(item.loc, list(seed_origins), check_path=True)
            sitemap_entries.append(
                {
                    "url": _safe_url(item.loc),
                    "_raw_url": item.loc,
                    "url_digest_sha256": hashlib.sha256(item.loc.encode()).hexdigest(),
                    "source_sitemap": _safe_url(url),
                    "lastmod": item.lastmod,
                    "lastmod_state": _lastmod_state(item.lastmod),
                    "hreflang": [
                        {"hreflang": link.hreflang, "href": _safe_url(link.href)} for link in item.hreflang_links
                    ],
                    "historical_crawl": "crawled" if item.loc in historical_pages else "not_crawled_in_selected_run",
                    "historical_status": historical_pages.get(item.loc, {}).get("final_status_code"),
                    "historical_indexable": historical_pages.get(item.loc, {}).get("overall_indexable"),
                    "admission_state": "in_scope" if url_reason is None else "not_admitted",
                    **({"admission_reason": url_reason} if url_reason else {}),
                }
            )
    live_samples = await _fetch_live_samples(
        engine,
        sitemap_entries,
        historical_pages=historical_pages,
        max_samples=max_live_samples,
        get_rules=get_rules,
    )
    duplicates = Counter(str(entry["_raw_url"]) for entry in sitemap_entries)
    duplicate_urls = sorted(url for url, count in duplicates.items() if count > 1)
    validation = [
        {
            "candidate_type": "duplicate_sitemap_url",
            "url": _safe_url(url),
            "url_digest_sha256": hashlib.sha256(url.encode()).hexdigest(),
            "occurrence_count": duplicates[url],
        }
        for url in duplicate_urls
    ]
    for robots in robots_records.values():
        malformed_values = robots.get("malformed_bare_sitemap_lines", [])
        for malformed in malformed_values if isinstance(malformed_values, list) else []:
            validation.append(
                {
                    "candidate_type": "malformed_bare_sitemap_declaration",
                    "url": malformed,
                    "qualification": "robots_sitemap_prefix_missing",
                }
            )
        controls = robots.get("matched_controls", [])
        if isinstance(controls, list):
            outcomes = {bool(item.get("allowed")) for item in controls if isinstance(item, Mapping)}
            if outcomes != {True, False}:
                validation.append(
                    {
                        "candidate_type": "robots_controls_incomplete",
                        "url": robots.get("source_url"),
                        "qualification": "one_or_both_actual_allow_block_controls_not_available",
                    }
                )
    for entry in sitemap_entries:
        url = urlsplit(str(entry["url"]))
        sitemap_url = urlsplit(str(entry["source_sitemap"]))
        if url.scheme and sitemap_url.scheme and url.scheme != sitemap_url.scheme:
            validation.append(
                {
                    "candidate_type": "sitemap_protocol_mismatch_review",
                    "url": entry["url"],
                    "source_sitemap": entry["source_sitemap"],
                    "qualification": "verify_host_configuration",
                }
            )
        if url.netloc and sitemap_url.netloc and url.netloc.lower() != sitemap_url.netloc.lower():
            validation.append(
                {
                    "candidate_type": "sitemap_host_mismatch_review",
                    "url": entry["url"],
                    "source_sitemap": entry["source_sitemap"],
                    "qualification": "cross_host_may_be_intentional",
                }
            )
        if entry["lastmod_state"] != "credible_or_absent":
            validation.append(
                {
                    "candidate_type": "sitemap_lastmod_review",
                    "url": entry["url"],
                    "lastmod": entry["lastmod"],
                    "lastmod_state": entry["lastmod_state"],
                }
            )
        seen_languages: set[str] = set()
        alternates = entry.get("hreflang", [])
        for alternate in alternates if isinstance(alternates, list) else []:
            if not isinstance(alternate, Mapping):
                continue
            code = str(alternate.get("hreflang") or "").lower()
            href = str(alternate.get("href") or "")
            if code in seen_languages:
                validation.append(
                    {
                        "candidate_type": "duplicate_sitemap_hreflang_language",
                        "url": entry["url"],
                        "hreflang": code,
                        "qualification": "review_duplicate_annotation",
                    }
                )
            seen_languages.add(code)
            if code != "x-default" and not re.fullmatch(r"(?:[a-z]{2,3}|[a-z]{4}|[a-z]{5,8})(?:-[a-z0-9]{1,8})*", code):
                validation.append(
                    {"candidate_type": "invalid_sitemap_hreflang_syntax", "url": entry["url"], "hreflang": code}
                )
            target_path = urlsplit(href).path.strip("/").split("/")
            target_locale = target_path[0].lower() if target_path else ""
            if code != "x-default" and re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})?", target_locale):
                if target_locale.split("-", 1)[0] != code.split("-", 1)[0]:
                    validation.append(
                        {
                            "candidate_type": "sitemap_hreflang_path_locale_review",
                            "url": entry["url"],
                            "href": href,
                            "hreflang": code,
                            "qualification": "path_segment_is_only_a_locale_heuristic",
                        }
                    )
    if len(sitemap_entries) >= max_urls:
        complete = False
    return {
        "record_type": "coverage",
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "complete": complete,
        "seed_origins": [_safe_url(origin) for origin in seed_origins],
        "allowed_host_count": len(allowed_hosts),
        "robots_documents": list(robots_records.values()),
        "sitemap_document_count": len(documents),
        "sitemap_entry_count": len(sitemap_entries),
        "unique_sitemap_url_count": len(duplicates),
        "duplicate_sitemap_url_count": len(duplicate_urls),
        "rejected_sitemaps": rejected_sitemaps,
        "documents": documents,
        "entries": [{key: value for key, value in entry.items() if key != "_raw_url"} for entry in sitemap_entries],
        "live_samples": live_samples,
        "validation_candidates": validation,
        "sampling": "deterministic round-robin by crawl state, locale and path-template proxy",
    }


async def _fetch_live_samples(engine, entries, *, historical_pages, max_samples, get_rules):
    if max_samples == 0:
        return []
    candidates = []
    seen = set()
    for entry in entries:
        safe_url = str(entry["url"])
        raw_url = _raw_url_for_redacted(entries, safe_url)
        if not raw_url or raw_url in seen or entry.get("admission_state") != "in_scope":
            continue
        seen.add(raw_url)
        path = urlsplit(raw_url).path.strip("/").split("/")
        first = path[0] if path else "root"
        locale = first.lower() if re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})?", first, re.I) else "unknown"
        template = path[1] if locale != "unknown" and len(path) > 1 else first
        crawl_state = "crawled" if raw_url in historical_pages else "not_crawled_in_selected_run"
        candidates.append((crawl_state, locale, template, raw_url, entry))
    by_stratum: dict[tuple[str, str, str], list[tuple[str, dict[str, object]]]] = defaultdict(list)
    for crawl_state, locale, template, url, entry in candidates:
        by_stratum[(crawl_state, locale, template)].append((url, entry))
    selected = []
    strata = sorted(by_stratum)
    while strata and len(selected) < max_samples:
        remaining = []
        for stratum in strata:
            group = by_stratum[stratum]
            if group:
                selected.append((stratum, *group.pop(0)))
                if len(selected) >= max_samples:
                    break
            if group:
                remaining.append(stratum)
        strata = remaining
    samples = []
    for (crawl_state, locale, template), url, entry in selected:
        rules = await get_rules(url)
        if rules is None:
            samples.append({"url": _safe_url(url), "state": "robots_unavailable_no_fetch"})
            continue
        decision = await engine._robots.check(url)
        if not decision.allowed:
            samples.append(
                {
                    "url": _safe_url(url),
                    "state": "robots_disallowed_not_fetched",
                    "matched_rule": decision.matched_rule,
                    "matched_user_agent": decision.matched_user_agent,
                }
            )
            continue
        response = await engine._bounded_fetch_response(url)
        sample = {
            "url": _safe_url(url),
            "crawl_state": crawl_state,
            "locale_stratum": locale,
            "template_path_stratum": template,
            "state": "fetch_unavailable" if response is None else "fetched",
            "historical_status": historical_pages.get(url, {}).get("final_status_code"),
        }
        if response is not None:
            sample.update(
                {
                    "http_status": response.status,
                    "final_url": _safe_url(response.url),
                    "content_type": response.headers.get("Content-Type"),
                    "elapsed_seconds": response.elapsed_seconds,
                    "redirect_chain": [
                        {"url": _safe_url(str(hop.get("url") or "")), "status": hop.get("status")}
                        for hop in response.redirect_chain
                        if isinstance(hop, Mapping)
                    ],
                    "response_headers": _safe_headers(response.headers),
                }
            )
            if response.status == 200 and "html" in (response.headers.get("Content-Type") or "").lower():
                extracted = extract_page_data(response.text, response.url, response.headers)
                sample.update(
                    {
                        "title_present": bool(extracted.title),
                        "description_present": bool(extracted.meta_description),
                        "canonical_channels": [
                            {"source": item.get("source"), "href": _safe_url(str(item.get("href") or ""))}
                            for item in extracted.canonical_evidence
                        ],
                        "indexable_by_saved_directives": not extracted.meta_robots.noindex
                        and not extracted.x_robots_tag.noindex,
                    }
                )
        samples.append(sample)
    return samples


def _robots_controls(rules, origin: str, user_agent: str) -> list[dict[str, object]]:
    groups = getattr(rules, "_groups", {})
    keys = rules._matching_group_keys(user_agent)
    candidates = []
    for key in keys:
        for kind, rule in groups.get(key, []):
            if not rule:
                continue
            path = rule.replace("*", "").replace("$", "") or "/"
            decision = rules.check(path, user_agent)
            if (kind == "disallow" and not decision.allowed) or (kind == "allow" and decision.allowed):
                candidates.append((kind, path, decision))
    controls: list[dict[str, object]] = []
    for wanted in ("allow", "disallow"):
        picked = next((item for item in candidates if item[0] == wanted), None)
        if picked:
            _kind, path, decision = picked
            controls.append(
                {
                    "path": path,
                    "allowed": decision.allowed,
                    "matched_rule": decision.matched_rule,
                    "matched_user_agent": decision.matched_user_agent,
                }
            )
    if not any(item["allowed"] is True for item in controls):
        decision = rules.check("/", user_agent)
        if decision.allowed:
            controls.append(
                {
                    "path": "/",
                    "allowed": True,
                    "matched_rule": decision.matched_rule,
                    "matched_user_agent": decision.matched_user_agent,
                }
            )
    return controls


def _lastmod_state(value: str | None) -> str:
    if not value:
        return "credible_or_absent"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "malformed"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return "future" if parsed > datetime.now(timezone.utc) + timedelta(days=1) else "credible_or_absent"


def _looks_like_bare_sitemap(line: str) -> bool:
    candidate = line.strip().split("#", 1)[0].strip()
    return candidate.lower().startswith(("http://", "https://")) and ".xml" in urlsplit(candidate).path.lower()


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], "", "", ""))


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    query_names = [key for key, _ in parse_qsl(parts.query, keep_blank_values=True)]
    stripped = parts._replace(query="&".join(query_names)).geturl()
    return redact_url_without_digest(stripped)


def _safe_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Retain response evidence while excluding credential/cookie material."""
    sensitive = {"set-cookie", "www-authenticate", "proxy-authenticate"}
    safe: dict[str, str] = {}
    for name, value in headers.items():
        lowered_name = str(name).lower()
        if lowered_name in sensitive:
            continue
        safe[lowered_name] = _safe_url(str(value)) if lowered_name == "location" else str(value)
    return safe


def _raw_url_for_redacted(entries: Sequence[Mapping[str, object]], safe_url: str) -> str | None:
    # The collector can only fetch its original in-memory URL. URL values are
    # not reconstructed from redacted output because that would be lossy.
    for entry in entries:
        raw = entry.get("_raw_url")
        if isinstance(raw, str) and _safe_url(raw) == safe_url:
            return raw
    return None
