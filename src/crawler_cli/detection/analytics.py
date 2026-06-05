"""Analytics, tag manager, marketing pixel and A/B-test platform detection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ..models import FetchResponse


@dataclass(slots=True)
class AnalyticsHit:
    """A single detected analytics vendor signal."""

    vendor: str
    category: Literal["tag_manager", "analytics", "pixel", "ab_test"]
    identifier: str | None
    evidence_type: Literal["script_src", "inline_js", "noscript_iframe", "cookie", "header", "meta"]
    evidence_snippet: str
    confidence: float


@dataclass(slots=True)
class AnalyticsDetectionResult:
    """Result of analytics detection — zero or more hits per page."""

    hits: list[AnalyticsHit]


class AnalyticsDetector:
    """Detects mainstream analytics / tag-management platforms from HTML & headers."""

    # Precompiled regex tables — built once per instance.
    # Each entry: (vendor, category, evidence_type, pattern_regex, identifier_regex_or_none, confidence)

    _SCRIPT_PATTERNS: list[tuple[str, str, str, re.Pattern[str], re.Pattern[str] | None, float]] = [
        # Tag managers
        ("gtm", "tag_manager", "script_src", re.compile(r"googletagmanager\.com/gtm\.js\?id=(GTM-[A-Z0-9]+)"), None, 1.0),
        ("gtm", "tag_manager", "script_src", re.compile(r"googletagmanager\.com/gtag/js\?id=(GTM-[A-Z0-9]+)"), None, 0.95),
        ("adobe-launch", "tag_manager", "script_src", re.compile(r"assets\.adobedtm\.com/"), None, 1.0),
        ("tealium", "tag_manager", "script_src", re.compile(r"tags\.tiqcdn\.com/utag/[^/]+/[^/]+/[^/]+/utag\.js"), re.compile(r"tags\.tiqcdn\.com/utag/([^/]+/[^/]+/[^/]+)/utag\.js"), 1.0),
        ("segment", "tag_manager", "script_src", re.compile(r"cdn\.segment\.com/analytics\.js/v1/[^/]+/analytics\.min\.js"), re.compile(r"cdn\.segment\.com/analytics\.js/v1/([^/]+)/analytics\.min\.js"), 1.0),
        ("ensighten", "tag_manager", "script_src", re.compile(r"nexus\.ensighten\.com/"), None, 1.0),
        ("matomo-tag-manager", "tag_manager", "script_src", re.compile(r"/js/container_([a-zA-Z0-9_-]+)\.js"), None, 1.0),
        ("commanders-act", "tag_manager", "script_src", re.compile(r"cdn\.tagcommander\.com/[^/]+/"), None, 1.0),
        # Web analytics
        ("ga4", "analytics", "script_src", re.compile(r"googletagmanager\.com/gtag/js\?id=(G-[A-Z0-9]+)"), None, 1.0),
        ("universal-analytics", "analytics", "script_src", re.compile(r"google-analytics\.com/analytics\.js"), None, 0.9),
        ("universal-analytics", "analytics", "script_src", re.compile(r"google-analytics\.com/ga\.js"), None, 0.9),
        ("google-ads", "analytics", "script_src", re.compile(r"googletagmanager\.com/gtag/js\?id=(AW-[A-Z0-9]+)"), None, 1.0),
        ("floodlight", "analytics", "script_src", re.compile(r"googletagmanager\.com/gtag/js\?id=(DC-[A-Z0-9]+)"), None, 1.0),
        ("adobe-analytics", "analytics", "script_src", re.compile(r"(s_code|AppMeasurement)\.js"), None, 0.95),
        ("matomo", "analytics", "script_src", re.compile(r"(matomo|piwik)\.js"), None, 1.0),
        ("plausible", "analytics", "script_src", re.compile(r"plausible\.io/js/script\.js"), None, 1.0),
        ("fathom", "analytics", "script_src", re.compile(r"cdn\.usefathom\.com/script\.js"), None, 1.0),
        ("heap", "analytics", "script_src", re.compile(r"cdn\.heapanalytics\.com"), None, 1.0),
        ("mixpanel", "analytics", "script_src", re.compile(r"cdn\.mxpnl\.com/libs/mixpanel-.*\.min\.js"), None, 1.0),
        ("amplitude", "analytics", "script_src", re.compile(r"cdn\.amplitude\.com/"), None, 1.0),
        ("snowplow", "analytics", "script_src", re.compile(r"(sp\.js|cf\.snplow\.net)"), None, 1.0),
        ("hotjar", "analytics", "script_src", re.compile(r"static\.hotjar\.com/c/hotjar-([0-9]+)\.js"), None, 1.0),
        ("clarity", "analytics", "script_src", re.compile(r"clarity\.ms/tag/([a-zA-Z0-9]+)"), None, 1.0),
        ("cloudflare-analytics", "analytics", "script_src", re.compile(r"static\.cloudflareinsights\.com/beacon\.min\.js"), None, 1.0),
        ("simple-analytics", "analytics", "script_src", re.compile(r"scripts\.simpleanalyticscdn\.com/latest\.js"), None, 1.0),
        ("umami", "analytics", "script_src", re.compile(r"(analytics\.umami\.is|umami\.is)/script\.js"), None, 1.0),
        # Marketing pixels
        ("meta-pixel", "pixel", "script_src", re.compile(r"connect\.facebook\.net/.*/fbevents\.js"), None, 1.0),
        ("linkedin-insight", "pixel", "script_src", re.compile(r"snap\.licdn\.com/li\.lms-analytics/insight\.min\.js"), None, 1.0),
        ("twitter-pixel", "pixel", "script_src", re.compile(r"static\.ads-twitter\.com/uwt\.js"), None, 1.0),
        ("tiktok-pixel", "pixel", "script_src", re.compile(r"analytics\.tiktok\.com/i18n/pixel/events\.js"), None, 1.0),
        ("pinterest-tag", "pixel", "script_src", re.compile(r"s\.pinimg\.com/ct/core\.js"), None, 1.0),
        ("reddit-pixel", "pixel", "script_src", re.compile(r"www\.redditstatic\.com/ads/pixel\.js"), None, 1.0),
        # A/B testing
        ("optimizely", "ab_test", "script_src", re.compile(r"cdn\.optimizely\.com/js/([a-zA-Z0-9]+)\.js"), None, 1.0),
        ("vwo", "ab_test", "script_src", re.compile(r"dev\.visualwebsiteoptimizer\.com/"), None, 1.0),
        ("google-optimize", "ab_test", "script_src", re.compile(r"optimize\.google\.com/optimize\.js\?id=(OPT-[A-Z0-9]+)"), None, 1.0),
        ("ab-tasty", "ab_test", "script_src", re.compile(r"try\.abtasty\.com/([a-zA-Z0-9_-]+)\.js"), None, 1.0),
        ("convert", "ab_test", "script_src", re.compile(r"cdn-3\.convertexperiments\.com/"), None, 1.0),
    ]

    _NOSCRIPT_PATTERNS: list[tuple[str, str, str, re.Pattern[str], re.Pattern[str] | None, float]] = [
        ("gtm", "tag_manager", "noscript_iframe", re.compile(r"googletagmanager\.com/ns\.html\?id=(GTM-[A-Z0-9]+)"), None, 0.95),
    ]

    _INLINE_PATTERNS: list[tuple[str, str, str, re.Pattern[str], re.Pattern[str] | None, float]] = [
        ("ga4", "analytics", "inline_js", re.compile(r"gtag\(['\"]config['\"],\s*['\"](G-[A-Z0-9]+)['\"]"), None, 0.95),
        ("ga4", "analytics", "inline_js", re.compile(r"dataLayer\.push\(\{[^}]*['\"]gtag\.config['\"]"), None, 0.7),
        ("universal-analytics", "analytics", "inline_js", re.compile(r"ga\(['\"]create['\"],\s*['\"](UA-\d+-\d+)['\"]"), None, 0.95),
        ("universal-analytics", "analytics", "inline_js", re.compile(r"_gaq\.push"), None, 0.8),
        ("meta-pixel", "pixel", "inline_js", re.compile(r"fbq\(['\"]init['\"],\s*['\"](\d+)['\"]"), None, 0.95),
        ("meta-pixel", "pixel", "inline_js", re.compile(r"fbq\(['\"]track['\"]"), None, 0.8),
        ("adobe-analytics", "analytics", "inline_js", re.compile(r"s\.t\(\)"), None, 0.9),
        ("adobe-analytics", "analytics", "inline_js", re.compile(r"s\.tl\(\)"), None, 0.9),
        ("adobe-analytics", "analytics", "inline_js", re.compile(r"s_account\s*="), None, 0.85),
        ("matomo", "analytics", "inline_js", re.compile(r"_paq\.push"), None, 0.9),
        ("heap", "analytics", "inline_js", re.compile(r"heap\.load\(['\"]([^'\"]+)['\"]\)"), None, 0.95),
        ("mixpanel", "analytics", "inline_js", re.compile(r"mixpanel\.init\(['\"]([^'\"]+)['\"]"), None, 0.95),
        ("amplitude", "analytics", "inline_js", re.compile(r"amplitude\.getInstance\(\)\.init"), None, 0.9),
        ("snowplow", "analytics", "inline_js", re.compile(r"snowplow\(['\"]newTracker['\"]"), None, 0.9),
        ("segment", "tag_manager", "inline_js", re.compile(r"analytics\.load\(['\"]([^'\"]+)['\"]\)"), None, 0.95),
        ("twitter-pixel", "pixel", "inline_js", re.compile(r"twq\(['\"]init['\"],\s*['\"]([^'\"]+)['\"]"), None, 0.95),
        ("tiktok-pixel", "pixel", "inline_js", re.compile(r"ttq\.load\(['\"]([^'\"]+)['\"]"), None, 0.95),
        ("pinterest-tag", "pixel", "inline_js", re.compile(r"pintrk\(['\"]load['\"],\s*['\"]([^'\"]+)['\"]"), None, 0.95),
        ("reddit-pixel", "pixel", "inline_js", re.compile(r"rdt\(['\"]init['\"],\s*['\"]([^'\"]+)['\"]"), None, 0.95),
        ("linkedin-insight", "pixel", "inline_js", re.compile(r"_linkedin_partner_id\s*=\s*['\"]?(\d+)"), None, 0.95),
        ("vwo", "ab_test", "inline_js", re.compile(r"_vwo_code"), None, 0.9),
        ("optimizely", "ab_test", "inline_js", re.compile(r"window\['optimizelyData'\]"), None, 0.7),
    ]

    _COOKIE_PATTERNS: list[tuple[str, str, str, re.Pattern[str], re.Pattern[str] | None, float]] = [
        ("universal-analytics", "analytics", "cookie", re.compile(r"_ga=[^;]+"), re.compile(r"(_ga=[^;]+)"), 0.7),
        ("universal-analytics", "analytics", "cookie", re.compile(r"_gid=[^;]+"), re.compile(r"(_gid=[^;]+)"), 0.7),
        ("adobe-analytics", "analytics", "cookie", re.compile(r"s_cc=[^;]+"), re.compile(r"(s_cc=[^;]+)"), 0.7),
    ]

    def __init__(self) -> None:
        # Compile all patterns eagerly
        self._script_patterns = self._SCRIPT_PATTERNS
        self._noscript_patterns = self._NOSCRIPT_PATTERNS
        self._inline_patterns = self._INLINE_PATTERNS
        self._cookie_patterns = self._COOKIE_PATTERNS

    def detect(self, response: FetchResponse) -> AnalyticsDetectionResult:
        """Detect all analytics vendors present in the response."""
        hits: list[AnalyticsHit] = []
        text = response.text
        headers = response.headers

        # 1. Script src patterns
        for vendor, category, evidence_type, pattern, id_pattern, confidence in self._script_patterns:
            for match in pattern.finditer(text):
                snippet = match.group(0)[:200]
                identifier = self._extract_identifier(match, id_pattern)
                hits.append(AnalyticsHit(vendor, category, identifier, evidence_type, snippet, confidence))

        # 2. Noscript iframe fallback
        for vendor, category, evidence_type, pattern, id_pattern, confidence in self._noscript_patterns:
            for match in pattern.finditer(text):
                snippet = match.group(0)[:200]
                identifier = self._extract_identifier(match, id_pattern)
                hits.append(AnalyticsHit(vendor, category, identifier, evidence_type, snippet, confidence))

        # 3. Inline JS markers
        for vendor, category, evidence_type, pattern, id_pattern, confidence in self._inline_patterns:
            for match in pattern.finditer(text):
                snippet = match.group(0)[:200]
                identifier = self._extract_identifier(match, id_pattern)
                hits.append(AnalyticsHit(vendor, category, identifier, evidence_type, snippet, confidence))

        # 4. Response headers / cookies
        set_cookie = headers.get("set-cookie", "")
        for vendor, category, evidence_type, pattern, id_pattern, confidence in self._cookie_patterns:
            for match in pattern.finditer(set_cookie):
                snippet = match.group(0)[:200]
                identifier = self._extract_identifier(match, id_pattern)
                hits.append(AnalyticsHit(vendor, category, identifier, evidence_type, snippet, confidence))

        # Deduplicate by (vendor, identifier, evidence_type) — keep highest confidence
        seen: dict[tuple[str, str | None, str], AnalyticsHit] = {}
        for hit in hits:
            key = (hit.vendor, hit.identifier, hit.evidence_type)
            existing = seen.get(key)
            if existing is None or hit.confidence > existing.confidence:
                seen[key] = hit

        return AnalyticsDetectionResult(list(seen.values()))

    @staticmethod
    def _extract_identifier(match: re.Match[str], id_pattern: re.Pattern[str] | None) -> str | None:
        """Extract identifier from a regex match."""
        if id_pattern is not None:
            id_match = id_pattern.search(match.group(0))
            if id_match:
                return id_match.group(1) if id_match.lastindex else id_match.group(0)
        # Fallback: if the main pattern has a capture group, use it
        if match.lastindex:
            return match.group(1)
        return None

    def get_supported_vendors(self) -> list[str]:
        """Return list of vendor slugs that this detector recognises."""
        vendors: set[str] = set()
        for patterns in (self._script_patterns, self._noscript_patterns, self._inline_patterns, self._cookie_patterns):
            for vendor, _, _, _, _, _ in patterns:
                vendors.add(vendor)
        return sorted(vendors)
