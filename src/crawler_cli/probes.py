from __future__ import annotations

import hashlib
import re
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
    headers: dict[str, str]
    redirect_chain: list[dict[str, object]]
    canonical: str | None
    noindex_by_saved_directives: bool | None
    elapsed_seconds: float | None
    error_phrase_in_body: bool


async def soft_404_fingerprint(engine, base_url: str) -> SoftFourOhFourFingerprint:
    """Probe a deliberately bogus URL to capture the site's error-page fingerprint.

    The probe needs the raw status, so it must not follow redirects. It restores
    the caller's setting afterwards: this used to assign ``engine.config`` to a
    local name and set ``follow_redirects = False`` on it, which is the same
    object, so a single probe silently disabled redirect following for the rest
    of the crawl (ticket 146).

    One request, one invented path. Callers that need a different probe URL
    should pass their own base; this never retries with further paths.
    """
    # A stable invalid route makes evidence replayable and avoids consuming a
    # different crawl path every time the same run is audited.
    suffix = hashlib.sha256(base_url.encode("utf-8")).hexdigest()[:12]
    test_url = f"{base_url.rstrip('/')}/__crawler-cli-404-{suffix}"

    config = engine.config
    previous_follow_redirects = config.follow_redirects
    config.follow_redirects = False
    try:
        result = await engine.crawl(test_url)
    finally:
        config.follow_redirects = previous_follow_redirects

    final_url = result.final_url
    status = result.status
    body_len = result.decoded_bytes or len((result.raw_html or "").encode("utf-8"))
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
        headers=dict(result.headers),
        redirect_chain=list(result.redirect_chain),
        canonical=result.extracted.canonical if result.extracted else None,
        noindex_by_saved_directives=(
            result.extracted.meta_robots.noindex or result.extracted.x_robots_tag.noindex
            if result.extracted
            else None
        ),
        elapsed_seconds=result.total_duration_seconds,
        error_phrase_in_body=bool(
            result.raw_html and re.search(r"\b(page not found|not found|404|does not exist|no longer available)\b", result.raw_html, re.I)
        ),
    )
