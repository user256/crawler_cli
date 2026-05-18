from __future__ import annotations

import random
import string
from dataclasses import dataclass

from .hashing import simhash64


@dataclass(slots=True)
class SoftFourOhFourFingerprint:
    tested_url: str
    final_url: str
    status: int
    body_len: int
    title: str | None
    simhash: int | None


async def soft_404_fingerprint(engine, base_url: str) -> SoftFourOhFourFingerprint:
    """Probe a deliberately bogus URL to capture the site's error-page fingerprint."""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    test_url = f"{base_url.rstrip('/')}/__crawler-cli-404-{suffix}"

    # First request with redirects disabled to see raw status
    no_redirect_config = engine.config
    no_redirect_config.follow_redirects = False
    result = await engine.crawl(test_url)

    final_url = result.final_url
    status = result.status
    body_len = len(result.raw_html or "")
    title = result.extracted.title if result.extracted else None
    sh = None
    if result.raw_html:
        sh = simhash64(result.raw_html)

    return SoftFourOhFourFingerprint(
        tested_url=test_url,
        final_url=final_url,
        status=status,
        body_len=body_len,
        title=title,
        simhash=sh,
    )
