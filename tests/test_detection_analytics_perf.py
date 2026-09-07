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
        """Detection must consume no more than 5ms of CPU at p99 per page.

        The budget is asserted against process CPU time, not wall clock. The
        detector is pure CPU work, so CPU time measures what this test is
        actually about. Wall clock additionally measures how long the OS chose
        to run something else, which under a loaded full-suite run inflates the
        tail far past the budget while the detector itself is unchanged — the
        original wall-clock assertion failed for that reason alone and passed
        when run in isolation. Wall clock is still recorded and reported.
        """
        iterations = 1000
        cpu_times: list[float] = []
        wall_times: list[float] = []
        for _ in range(iterations):
            wall_start = time.perf_counter()
            cpu_start = time.process_time()
            self.detector.detect(self.response)
            cpu_times.append((time.process_time() - cpu_start) * 1000.0)
            wall_times.append((time.perf_counter() - wall_start) * 1000.0)

        cpu_times.sort()
        wall_times.sort()
        index_99 = int(iterations * 0.99)
        index_50 = int(iterations * 0.50)
        cpu_p99 = cpu_times[index_99]

        print(
            f"\nPerf: cpu p50={cpu_times[index_50]:.3f}ms cpu p99={cpu_p99:.3f}ms "
            f"cpu max={cpu_times[-1]:.3f}ms | wall p50={wall_times[index_50]:.3f}ms "
            f"wall p99={wall_times[index_99]:.3f}ms wall max={wall_times[-1]:.3f}ms"
        )
        assert cpu_p99 <= 5.0, f"CPU p99 {cpu_p99:.3f}ms exceeds 5ms budget"
