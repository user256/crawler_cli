from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .detection.analytics import AnalyticsDetectionResult
    from .detection.cms import CMSDetectionResult


BodyTruncationReason = Literal[
    "max_response_bytes",
    "max_bytes",
    "incomplete_content_encoding",
    "unsupported_content_encoding",
]
JavaScriptSourceKind = Literal["inline_script", "external_script"]
JavaScriptLiteralKind = Literal[
    "absolute",
    "protocol_relative",
    "root_relative",
    "path_relative",
    "query_relative",
]
JavaScriptUrlClassification = Literal["page", "api", "asset", "action"]
CssSourceKind = Literal["inline_style", "style_attribute", "external_stylesheet"]
CssTokenKind = Literal["url", "import"]
UrlCandidateConfidence = Literal["high", "medium", "low"]
BrowserRequestOutcome = Literal["issued", "response", "finished", "failed"]
RenderSourceKind = Literal["render_network", "render_dom"]


@dataclass(slots=True)
class BrowserRuntime:
    provider: Literal["chromium", "cdp", "obscura"]
    cdp_endpoint: str | None = None
    managed: bool | None = None
    stealth: bool | None = None
    persistent: bool | None = None
    channel: str | None = None
    executable_path: str | None = None
    user_data_dir: str | None = None
    profile_directory: str | None = None
    headless: bool | None = None


@dataclass(slots=True)
class BrowserRequestObservation:
    url: str
    method: str
    resource_type: str
    outcome: BrowserRequestOutcome = "issued"
    status: int | None = None
    failure: str | None = None
    occurrence_count: int = 1


@dataclass(slots=True)
class FetchResponse:
    url: str
    requested_url: str
    status: int
    headers: dict[str, str]
    body: bytes
    text: str
    ttfb_seconds: float | None = None
    """Time to first byte: request send → first response byte (ticket 029)."""
    elapsed_seconds: float | None = None
    """Total fetch duration: request send → full body received (ticket 029)."""
    body_truncated: bool = False
    """True when the response body was capped at max_response_bytes during streaming."""
    wire_bytes: int = 0
    """Raw HTTP transfer bytes read, before Content-Encoding decoding."""
    decoded_bytes: int = 0
    """Decoded response bytes retained for consumers, before text decoding."""
    accounted_bytes: int = 0
    """Bytes charged to a run ``max_bytes`` budget (currently wire bytes)."""
    body_truncation_reason: BodyTruncationReason | None = None
    """The response cap or run budget that made this body partial."""
    lcp_ms: float | None = None
    """Largest Contentful Paint in ms — lab metric, Playwright only (ticket 046)."""
    cls: float | None = None
    """Cumulative Layout Shift (unitless) — lab metric, Playwright only (ticket 046)."""
    inp_ms: float | None = None
    """Interaction to Next Paint in ms — lab metric, Playwright only (ticket 046)."""
    redirect_chain: list[dict[str, Any]] = field(default_factory=list)
    """Ordered redirect hops before the final response, each ``{"url", "status"}``
    (ticket 122). Populated from aiohttp/curl_cffi ``response.history`` and the
    Playwright request redirect chain; empty when the request was not redirected.
    Enables redirect validation in ``compare-urls`` (301 vs 302, hop count,
    intermediate URLs) instead of only knowing the final URL."""
    raw_text: str | None = None
    """Original main-document response text before DOM hydration, Playwright only."""
    observed_requests: list[BrowserRequestObservation] = field(default_factory=list)
    """Bounded browser network observations, populated only when explicitly enabled."""
    render_settled: bool | None = None
    """Whether configured Playwright settle/selector waits completed."""


@dataclass(slots=True)
class HreflangLink:
    hreflang: str
    href: str
    source: Literal["http_header", "html_head", "sitemap"]


@dataclass(slots=True)
class RobotsDirectives:
    noindex: bool = False
    nofollow: bool = False
    raw: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExtractedContent:
    title: str | None
    meta_description: str | None
    meta_robots: RobotsDirectives
    x_robots_tag: RobotsDirectives
    canonical: str | None
    x_canonical: str | None
    hreflang_links: list[HreflangLink]
    html_lang: str | None
    headings: dict[str, list[str]]
    text: str
    word_count: int
    metadata: dict[str, Any]
    amphtml: str | None = None
    """Absolute URL from ``<link rel="amphtml" href=...>`` — the page's declared
    AMP variant.  Captured so AMP variants get a first-class page<->AMP pairing
    signal instead of being dropped at extraction time (ticket 103)."""
    schema_data: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class DiscoveredLink:
    href: str
    anchor_text: str | None
    xpath: str
    is_image: bool
    fragment: str | None = None
    url_parameters: str | None = None
    original_href: str | None = None


