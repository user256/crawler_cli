"""Session cookie parsing for ticket 028.

Supports two input forms:

* ``--cookie "name=value"`` CLI pairs (repeatable). Also accepts a single
  string of ``"a=1; b=2"`` semicolon-delimited pairs.
* ``--cookies-file PATH`` pointing at either a JSON array of cookie objects
  (the shape exported by browser dev-tools / Playwright ``storageState``) or a
  Netscape ``cookies.txt`` file (tab-delimited, the format ``curl -b`` and many
  browser extensions emit).

Parsed cookies are reduced to a flat ``name -> value`` map and injected as a
single ``Cookie`` request header across all backends. This is enough to bypass
login walls (the common case). It does **not** model per-path/per-domain cookie
scoping — see DECISIONS-2026-06-07.md.
"""

from __future__ import annotations

import json
from pathlib import Path


def parse_cookie_pairs(pairs: list[str]) -> dict[str, str]:
    """Parse ``name=value`` strings (each may contain ``;``-joined pairs)."""
    cookies: dict[str, str] = {}
    for raw in pairs:
        for segment in raw.split(";"):
            segment = segment.strip()
            if not segment or "=" not in segment:
                continue
            name, value = segment.split("=", 1)
            name = name.strip()
            if name:
                cookies[name] = value.strip()
    return cookies


def _parse_netscape(text: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for line in text.splitlines():
        line = line.rstrip("\n")
        if not line or line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue
        # #HttpOnly_ prefix marks an httponly cookie but is otherwise a normal row.
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        fields = line.split("\t")
        # Netscape format: domain, flag, path, secure, expiry, name, value
        if len(fields) >= 7:
            name, value = fields[5], fields[6]
            if name:
                cookies[name] = value
    return cookies


def _parse_json(text: str) -> dict[str, str]:
    data = json.loads(text)
    # Accept either a bare list of cookie objects or a storageState dict.
    if isinstance(data, dict) and "cookies" in data:
        data = data["cookies"]
    cookies: dict[str, str] = {}
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and "name" in entry and "value" in entry:
                cookies[str(entry["name"])] = str(entry["value"])
    return cookies


def load_cookies_file(path: str | Path) -> dict[str, str]:
    """Load cookies from a JSON or Netscape cookies.txt file (auto-detected)."""
    text = Path(path).read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return _parse_json(text)
    return _parse_netscape(text)


def build_cookie_header(cookies: dict[str, str]) -> str:
    """Render a cookies map into a single ``Cookie`` header value."""
    return "; ".join(f"{name}={value}" for name, value in cookies.items())
