from __future__ import annotations

import hashlib
import re
from collections import Counter

from bs4 import BeautifulSoup


def normalize_html_for_hashing(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Remove common dynamic attributes so hashes stay stable across runs.
    for node in soup.find_all(True):
        for attr in list(node.attrs):
            if attr.lower().startswith(("data-", "nonce")):
                del node.attrs[attr]

    return " ".join(soup.get_text(" ", strip=True).split())


def sha256_hash(html: str) -> str:
    normalized = normalize_html_for_hashing(html)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def simhash64(html: str) -> int:
    normalized = normalize_html_for_hashing(html).lower()
    tokens = re.findall(r"\w+", normalized)
    if not tokens:
        return 0
    counts = Counter(tokens)
    vector = [0] * 64
    for token, weight in counts.items():
        digest = hashlib.md5(token.encode("utf-8")).digest()[:8]
        bits = int.from_bytes(digest, byteorder="big", signed=False)
        for i in range(64):
            vector[i] += weight if (bits >> i) & 1 else -weight

    fingerprint = 0
    for i, score in enumerate(vector):
        if score >= 0:
            fingerprint |= 1 << i
    return fingerprint

