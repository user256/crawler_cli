"""CMS Detection module for identifying popular content management systems."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from ..models import FetchResponse


@dataclass(slots=True)
class CMSDetectionResult:
    """Result of CMS detection."""
    cms_name: str | None
    confidence: float
    indicators: list[str]


class CMSDetector:
    """Detects popular Content Management Systems from HTTP responses and HTML content."""
    
    def __init__(self) -> None:
        self._patterns = {
            "wordpress": {
                "headers": [
                    (r"x-powered-by", r"wordpress"),
                    (r"link", r".*/wp-content/.*"),
                ],
                "meta_tags": [
                    (r"generator", r"wordpress\s+\d+\.\d+\.\d+"),
                    (r"generator", r"wordpress\.org"),
                ],
                "content_patterns": [
                    r"/wp-content/",
                    r"/wp-includes/",
                    r"/wp-json/",
                    r"wp-.*\.js",
                    r"wp-.*\.css",
                    r"wordpress",
                ],
                "scripts": [
                    r"/wp-content/themes/",
                    r"/wp-content/plugins/",
                ]
            },
            "shopify": {
                "headers": [
                    (r"x-shopify", r".+"),
                    (r"x-shopify-stage", r".+"),
                ],
                "meta_tags": [
                    (r"generator", r"shopify"),
                ],
                "content_patterns": [
                    r"cdn\.shopify\.com",
                    r"shopify\.com",
                    r"/apps/",
                    r"/collections/",
                    r"/products/",
                    r"variant=",
                ],
                "scripts": [
                    r"cdn\.shopify\.com",
                    r"Shopify\.",
                ]
            },
            "drupal": {
                "headers": [
                    (r"x-drupal-cache", r".+"),
                    (r"x-generator", r"drupal\s+\d+"),
                ],
                "meta_tags": [
                    (r"generator", r"drupal\s+\d+"),
                    (r"drupal-settings-json", r".+"),
                ],
                "content_patterns": [
                    r"/sites/default/files/",
                    r"/sites/all/",
                    r"/modules/",
                    r"/themes/",
                    r"drupal\.js",
                ],
                "scripts": [
                    r"/sites/default/files/",
                    r"Drupal\.settings",
                ]
            },
            "joomla": {
                "headers": [
                    (r"x-powered-by", r"joomla"),
                ],
                "meta_tags": [
                    (r"generator", r"joomla"),
                ],
                "content_patterns": [
                    r"/media/",
                    r"/components/",
                    r"/modules/",
                    r"/templates/",
                    r"joomla",
                ],
                "scripts": [
                    r"/media/",
                    r"Joomla\.",
                ]
            },
            "squarespace": {
                "headers": [
                    (r"x-served-by-squarespace", r".+"),
                ],
                "meta_tags": [
                    (r"generator", r"squarespace"),
                ],
                "content_patterns": [
                    r"squarespace\.com",
                    r"/s/",
                    r"static\.squarespace\.com",
                    r"static1\.squarespace\.com",
                ],
                "scripts": [
                    r"squarespace\.com",
                    r"Squarespace\.",
                ]
            },
            "wix": {
                "headers": [
                    (r"x-wix-request-id", r".+"),
                    (r"x-wix-meta-site-id", r".+"),
                ],
                "meta_tags": [
                    (r"generator", r"wix\.com"),
                ],
                "content_patterns": [
                    r"wix\.com",
                    r"static\.wixstatic\.com",
                    r"viewer\.wix\.com",
                    r"/wix-.*\.js",
                ],
                "scripts": [
                    r"wix\.com",
                    r"Wix\.",
                ]
            }
        }
    
    def detect(self, response: FetchResponse) -> CMSDetectionResult:
        """Detect CMS from HTTP response and HTML content."""
        scores = {}
        indicators = {}
        
        for cms_name, patterns in self._patterns.items():
            score, found_indicators = self._detect_cms(response, patterns)
            if score > 0:
                scores[cms_name] = score
                indicators[cms_name] = found_indicators
        
        if not scores:
            return CMSDetectionResult(None, 0.0, [])
        
        # Return the CMS with highest score
        best_cms = max(scores, key=scores.get)
        confidence = min(scores[best_cms] / 10.0, 1.0)  # Normalize to 0-1
        
        return CMSDetectionResult(
            cms_name=best_cms,
            confidence=confidence,
            indicators=indicators[best_cms]
        )
    
    def _detect_cms(self, response: FetchResponse, patterns: dict[str, Any]) -> tuple[float, list[str]]:
        """Detect a specific CMS using its patterns."""
        score = 0.0
        found_indicators = []
        
        # Check headers
        for header_name, pattern in patterns.get("headers", []):
            header_value = response.headers.get(header_name.lower(), "")
            if re.search(pattern, header_value, re.IGNORECASE):
                score += 2.0
                found_indicators.append(f"Header {header_name}: {pattern}")
        
        # Check meta tags (in HTML content)
        for meta_name, pattern in patterns.get("meta_tags", []):
            meta_pattern = rf'<meta[^>]+name=["\']{re.escape(meta_name)}["\'][^>]+content=["\'][^"\']*{pattern}[^"\']*["\']'
            if re.search(meta_pattern, response.text, re.IGNORECASE):
                score += 3.0
                found_indicators.append(f"Meta {meta_name}: {pattern}")
        
        # Check content patterns
        for pattern in patterns.get("content_patterns", []):
            if re.search(pattern, response.text, re.IGNORECASE):
                score += 1.0
                found_indicators.append(f"Content: {pattern}")
        
        # Check script sources
        script_pattern = r'<script[^>]+src=["\']([^"\']+)["\']'
        for script_src in re.findall(script_pattern, response.text):
            for pattern in patterns.get("scripts", []):
                if re.search(pattern, script_src, re.IGNORECASE):
                    score += 2.0
                    found_indicators.append(f"Script: {pattern}")
                    break
        
        return score, found_indicators
    
    def get_supported_cms(self) -> list[str]:
        """Get list of supported CMS platforms."""
        return list(self._patterns.keys())
