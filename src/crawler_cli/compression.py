from __future__ import annotations

import gzip

# Single-byte format tag prepended to gzip payloads (legacy rows have no tag).
FORMAT_GZIP = b"\x01"


def compress_html(text: str) -> bytes:
    """Return gzip-compressed HTML with a format prefix."""
    payload = text.encode("utf-8")
    compressed = gzip.compress(payload, compresslevel=6)
    return FORMAT_GZIP + compressed


def is_compressed(data: bytes) -> bool:
    return bool(data) and data[0:1] == FORMAT_GZIP


def decompress_html(data: bytes) -> str:
    """Decompress stored HTML; accept legacy raw UTF-8 blobs without a format tag."""
    if not data:
        return ""
    if is_compressed(data):
        return gzip.decompress(data[1:]).decode("utf-8")
    return data.decode("utf-8")
