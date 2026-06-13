"""Session cookie parsing for tickets 028 and 048.

Supports two input forms:

* ``--cookie "name=value"`` CLI pairs (repeatable). Also accepts a single
  string of ``"a=1; b=2"`` semicolon-delimited pairs.
* ``--cookies-file PATH`` pointing at either a JSON array of cookie objects
  (the shape exported by browser dev-tools / Playwright ``storageState``) or a
  Netscape ``cookies.txt`` file (tab-delimited, the format ``curl -b`` and many
  browser extensions emit).

Two views are produced:

* The legacy flat ``name -> value`` map (``parse_cookie_pairs`` /
  ``load_cookies_file``), injected as one ``Cookie`` header on every request.
  Fine for single-host login walls.
* Scoped ``Cookie`` objects (``load_scoped_cookies_file`` /
  ``scoped_cookies_from_pairs``) that retain ``domain`` / ``path`` / ``secure``
  / ``httponly``, so a multi-host crawl only sends each cookie to URLs it
  matches (ticket 048). Standard domain/path matching is applied via
  ``cookies_for_url`` + ``build_scoped_cookie_header``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(slots=True)
class Cookie:
    """A cookie retaining the attributes needed for domain/path scoping."""

    name: str
    value: str
    domain: str = ""
    path: str = "/"
    secure: bool = False
    httponly: bool = False

    def matches(self, url: str) -> bool:
        """Return True when this cookie should be sent to *url*.

        Implements the standard matching rules: secure-only cookies require
        https; a leading-dot (or attribute) domain matches the host and its
        subdomains; a host-only cookie (no domain) matches only the exact
        host it was set on. Path-match per RFC 6265 §5.1.4.
        """
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        scheme = parsed.scheme.lower()
        req_path = parsed.path or "/"

        if self.secure and scheme != "https":
            return False
        if not _domain_match(host, self.domain):
            return False
        return _path_match(req_path, self.path or "/")


def _domain_match(host: str, cookie_domain: str) -> bool:
    """RFC 6265-ish domain match.

    Empty cookie_domain → host-only cookie; we treat it as matching any host
    (the CLI ``--cookie name=value`` form has no domain and the caller scopes
    by other means). A non-empty domain matches the host exactly or as a
    parent domain (``.example.com`` and ``example.com`` both match
    ``www.example.com``).
    """
    if not cookie_domain:
        return True
    cookie_domain = cookie_domain.lstrip(".").lower()
    if not host:
        return False
    if host == cookie_domain:
        return True
    return host.endswith("." + cookie_domain)


def _path_match(request_path: str, cookie_path: str) -> bool:
    """RFC 6265 §5.1.4 path-match."""
    if not cookie_path.startswith("/"):
        cookie_path = "/" + cookie_path
    if request_path == cookie_path:
        return True
    if request_path.startswith(cookie_path):
        # Either the cookie-path ends in '/', or the next char in the request
        # path is '/'. Prevents '/foo' matching '/foobar'.
        return cookie_path.endswith("/") or request_path[len(cookie_path):].startswith("/")
    return False


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


def scoped_cookies_from_pairs(pairs: list[str]) -> list[Cookie]:
    """``--cookie name=value`` pairs as host-only, path ``/`` cookies.

    No domain is recorded, so these are sent to every host (matching the
    legacy flat-map behaviour). Use a cookies-file for per-domain scoping.
    """
    return [Cookie(name=n, value=v) for n, v in parse_cookie_pairs(pairs).items()]


def _parse_netscape(text: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for cookie in _parse_netscape_scoped(text):
        cookies[cookie.name] = cookie.value
    return cookies


def _parse_netscape_scoped(text: str) -> list[Cookie]:
    cookies: list[Cookie] = []
    for line in text.splitlines():
        line = line.rstrip("\n")
        httponly = False
        if not line or line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue
        # #HttpOnly_ prefix marks an httponly cookie but is otherwise a normal row.
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
            httponly = True
        fields = line.split("\t")
        # Netscape format: domain, flag, path, secure, expiry, name, value
        if len(fields) >= 7:
            domain, _flag, path, secure, _expiry, name, value = fields[:7]
            if name:
                cookies.append(
                    Cookie(
                        name=name,
                        value=value,
                        domain=domain,
                        path=path or "/",
                        secure=secure.strip().upper() == "TRUE",
                        httponly=httponly,
                    )
                )
    return cookies


def _json_entries(text: str) -> list[dict]:
    data = json.loads(text)
    # Accept either a bare list of cookie objects or a storageState dict.
    if isinstance(data, dict) and "cookies" in data:
        data = data["cookies"]
    if isinstance(data, list):
        return [entry for entry in data if isinstance(entry, dict)]
    return []


def _parse_json(text: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for entry in _json_entries(text):
        if "name" in entry and "value" in entry:
            cookies[str(entry["name"])] = str(entry["value"])
    return cookies


def _parse_json_scoped(text: str) -> list[Cookie]:
    cookies: list[Cookie] = []
    for entry in _json_entries(text):
        if "name" not in entry or "value" not in entry:
            continue
        cookies.append(
            Cookie(
                name=str(entry["name"]),
                value=str(entry["value"]),
                domain=str(entry.get("domain", "")),
                path=str(entry.get("path", "/")) or "/",
                secure=bool(entry.get("secure", False)),
                httponly=bool(entry.get("httpOnly", entry.get("httponly", False))),
            )
        )
    return cookies


def load_cookies_file(path: str | Path) -> dict[str, str]:
    """Load cookies from a JSON or Netscape cookies.txt file (auto-detected)."""
    text = Path(path).read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return _parse_json(text)
    return _parse_netscape(text)


def load_scoped_cookies_file(path: str | Path) -> list[Cookie]:
    """Load cookies with domain/path attributes retained (ticket 048)."""
    text = Path(path).read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return _parse_json_scoped(text)
    return _parse_netscape_scoped(text)


def cookies_for_url(cookies: list[Cookie], url: str) -> list[Cookie]:
    """Select the cookies whose domain/path/secure attributes match *url*."""
    return [cookie for cookie in cookies if cookie.matches(url)]


def build_cookie_header(cookies: dict[str, str]) -> str:
    """Render a cookies map into a single ``Cookie`` header value."""
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def build_scoped_cookie_header(cookies: list[Cookie], url: str) -> str:
    """Render the ``Cookie`` header for *url* from scoped cookies."""
    return "; ".join(f"{c.name}={c.value}" for c in cookies_for_url(cookies, url))
