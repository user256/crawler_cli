"""AI crawler governance: declared robots.txt posture and /llms.txt evidence (ticket 258).

Two bounded, deterministic collections feed the ``ai-crawler-governance``
technical-audit check:

* the declared ``robots.txt`` posture for nine recognised AI crawler families,
  evaluated with the crawler's own RFC 9309 parser (``robots._RobotsRules``);
* at most three GETs per origin for ``/.well-known/llms.txt``, ``/llms.txt``
  and ``/llms-full.txt``, classified as valid Markdown/plain text, absent, or
  an HTML soft-404 masquerading as a text file.

The token list and posture rules follow the ``llm-crawlability-audit`` skill
(``scripts/robots_matrix.py`` and ``references/provider-matrix.md``, verified
2026-09-14). That skill's matrix is wider (21 tokens x arbitrary URLs); this
module keeps the ticket's nine families so the audit contract is fixed.

Everything here is *declared* policy. A robots group need not correspond to a
separate HTTP crawler, several user-triggered fetchers are documented as not
consulting robots.txt, and a CDN/WAF can block a token that robots.txt allows.
``llms.txt`` is a proposal, not a standard: its absence is not a defect.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from typing import TYPE_CHECKING, Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from .probes import SOFT_404_ERROR_PHRASE
from .redaction import redact_url_without_digest

if TYPE_CHECKING:
    from .models import FetchResponse
    from .robots import _RobotsRules


AI_GOVERNANCE_RULESET_VERSION = "ai-crawler-governance/1"
AI_GOVERNANCE_PROVIDER_MATRIX_VERIFIED_ON = "2026-09-14"
AI_POSTURES = ("allowed", "blocked", "partially_blocked", "default_wildcard", "unknown")

# A path no site plausibly names. Together with "/" it distinguishes a
# homepage-only rule (``Disallow: /$``) from a full block.
_DEEP_PROBE_PATH = "/crawler-cli-ai-governance-probe"
_MAX_RULES_RECORDED = 25
_TEXT_CONTENT_TYPES = {"text/markdown", "text/x-markdown", "text/plain"}
_HTML_SNIFF = re.compile(r"^\s*(?:<!doctype\s+html|<html[\s>]|<head[\s>]|<body[\s>])", re.I)
_HTML_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_MARKDOWN_H1 = re.compile(r"^#\s+(\S.*?)\s*#*\s*$")
_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\([^)\s]+[^)]*\)")


@dataclass(frozen=True, slots=True)
class AiCrawlerFamily:
    id: str
    operator: str
    tokens: tuple[str, ...]
    """Robots product tokens; the first is primary, the rest are aliases."""
    role: str
    robots_documented: str


AI_CRAWLER_FAMILIES: tuple[AiCrawlerFamily, ...] = (
    AiCrawlerFamily("gptbot", "OpenAI", ("GPTBot",), "training", "respected"),
    AiCrawlerFamily(
        "chatgpt-user",
        "OpenAI",
        ("ChatGPT-User",),
        "user_triggered",
        "user-initiated fetches; OpenAI states robots.txt rules may not apply",
    ),
    AiCrawlerFamily(
        "claudebot", "Anthropic", ("ClaudeBot", "anthropic-ai"), "training", "respected; anthropic-ai is a legacy token"
    ),
    AiCrawlerFamily("perplexitybot", "Perplexity", ("PerplexityBot",), "search_index", "respected"),
    AiCrawlerFamily(
        "google-extended",
        "Google",
        ("Google-Extended",),
        "control_token",
        "control token only; no separate crawler and no effect on Google Search inclusion",
    ),
    AiCrawlerFamily(
        "amazonbot", "Amazon", ("Amazonbot",), "search_and_training", "respected; robots cached up to 30 days"
    ),
    AiCrawlerFamily("bytespider", "ByteDance", ("Bytespider",), "crawler", "no reachable official documentation"),
    AiCrawlerFamily("ccbot", "Common Crawl", ("CCBot",), "open_corpus", "respected; obeys Crawl-delay"),
    AiCrawlerFamily(
        "applebot-extended",
        "Apple",
        ("Applebot-Extended",),
        "control_token",
        "training opt-out token only; does not crawl",
    ),
)

LLMS_TXT_PROBES: tuple[tuple[str, str], ...] = (
    ("/.well-known/llms.txt", "llms_txt"),
    ("/llms.txt", "llms_txt"),
    ("/llms-full.txt", "llms_full_txt"),
)


def _probe_path(rule: str) -> str:
    """Return a path the rule itself matches (``*`` may match the empty string)."""
    path = rule.replace("*", "").rstrip("$")
    return path if path.startswith("/") else "/" + path


def _group_rules(rules: _RobotsRules, keys: Sequence[str]) -> list[tuple[str, str]]:
    return [(kind, path) for key in keys for kind, path in rules._groups.get(key, []) if path]


def _access(rules: _RobotsRules, token: str, keys: Sequence[str]) -> tuple[str, list[dict[str, object]]]:
    """Classify the effective access of *token* across its applicable rules.

    Probe paths are the site root, an arbitrary deep path, and one path that
    each applicable rule matches. All allowed -> ``allowed``; all disallowed ->
    ``blocked``; otherwise ``partially_blocked``. Decisions come from the
    crawler's RFC 9309 matcher (longest match, Allow wins ties).
    """
    probes = ["/", _DEEP_PROBE_PATH]
    for _kind, path in _group_rules(rules, keys):
        candidate = _probe_path(path)
        if candidate not in probes:
            probes.append(candidate)
    decisions = []
    for path in probes:
        decision = rules.check(path, token)
        decisions.append({"path": path, "allowed": decision.allowed, "matched_rule": decision.matched_rule})
    outcomes = {bool(item["allowed"]) for item in decisions}
    if outcomes == {True}:
        return "allowed", decisions
    if outcomes == {False}:
        return "blocked", decisions
    return "partially_blocked", decisions


def classify_token(rules: _RobotsRules, token: str) -> dict[str, object]:
    """Return the declared posture of one product token against parsed rules."""
    keys = rules._matching_group_keys(token)
    explicit = bool(keys) and keys != ["*"]
    effective, decisions = _access(rules, token, keys)
    root = next(item for item in decisions if item["path"] == "/")
    return {
        "token": token,
        "posture": effective if explicit else "default_wildcard",
        "effective_access": effective,
        "group_source": "explicit" if explicit else ("wildcard" if keys else "none"),
        "matched_groups": list(keys),
        "group_rules": [
            f"{kind.capitalize()}: {path}" for kind, path in _group_rules(rules, keys)[:_MAX_RULES_RECORDED]
        ],
        "root_allowed": root["allowed"],
        "root_matched_rule": root["matched_rule"],
        "probe_decisions": decisions,
        "crawl_delay": rules.crawl_delay(token),
    }


def classify_ai_crawlers(
    rules: _RobotsRules | None,
    *,
    families: Sequence[AiCrawlerFamily] = AI_CRAWLER_FAMILIES,
) -> list[dict[str, object]]:
    """Classify every recognised AI crawler family against one robots.txt.

    ``rules`` of ``None`` means robots.txt was unreachable (RFC 9309 treats
    that as complete disallow for crawling, but the *declared* policy is
    unknown), so every family is ``unknown``. A 4xx robots.txt parses as an
    empty ruleset: every family is ``default_wildcard`` with allowed access.
    The family posture is the primary token's when it has its own group,
    otherwise the first alias with its own group, otherwise the wildcard.
    """
    rows: list[dict[str, object]] = []
    for family in families:
        base = {
            "family": family.id,
            "operator": family.operator,
            "tokens": list(family.tokens),
            "role": family.role,
            "robots_documented": family.robots_documented,
        }
        if rules is None:
            rows.append({**base, "posture": "unknown", "effective_access": None, "token_results": []})
            continue
        token_results = [classify_token(rules, token) for token in family.tokens]
        explicit = [item for item in token_results if item["group_source"] == "explicit"]
        governing = explicit[0] if explicit else token_results[0]
        postures = {str(item["posture"]) for item in explicit}
        rows.append(
            {
                **base,
                "posture": governing["posture"],
                "effective_access": governing["effective_access"],
                "governing_token": governing["token"],
                "group_source": governing["group_source"],
                "alias_conflict": len(postures) > 1,
                "token_results": token_results,
            }
        )
    return rows


def declared_preference_signals(raw_robots: str) -> list[str]:
    """Return ``Content-Signal`` / ``Content-Usage`` robots lines as declarations.

    These are preference declarations (Cloudflare Content Signals, IETF AIPREF
    drafts), not enforcement. The crawler's robots parser ignores them.
    """
    signals = []
    for line in raw_robots.splitlines():
        stripped = line.split("#", 1)[0].strip()
        key, _, value = stripped.partition(":")
        if key.strip().lower() in {"content-signal", "content-usage"} and value.strip():
            signals.append(f"{key.strip()}: {value.strip()}")
    return signals


def _media_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    return content_type.split(";", 1)[0].strip().lower() or None


def classify_llms_response(response: FetchResponse, *, kind: str) -> dict[str, object]:
    """Classify one fetched AI context file without further requests.

    A 200 whose body or ``Content-Type`` is HTML is an ``html_soft_404``: the
    server answered a missing text file with a page. Only ``text/markdown``,
    ``text/x-markdown`` or ``text/plain`` bodies count as valid; ``llms.txt``
    additionally needs its required H1 title (``llms-full.txt`` does not).
    """
    body = response.body or b""
    text = response.text or body.decode("utf-8", errors="replace")
    media_type = _media_type(response.headers.get("Content-Type") or response.headers.get("content-type"))
    record: dict[str, object] = {
        "http_status": response.status,
        "final_url": _safe_url(response.url),
        "content_type": media_type,
        "byte_size": response.decoded_bytes or len(body),
        "wire_bytes": response.wire_bytes,
        "body_truncated": response.body_truncated,
        "redirect_chain": [
            {"url": _safe_url(str(hop.get("url") or "")), "status": hop.get("status")}
            for hop in response.redirect_chain
            if isinstance(hop, Mapping)
        ],
        "content_sha256": hashlib.sha256(body).hexdigest() if body else None,
        "title": None,
    }
    requested_origin = _origin(response.requested_url)
    record["redirected_cross_origin"] = bool(response.url) and _origin(response.url) != requested_origin
    if response.status in {404, 410}:
        record["state"] = "absent"
        return record
    if response.status != 200:
        record["state"] = "http_error"
        return record
    looks_html = (media_type is not None and "html" in media_type) or bool(_HTML_SNIFF.match(text[:1024]))
    if looks_html:
        title_match = _HTML_TITLE.search(text)
        html_title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else None
        record.update(
            {
                "state": "html_soft_404",
                "html_title": html_title,
                "error_phrase_in_body": bool(SOFT_404_ERROR_PHRASE.search(text)),
            }
        )
        return record
    if not text.strip():
        record["state"] = "empty"
        return record
    lines = text.splitlines()
    first_content = next((line.strip() for line in lines if line.strip()), "")
    h1 = _MARKDOWN_H1.match(first_content)
    record.update(
        {
            "title": h1.group(1) if h1 else None,
            "summary_blockquote_present": any(line.startswith(">") for line in lines),
            "section_count": sum(1 for line in lines if line.startswith("## ")),
            "markdown_link_count": len(_MARKDOWN_LINK.findall(text)),
        }
    )
    if media_type not in _TEXT_CONTENT_TYPES:
        record["state"] = "unexpected_content_type"
    elif kind == "llms_txt" and h1 is None:
        record["state"] = "missing_h1_title"
    else:
        record["state"] = "valid"
    return record


def ai_governance_candidates(
    bot_rows: Sequence[Mapping[str, object]], llms_rows: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    """Derive reviewable findings from posture and llms.txt observations."""
    candidates: list[dict[str, object]] = []
    for row in bot_rows:
        base = {"origin": row.get("origin"), "family": row.get("family"), "operator": row.get("operator")}
        if row.get("posture") in {"blocked", "partially_blocked"}:
            candidates.append(
                {
                    **base,
                    "candidate_type": "ai_crawler_access_restricted",
                    "posture": row.get("posture"),
                    "role": row.get("role"),
                    "governing_token": row.get("governing_token"),
                    "qualification": "declared_policy_confirm_business_intent",
                }
            )
        if row.get("alias_conflict"):
            token_results = row.get("token_results")
            candidates.append(
                {
                    **base,
                    "candidate_type": "ai_crawler_alias_conflict",
                    "token_postures": {
                        str(item.get("token")): item.get("posture")
                        for item in (token_results if isinstance(token_results, list) else [])
                        if isinstance(item, Mapping) and item.get("group_source") == "explicit"
                    },
                    "qualification": "tokens_of_one_operator_disagree",
                }
            )
    by_origin: dict[str, list[Mapping[str, object]]] = {}
    for row in llms_rows:
        by_origin.setdefault(str(row.get("origin")), []).append(row)
    for origin, rows in sorted(by_origin.items()):
        for row in rows:
            state = row.get("state")
            if state in {"html_soft_404", "empty", "unexpected_content_type", "missing_h1_title", "http_error"}:
                candidates.append(
                    {
                        "origin": origin,
                        "candidate_type": f"llms_file_{state}",
                        "path": row.get("path"),
                        "http_status": row.get("http_status"),
                        "content_type": row.get("content_type"),
                        "final_url": row.get("final_url"),
                        "qualification": "invalid_ai_context_file" if state != "http_error" else "recheck_required",
                    }
                )
        manifests = [row for row in rows if row.get("kind") == "llms_txt"]
        if manifests and all(row.get("state") == "absent" for row in manifests):
            candidates.append(
                {
                    "origin": origin,
                    "candidate_type": "llms_txt_absent",
                    "paths": [row.get("path") for row in manifests],
                    "qualification": "absence_is_not_a_defect_llms_txt_is_a_proposal",
                }
            )
    return candidates


async def collect_ai_governance(
    engine: Any,
    *,
    seed_origins: Sequence[str],
    max_origins: int = 10,
) -> dict[str, object]:
    """Collect declared AI crawler posture and /llms.txt evidence per origin.

    Requests go through ``CrawlEngine``'s guarded paths: robots.txt through
    its robots cache, AI context files through ``_bounded_fetch_response``.
    A robots-disallowed context file is recorded, never requested. At most
    one robots fetch and three GETs are made per origin.
    """
    if max_origins < 1:
        raise ValueError("AI governance collection requires a positive origin budget")
    origins = sorted({_origin(value) for value in seed_origins if urlsplit(value).netloc})
    if not origins:
        raise ValueError("AI governance collection requires at least one seed origin")
    selected, skipped = origins[:max_origins], origins[max_origins:]
    complete = not skipped
    robots_documents: list[dict[str, object]] = []
    bot_rows: list[dict[str, object]] = []
    llms_rows: list[dict[str, object]] = []
    for origin in selected:
        rules = await engine._robots.get_rules(origin)
        status = getattr(rules, "http_status", None) if rules is not None else None
        if rules is None:
            robots_state = "unavailable_or_unreachable"
            complete = False
        elif status is not None and 400 <= status < 500:
            robots_state = "absent_allow_all"
        else:
            robots_state = "fetched"
        raw = str(getattr(rules, "raw_content", "")) if rules is not None else ""
        robots_documents.append(
            {
                "origin": _safe_url(origin),
                "source_url": _safe_url(f"{origin}/robots.txt"),
                "state": robots_state,
                "http_status": status,
                "content_sha256": hashlib.sha256(raw.encode()).hexdigest() if rules is not None else None,
                "declared_preference_signals": declared_preference_signals(raw),
            }
        )
        bot_rows.extend({"origin": _safe_url(origin), **row} for row in classify_ai_crawlers(rules))
        for path, kind in LLMS_TXT_PROBES:
            url = f"{origin}{path}"
            row: dict[str, object] = {"origin": _safe_url(origin), "path": path, "kind": kind, "url": _safe_url(url)}
            row["observed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if rules is None:
                row.update(
                    {
                        "state": "robots_unavailable_not_fetched",
                        "fetch_outcome": "unknown",
                        "unknown_reason": "robots_unavailable",
                    }
                )
                llms_rows.append(row)
                continue
            decision = await engine._robots.check(url)
            if not decision.allowed:
                row.update(
                    {
                        "state": "robots_disallowed_not_fetched",
                        "fetch_outcome": "unknown",
                        "unknown_reason": "robots_disallowed",
                        "matched_rule": decision.matched_rule,
                        "matched_user_agent": decision.matched_user_agent,
                    }
                )
                llms_rows.append(row)
                continue
            # Ticket 423: record why a context file was not read, as the robots fetch does (ticket 410).
            reasons: list[str] = []
            response = await engine._bounded_fetch_response(url, on_skip=reasons.append)
            if response is None:
                row.update(
                    {
                        "state": "fetch_unavailable",
                        "fetch_outcome": "unknown",
                        "unknown_reason": reasons[-1] if reasons else "no_response",
                    }
                )
                complete = False
            else:
                row.update(classify_llms_response(response, kind=kind))
                row["fetch_outcome"] = "fetched"
            llms_rows.append(row)
    return {
        "record_type": "coverage",
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "complete": complete,
        "ruleset_version": AI_GOVERNANCE_RULESET_VERSION,
        "provider_matrix_verified_on": AI_GOVERNANCE_PROVIDER_MATRIX_VERIFIED_ON,
        "origin_count": len(selected),
        "skipped_origins": [_safe_url(origin) for origin in skipped],
        "family_count": len(AI_CRAWLER_FAMILIES),
        "tested_count": len(bot_rows) + len(llms_rows),
        "robots_documents": robots_documents,
        "bot_posture": bot_rows,
        "llms_files": llms_rows,
        "limitations": (
            "Declared robots.txt policy only: a token need not be a separate HTTP crawler, user-triggered "
            "fetchers may ignore robots.txt, and CDN/WAF rules can block a token robots.txt allows. "
            "llms.txt is a proposal; its absence is not a defect."
        ),
    }


def project_ai_governance(collected: Mapping[str, object]) -> list[dict[str, object]]:
    """Flatten collected evidence into audit report rows: coverage, observations, candidates."""
    if collected.get("record_type") != "coverage":
        return []
    raw_bots = collected.get("bot_posture", [])
    raw_llms = collected.get("llms_files", [])
    bot_rows = [dict(row) for row in raw_bots if isinstance(row, Mapping)] if isinstance(raw_bots, list) else []
    llms_rows = [dict(row) for row in raw_llms if isinstance(row, Mapping)] if isinstance(raw_llms, list) else []
    coverage = {key: value for key, value in collected.items() if key not in {"bot_posture", "llms_files"}}
    return [
        coverage,
        *[{"record_type": "bot_posture", **row} for row in bot_rows],
        *[{"record_type": "llms_file", **row} for row in llms_rows],
        *[{"record_type": "candidate", **row} for row in ai_governance_candidates(bot_rows, llms_rows)],
    ]


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.rsplit("@", 1)[-1].lower(), "", "", ""))


def _safe_url(url: str | None) -> str | None:
    return redact_url_without_digest(url) if url else None