@dataclass(slots=True)
class JavaScriptUrlCandidate:
    """A static URL-like JavaScript literal, not a normal crawlable link.

    ``follow_eligible`` is intentionally stricter than URL validity. Assets,
    API/action-shaped paths, credential-bearing URLs, and dynamic templates
    remain useful inventory evidence but must not enter the frontier.
    """

    url: str
    source_kind: JavaScriptSourceKind
    script_source: str
    script_index: int | None
    literal_kind: JavaScriptLiteralKind
    classification: JavaScriptUrlClassification
    follow_eligible: bool
    occurrence_count: int = 1
    confidence: UrlCandidateConfidence = "low"
    confidence_weight: float = 0.15
    resolution_base: Literal["document", "asset"] = "document"


@dataclass(slots=True)
class CssUrlCandidate:
    """A URL token published in inline or linked CSS.

    CSS references are strong resource evidence, but only page-shaped values
    are eligible for the explicitly enabled speculative page frontier.
    """

    url: str
    source_kind: CssSourceKind
    stylesheet_source: str
    style_index: int | None
    token_kind: CssTokenKind
    classification: JavaScriptUrlClassification
    follow_eligible: bool
    occurrence_count: int = 1
    confidence: UrlCandidateConfidence = "high"
    confidence_weight: float = 0.6
    resolution_base: Literal["document", "asset"] = "asset"


@dataclass(slots=True)
class RenderUrlCandidate:
    url: str
    source_kind: RenderSourceKind
    classification: JavaScriptUrlClassification
    follow_eligible: bool
    resource_type: str | None = None
    method: str = "GET"
    outcome: BrowserRequestOutcome | None = None
    status: int | None = None
    occurrence_count: int = 1
    confidence: UrlCandidateConfidence = "high"


@dataclass(slots=True)
class CrawlResult:
    requested_url: str
    final_url: str
    status: int
    headers: dict[str, str]
    content_type: str | None
    fetch_backend: str
    extracted: ExtractedContent | None
    raw_html: str | None
    body_truncated: bool = False
    wire_bytes: int = 0
    decoded_bytes: int = 0
    accounted_bytes: int = 0
    body_truncation_reason: BodyTruncationReason | None = None
    content_hash_sha256: str | None = None
    content_hash_simhash: int | None = None
    discovered_links: list[DiscoveredLink] = field(default_factory=list)
    javascript_url_candidates: list[JavaScriptUrlCandidate] = field(default_factory=list)
    css_url_candidates: list[CssUrlCandidate] = field(default_factory=list)
    speculative_rejection_counts: dict[str, int] = field(default_factory=dict)
    render_url_candidates: list[RenderUrlCandidate] = field(default_factory=list)
    render_discovery_attempted: bool = False
    render_discovery_complete: bool | None = None
    render_discovery_skip_reason: str | None = None
    allowed_by_robots: bool | None = None
    skip_reason: str | None = None
    persist_error: str | None = None
    challenge: str | None = None
    """Bot-challenge vendor (cloudflare/datadome/...) if this response was an
    anti-bot interstitial rather than real content (ticket 074/089). When set,
    ``skip_reason`` is ``bot_challenge``, content is not extracted/persisted,
    and the result is counted as blocked rather than crawled."""
    detected_cms: "CMSDetectionResult | None" = None
    detected_analytics: "AnalyticsDetectionResult | None" = None
    browser_runtime: BrowserRuntime | None = None
    ttfb_seconds: float | None = None
    total_duration_seconds: float | None = None
    custom_data: dict[str, Any] | None = None
    lcp_ms: float | None = None
    """Largest Contentful Paint in ms — lab metric, Playwright only (ticket 046)."""
    cls: float | None = None
    """Cumulative Layout Shift (unitless) — lab metric, Playwright only (ticket 046)."""
    inp_ms: float | None = None
    """Interaction to Next Paint in ms — lab metric, Playwright only (ticket 046)."""
    redirect_chain: list[dict[str, Any]] = field(default_factory=list)
    """Redirect hops carried through from :class:`FetchResponse` (ticket 122)."""


