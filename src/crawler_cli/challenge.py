"""Bot-challenge interstitial detection (ticket 074).

Identifies anti-bot challenge pages (Cloudflare, Datadome, PerimeterX/HUMAN,
Akamai, Imperva) so the engine can treat them as *blocked* rather than content,
and recover by escalating HTTP→browser through a fresh IP.

Detection is deliberately conservative — signatures that match challenge
interstitials specifically, not merely the vendor's presence on a normal page —
to avoid false-positiving real content that happens to load a vendor script.
"""

from __future__ import annotations

from typing import Literal

ChallengeKind = Literal["cloudflare", "datadome", "perimeterx", "akamai", "imperva"]


def _headers_lower(headers: dict[str, str]) -> dict[str, str]:
    return {k.lower(): (v or "") for k, v in headers.items()}


def detect_challenge(
    status: int,
    headers: dict[str, str],
    body: str | None,
) -> ChallengeKind | None:
    """Return the challenge vendor if *this response is an interstitial*, else None.

    Combines status, headers and a body-signature scan. A challenge is only
    reported when there is a strong interstitial signal — a challenge-specific
    header, or a challenge marker in the body — not just a 403 (which can be a
    legitimate forbidden) or a vendor cookie on an otherwise-real page.
    """
    h = _headers_lower(headers)
    text = body or ""
    lowered = text.lower()

    # --- Cloudflare ---
    # cf-mitigated: challenge is the definitive header signal; the interstitial
    # title/markers are the body signal. Status is typically 403 or 503.
    if h.get("cf-mitigated", "").lower() == "challenge":
        return "cloudflare"
    # Strong, Cloudflare-specific interstitial markers — sufficient on their own.
    cf_strong = (
        "just a moment...",
        "__cf_chl_",
        "cf_chl_opt",
        "challenges.cloudflare.com/turnstile",
    )
    if any(m in lowered for m in cf_strong):
        return "cloudflare"
    # Weaker marker needs corroboration (a vendor string or a challenge status).
    if "cf-challenge" in lowered and (
        "cloudflare" in lowered or status in (403, 503, 429)
    ):
        return "cloudflare"

    # --- Datadome ---
    if "datadome" in h.get("set-cookie", "").lower() and status in (403, 429):
        return "datadome"
    if "geo.captcha-delivery.com" in lowered or "dd_cookie" in lowered:
        return "datadome"

    # --- PerimeterX / HUMAN ---
    px_markers = ("px-captcha", "_px2", "perimeterx", "px.gif", "human challenge")
    if any(m in lowered for m in px_markers) and status in (403, 429):
        return "perimeterx"

    # --- Akamai Bot Manager ---
    if "_abck" in h.get("set-cookie", "").lower() and status in (403, 429):
        return "akamai"
    if "akamai" in lowered and "reference #" in lowered and status == 403:
        return "akamai"

    # --- Imperva / Incapsula ---
    if "incap_ses" in h.get("set-cookie", "").lower() and status in (403, 429):
        return "imperva"
    if "_incapsula_resource" in lowered or "incident id" in lowered and "incapsula" in lowered:
        return "imperva"

    return None
