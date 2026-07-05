"""Performance benchmark for analytics detection."""

from __future__ import annotations

import time


from crawler_cli.detection.analytics import AnalyticsDetector
from crawler_cli.models import FetchResponse


def _build_mixed_html() -> str:
    """Build a realistic HTML page with multiple vendors."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://www.googletagmanager.com/gtm.js?id=GTM-ABC123"></script>
        <script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX"></script>
        <script src="https://connect.facebook.net/en_US/fbevents.js"></script>
        <script src="https://static.hotjar.com/c/hotjar-123456.js"></script>
        <script src="https://www.clarity.ms/tag/abc123def"></script>
        <script>gtag('config', 'G-TEST123456');</script>
        <script>fbq('init', '1234567890');</script>
        <noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-XYZ789"></iframe></noscript>
    </head>
    <body>
        <h1>Test Page</h1>
        <p>This page contains multiple analytics vendors for benchmarking.</p>
    </body>
    </html>
    """


class TestAnalyticsDetectorPerf:
    def setup_method(self) -> None:
        self.detector = AnalyticsDetector()
        self.html = _build_mixed_html()
        self.response = FetchResponse(
            url="https://example.com",
            requested_url="https://example.com",
            status=200,
            headers={"content-type": "text/html"},
            body=self.html.encode(),
            text=self.html,
        )

    def test_p99_under_5ms(self) -> None:
        """Detection must complete in ≤5ms p99 per page."""
        iterations = 1000
        times: list[float] = []
        for _ in range(iterations):
            start = time.perf_counter()
            self.detector.detect(self.response)
            elapsed = (time.perf_counter() - start) * 1000.0
            times.append(elapsed)

        times.sort()
        p99 = times[int(iterations * 0.99)]
        p50 = times[int(iterations * 0.50)]
        max_ms = times[-1]

        print(f"\nPerf: p50={p50:.3f}ms p99={p99:.3f}ms max={max_ms:.3f}ms")
        assert p99 <= 5.0, f"p99 {p99:.3f}ms exceeds 5ms budget"
