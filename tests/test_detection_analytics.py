"""Tests for analytics / tag manager / pixel detection."""

from __future__ import annotations

import pytest

from crawler_cli.detection.analytics import AnalyticsDetector, AnalyticsHit
from crawler_cli.models import FetchResponse


class TestAnalyticsDetector:
    """Test cases for AnalyticsDetector class."""

    def setup_method(self) -> None:
        self.detector = AnalyticsDetector()

    def test_get_supported_vendors(self) -> None:
        vendors = self.detector.get_supported_vendors()
        assert "gtm" in vendors
        assert "ga4" in vendors
        assert "meta-pixel" in vendors
        assert "hotjar" in vendors

    def test_detect_no_analytics(self) -> None:
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=b"<html><body>Plain HTML site</body></html>",
            text="<html><body>Plain HTML site</body></html>",
        )
        result = self.detector.detect(response)
        assert result.hits == []

    def test_detect_gtm_script_src(self) -> None:
        html = '<script src="https://www.googletagmanager.com/gtm.js?id=GTM-ABC123"></script>'
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        assert len(result.hits) == 1
        hit = result.hits[0]
        assert hit.vendor == "gtm"
        assert hit.category == "tag_manager"
        assert hit.identifier == "GTM-ABC123"
        assert hit.evidence_type == "script_src"
        assert hit.confidence == 1.0

    def test_detect_gtm_noscript_iframe(self) -> None:
        html = '<noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-XYZ789"></iframe></noscript>'
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        gtm_hits = [h for h in result.hits if h.vendor == "gtm"]
        assert len(gtm_hits) == 1
        assert gtm_hits[0].identifier == "GTM-XYZ789"
        assert gtm_hits[0].evidence_type == "noscript_iframe"

    def test_detect_ga4_script_src(self) -> None:
        html = '<script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX"></script>'
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        ga4_hits = [h for h in result.hits if h.vendor == "ga4"]
        assert len(ga4_hits) == 1
        assert ga4_hits[0].identifier == "G-XXXXXXXXXX"
        assert ga4_hits[0].evidence_type == "script_src"

    def test_detect_ga4_inline_config(self) -> None:
        html = "<script>gtag('config', 'G-TEST123456');</script>"
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        ga4_hits = [h for h in result.hits if h.vendor == "ga4"]
        assert len(ga4_hits) == 1
        assert ga4_hits[0].identifier == "G-TEST123456"
        assert ga4_hits[0].evidence_type == "inline_js"

    def test_detect_universal_analytics(self) -> None:
        html = '<script>ga("create", "UA-123456-1", "auto");</script>'
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        ua_hits = [h for h in result.hits if h.vendor == "universal-analytics"]
        assert len(ua_hits) == 1
        assert ua_hits[0].identifier == "UA-123456-1"

    def test_detect_meta_pixel(self) -> None:
        html = '<script>fbq("init", "1234567890");</script>'
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        pixel_hits = [h for h in result.hits if h.vendor == "meta-pixel"]
        assert len(pixel_hits) == 1
        assert pixel_hits[0].identifier == "1234567890"

    def test_detect_hotjar(self) -> None:
        html = '<script src="https://static.hotjar.com/c/hotjar-123456.js"></script>'
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        hotjar_hits = [h for h in result.hits if h.vendor == "hotjar"]
        assert len(hotjar_hits) == 1
        assert hotjar_hits[0].identifier == "123456"

    def test_detect_clarity(self) -> None:
        html = '<script src="https://www.clarity.ms/tag/abc123def"></script>'
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        clarity_hits = [h for h in result.hits if h.vendor == "clarity"]
        assert len(clarity_hits) == 1
        assert clarity_hits[0].identifier == "abc123def"

    def test_detect_segment(self) -> None:
        html = '<script src="https://cdn.segment.com/analytics.js/v1/WRITEKEY123/analytics.min.js"></script>'
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        seg_hits = [h for h in result.hits if h.vendor == "segment"]
        assert len(seg_hits) == 1
        assert seg_hits[0].identifier == "WRITEKEY123"

    def test_detect_tealium(self) -> None:
        html = '<script src="https://tags.tiqcdn.com/utag/acct/prod/dev/utag.js"></script>'
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        tealium_hits = [h for h in result.hits if h.vendor == "tealium"]
        assert len(tealium_hits) == 1
        assert tealium_hits[0].identifier == "acct/prod/dev"

    def test_detect_adobe_launch(self) -> None:
        html = '<script src="https://assets.adobedtm.com/launch-EN123.js"></script>'
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        adobe_hits = [h for h in result.hits if h.vendor == "adobe-launch"]
        assert len(adobe_hits) == 1

    def test_detect_optimizely(self) -> None:
        html = '<script src="https://cdn.optimizely.com/js/123456789.js"></script>'
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        opt_hits = [h for h in result.hits if h.vendor == "optimizely"]
        assert len(opt_hits) == 1
        assert opt_hits[0].identifier == "123456789"

    def test_detect_google_optimize_legacy(self) -> None:
        html = '<script src="https://optimize.google.com/optimize.js?id=OPT-ABC123"></script>'
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        opt_hits = [h for h in result.hits if h.vendor == "google-optimize"]
        assert len(opt_hits) == 1
        assert opt_hits[0].identifier == "OPT-ABC123"

    def test_negative_body_text_only(self) -> None:
        """Mere mention of analytics in body text must not trigger."""
        html = "<html><body>We use Google Analytics to track visitors.</body></html>"
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        assert result.hits == []

    def test_multi_vendor_page(self) -> None:
        html = """
        <html>
        <head>
            <script src="https://www.googletagmanager.com/gtm.js?id=GTM-ABC123"></script>
            <script async src="https://www.googletagmanager.com/gtag/js?id=G-XYZ789"></script>
            <script src="https://connect.facebook.net/en_US/fbevents.js"></script>
        </head>
        <body>Multi-vendor page</body>
        </html>
        """
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        vendors = {h.vendor for h in result.hits}
        assert "gtm" in vendors
        assert "ga4" in vendors
        assert "meta-pixel" in vendors
        assert len(result.hits) >= 3

    def test_cookie_detection(self) -> None:
        html = "<html><body>Site</body></html>"
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={
                "content-type": "text/html",
                "set-cookie": "_ga=GA1.2.123456789.1234567890; _gid=GA1.2.987654321.1234567890",
            },
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        cookie_hits = [h for h in result.hits if h.evidence_type == "cookie"]
        assert len(cookie_hits) == 2
        assert all(h.vendor == "universal-analytics" for h in cookie_hits)

    def test_identifier_case_sensitivity(self) -> None:
        """GTM and GA4 identifiers are uppercase; detector must preserve case."""
        html = '<script src="https://www.googletagmanager.com/gtm.js?id=gtm-lowercase"></script>'
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        # Lowercase gtm- should NOT match (regex requires uppercase)
        gtm_hits = [h for h in result.hits if h.vendor == "gtm"]
        assert len(gtm_hits) == 0

    def test_deduplication_same_vendor_identifier(self) -> None:
        """Duplicate (vendor, identifier, evidence_type) should be deduplicated, keeping highest confidence."""
        html = """
        <script src="https://www.googletagmanager.com/gtm.js?id=GTM-DUP123"></script>
        <script src="https://www.googletagmanager.com/gtag/js?id=GTM-DUP123"></script>
        """
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )
        result = self.detector.detect(response)
        gtm_hits = [h for h in result.hits if h.vendor == "gtm"]
        # Should dedupe to one hit for GTM-DUP123 script_src
        script_hits = [h for h in gtm_hits if h.evidence_type == "script_src"]
        assert len(script_hits) == 1
        assert script_hits[0].confidence == 1.0  # highest wins
