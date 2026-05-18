"""Tests for CMS detection functionality."""

from __future__ import annotations

import pytest

from src.crawler_cli.detection.cms import CMSDetector, CMSDetectionResult
from src.crawler_cli.models import FetchResponse


class TestCMSDetector:
    """Test cases for CMSDetector class."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.detector = CMSDetector()

    def test_get_supported_cms(self) -> None:
        """Test that supported CMS list is correct."""
        supported = self.detector.get_supported_cms()
        expected = ["wordpress", "shopify", "drupal", "joomla", "squarespace", "wix"]
        assert set(supported) == set(expected)

    def test_detect_no_cms(self) -> None:
        """Test detection when no CMS is present."""
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=b"<html><body>Plain HTML site</body></html>",
            text="<html><body>Plain HTML site</body></html>",
        )
        
        result = self.detector.detect(response)
        assert result.cms_name is None
        assert result.confidence == 0.0
        assert result.indicators == []

    def test_detect_wordpress_generator_meta(self) -> None:
        """Test WordPress detection via generator meta tag."""
        html = """
        <html>
        <head>
            <meta name="generator" content="WordPress 6.2.2" />
        </head>
        <body>WordPress site</body>
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
        assert result.cms_name == "wordpress"
        assert result.confidence > 0.2
        assert any("Meta generator" in indicator for indicator in result.indicators)

    def test_detect_wordpress_content_patterns(self) -> None:
        """Test WordPress detection via content patterns."""
        html = """
        <html>
        <head>
            <link rel="stylesheet" href="/wp-content/themes/twentytwenty/style.css" />
            <script src="/wp-includes/js/jquery/jquery.min.js"></script>
        </head>
        <body>WordPress site</body>
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
        assert result.cms_name == "wordpress"
        assert result.confidence > 0.1

    def test_detect_shopify_headers(self) -> None:
        """Test Shopify detection via headers."""
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={
                "content-type": "text/html",
                "x-shopify-stage": "production",
                "x-shopify-request-id": "12345",
            },
            body=b"<html><body>Shopify site</body></html>",
            text="<html><body>Shopify site</body></html>",
        )
        
        result = self.detector.detect(response)
        assert result.cms_name == "shopify"
        assert result.confidence > 0.1
        assert any("Header x-shopify" in indicator for indicator in result.indicators)

    def test_detect_shopify_content_patterns(self) -> None:
        """Test Shopify detection via content patterns."""
        html = """
        <html>
        <head>
            <script src="https://cdn.shopify.com/assets/shopify.js"></script>
        </head>
        <body>
            <a href="/collections/all">All Products</a>
            <a href="/products/example">Example Product</a>
        </body>
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
        assert result.cms_name == "shopify"
        assert result.confidence > 0.1

    def test_detect_drupal_headers(self) -> None:
        """Test Drupal detection via headers."""
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={
                "content-type": "text/html",
                "x-drupal-cache": "HIT",
                "x-generator": "Drupal 9",
            },
            body=b"<html><body>Drupal site</body></html>",
            text="<html><body>Drupal site</body></html>",
        )
        
        result = self.detector.detect(response)
        assert result.cms_name == "drupal"
        assert result.confidence > 0.2

    def test_detect_drupal_content_patterns(self) -> None:
        """Test Drupal detection via content patterns."""
        html = """
        <html>
        <head>
            <script src="/sites/default/files/js/drupal.js"></script>
        </head>
        <body>Drupal site</body>
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
        assert result.cms_name == "drupal"
        assert result.confidence > 0.1

    def test_detect_joomla(self) -> None:
        """Test Joomla detection."""
        html = """
        <html>
        <head>
            <meta name="generator" content="Joomla! 4 - Open Source Content Management" />
            <script src="/media/jui/js/jquery.min.js"></script>
        </head>
        <body>Joomla site</body>
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
        assert result.cms_name == "joomla"
        assert result.confidence > 0.2

    def test_detect_squarespace(self) -> None:
        """Test Squarespace detection."""
        html = """
        <html>
        <head>
            <script src="https://static.squarespace.com/static/js/squarespace.js"></script>
        </head>
        <body>Squarespace site</body>
        </html>
        """
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={
                "content-type": "text/html",
                "x-served-by-squarespace": "true",
            },
            body=html.encode(),
            text=html,
        )
        
        result = self.detector.detect(response)
        assert result.cms_name == "squarespace"
        assert result.confidence > 0.2

    def test_detect_wix(self) -> None:
        """Test Wix detection."""
        html = """
        <html>
        <head>
            <script src="https://static.wixstatic.com/sites/wix.js"></script>
        </head>
        <body>Wix site</body>
        </html>
        """
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={
                "content-type": "text/html",
                "x-wix-request-id": "12345",
            },
            body=html.encode(),
            text=html,
        )
        
        result = self.detector.detect(response)
        assert result.cms_name == "wix"
        assert result.confidence > 0.2

    def test_confidence_normalization(self) -> None:
        """Test that confidence is properly normalized to 0-1 range."""
        # Create a response with many WordPress indicators
        html = """
        <html>
        <head>
            <meta name="generator" content="WordPress 6.2.2" />
            <link rel="stylesheet" href="/wp-content/themes/twentytwenty/style.css" />
            <script src="/wp-includes/js/jquery/jquery.min.js"></script>
            <script src="/wp-content/plugins/jetpack/jetpack.js"></script>
        </head>
        <body>
            <a href="/wp-json/wp/v2/posts">API</a>
        </body>
        </html>
        """
        response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={
                "content-type": "text/html",
                "x-powered-by": "WordPress",
            },
            body=html.encode(),
            text=html,
        )
        
        result = self.detector.detect(response)
        assert result.cms_name == "wordpress"
        assert 0.0 <= result.confidence <= 1.0
        # With many indicators, confidence should be high
        assert result.confidence > 0.5

    def test_multiple_cms_conflict(self) -> None:
        """Test behavior when multiple CMS indicators are present."""
        # Mix WordPress and Shopify indicators - should pick the one with highest score
        html = """
        <html>
        <head>
            <meta name="generator" content="WordPress 6.2.2" />
            <script src="https://cdn.shopify.com/assets/shopify.js"></script>
        </head>
        <body>Conflicting CMS site</body>
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
        # Should detect one of them (WordPress has higher weight for meta generator)
        assert result.cms_name in ["wordpress", "shopify"]
        assert result.confidence > 0.0

    def test_case_insensitive_matching(self) -> None:
        """Test that pattern matching is case insensitive."""
        html = """
        <html>
        <head>
            <meta name="GENERATOR" content="WordPress 6.2.2" />
            <script src="/WP-CONTENT/themes/style.css"></script>
        </head>
        <body>WordPress site</body>
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
        assert result.cms_name == "wordpress"
        assert result.confidence > 0.0