@dataclass(slots=True)
class CrawlJobResult:
    mode: Literal["list", "open"]
    seed_urls: list[str]
    results: list[CrawlResult]
    saved_to: str | None = None
    max_urls: int | None = None
    run_id: str | None = None
    """Explicit crawl-run identity for resumable open crawls (ticket 086)."""
    retry_attempts: int = 0
    """Total transient-error attempts that were retried and do not appear in
    *results* (ticket-062).  Surfaced in the CLI summary."""
    interrupted: bool = False
    """True when the crawl was stopped early via a signal (ticket-064)."""
    refresh_skipped_count: int = 0
    """URLs skipped at enqueue time because they were fetched within the
    --refresh-days window (ticket 080). Surfaced in the CLI summary."""
    frontier_mark_done_failed_urls: list[str] = field(default_factory=list)
    """Persisted URLs left pending because frontier mark-done failed (ticket 115).

    These URLs are safe to retry with ``--resume``: their page data was
    persisted, but their frontier bookkeeping was not completed.
    """
    crawl_run_status: str | None = None
    """Final status recorded for the open crawl run, when applicable."""
    budget_requests_started: int = 0
    budget_wire_bytes: int = 0
    budget_decoded_bytes: int = 0
    budget_accounted_bytes: int = 0
    budget_stop_reason: Literal["max_requests", "max_bytes"] | None = None
    """Typed terminal cause for a deliberately partial budgeted crawl."""
    javascript_url_candidate_count: int = 0
    """Unique static JS URL candidates observed before result compaction."""
    javascript_url_enqueued_count: int = 0
    """JS candidates newly inserted into the open-crawl frontier."""
    css_url_candidate_count: int = 0
    """Unique CSS URL candidates observed before result compaction."""
    css_url_enqueued_count: int = 0
    """CSS candidates newly inserted into the open-crawl frontier."""
    speculative_capped_count: int = 0
    """Follow-eligible candidates held out by the per-host outstanding cap."""
    render_url_candidate_count: int = 0
    render_dom_enqueued_count: int = 0
    render_discovery_attempt_count: int = 0
    authorization_scope: dict[str, Any] | None = None
    """Canonical, secret-free scope snapshot when a scope manifest was active.

    ``None`` for an ordinary technical-SEO crawl, which stays manifest-optional
    (ticket 148). When populated it carries the authorisation reference, the
    validity window, the exact allowed origins, the path policy, and the
    attestation notice — never the manifest's free-text notes or its filesystem
    path."""

    @property
    def crawled_count(self) -> int:
        return sum(1 for result in self.results if result.skip_reason is None)

    @property
    def blocked_count(self) -> int:
        return sum(1 for result in self.results if result.skip_reason == "robots_txt_disallow")

    @property
    def persist_error_count(self) -> int:
        return sum(1 for result in self.results if result.persist_error is not None)

    @property
    def persist_failed_urls(self) -> list[str]:
        """URLs whose fetched page failed to write to the store (ticket 092)."""
        return [result.final_url or result.requested_url for result in self.results if result.persist_error is not None]

    @property
    def frontier_mark_done_error_count(self) -> int:
        """Number of persisted URLs whose frontier completion is resumable."""
        return len(self.frontier_mark_done_failed_urls)

    @property
    def durability(self) -> Literal["durable", "partially_durable", "saved_output_only"]:
        """How durable the crawl results are after persistence (ticket 092).

        - ``durable``: every crawled page persisted successfully
        - ``partially_durable``: some crawled pages persisted, some failed
        - ``saved_output_only``: no crawled page persisted; data only in
          ``saved_to`` / in-memory results
        """
        crawled = [result for result in self.results if result.skip_reason is None]
        failed = [result for result in crawled if result.persist_error is not None]
        if not failed:
            return "durable"
        ok = len(crawled) - len(failed)
        if ok > 0:
            return "partially_durable"
        return "saved_output_only"

    @property
    def challenge_blocked_count(self) -> int:
        """Pages that were anti-bot interstitials, not real content (ticket 074)."""
        return sum(1 for result in self.results if result.challenge is not None)


@dataclass(slots=True)
class SitemapUrl:
    loc: str
    lastmod: str | None = None
    hreflang_links: list[HreflangLink] = field(default_factory=list)


@dataclass(slots=True)
class SitemapDocument:
    url: str
    kind: Literal["sitemap", "sitemap_index", "text"]
    urls: list[SitemapUrl] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
