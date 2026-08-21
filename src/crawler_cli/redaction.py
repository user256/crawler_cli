"""Central redaction and secret-hygiene machinery (ticket 153).

Every security-adjacent report in this project shares one redaction policy so
that individual detectors cannot invent their own, subtly leaking, evidence
format. The rules implemented here are deliberately conservative: it is far
better to redact a value that turns out to be harmless than to publish a
session cookie in a CSV that somebody mails to a client.

The module provides five groups of helpers:

``RedactionPolicy``
    The declarative description of which header names and query-string keys
    are considered sensitive, plus the small number of behavioural switches
    (fragment handling, e-mail handling) that a caller may legitimately want
    to change.

``CorrelationDigest``
    A keyed HMAC-SHA256 digest used whenever a report needs to correlate two
    occurrences of the same sensitive value without publishing the value. A
    plain SHA-256 of a low-entropy secret (a four digit code, an e-mail
    address, a numeric session identifier) is trivially reversible by brute
    force, so an unkeyed digest is never used for this purpose.

``SecretRegistry``
    A process-local registry of literal secret values that were loaded from
    the environment, a file, or a configuration object. Registering a secret
    lets every downstream scrubber remove it verbatim, which is the strongest
    guarantee available and is what the recursive secret-absence proofs rely
    on.

URL projection
    ``project_url`` turns a raw crawl URL into a :class:`UrlProjection`. The
    raw URL remains the crawler's internal identity and is never rewritten in
    place; the projection is a separate, additional, export-only value. This
    distinction matters because redacting a frontier key in place would merge
    two genuinely different URLs (``?token=a`` and ``?token=b``) into one
    record and would break redirect and canonical analysis.

Output hygiene
    Header, cookie, form, snippet, exception, logging and CSV helpers, all of
    which route through the same scrubbing pass.

What remains sensitive even after all of this: arbitrary crawled page content
may contain personal or confidential information that no pattern recognises.
This module performs data minimisation, not a guarantee.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import traceback
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote_plus, urlsplit, urlunsplit

REDACTED = "[REDACTED]"
"""Replacement text for any value that has been removed."""

REDACTED_EMAIL = "[REDACTED_EMAIL]"
"""Replacement text for an e-mail address found in free text."""

MIN_REGISTERED_SECRET_LENGTH = 8
"""Registered secrets shorter than this are ignored.

A short value such as ``pass`` or ``1234`` is both unprotectable — it is
guessable regardless of what this module does — and actively harmful to
register, because it occurs as a substring of ordinary text and would turn
every scrubbed string into a wall of redaction markers. Short values are
therefore refused at registration time and are covered instead by the
name-based header and query rules, which do not depend on the value at all.
"""


# --- Policy -------------------------------------------------------------------

DEFAULT_SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
        "apikey",
        "x-auth-token",
        "x-authorization",
        "x-access-token",
        "x-session-token",
        "x-csrf-token",
        "x-xsrf-token",
        "x-amz-security-token",
        "x-goog-api-key",
        "x-forwarded-authorization",
        "authentication",
        "proxy-authenticate",
    }
)
"""Header names whose values are removed by default, matched case-insensitively."""

SENSITIVE_HEADER_SUBSTRINGS: tuple[str, ...] = (
    "token",
    "secret",
    "password",
    "passwd",
    "api-key",
    "api_key",
    "apikey",
    "auth",
    "credential",
    "session",
)
"""Substrings that make an otherwise unknown header name sensitive.

Sites invent their own header names constantly (``X-Shop-Session-Token``,
``X-Acme-Api-Key``), so an exact-name list alone would leak. The substring
rule over-redacts on purpose.
"""

DEFAULT_SENSITIVE_QUERY_KEYS: frozenset[str] = frozenset(
    {
        "token",
        "key",
        "secret",
        "password",
        "passwd",
        "pwd",
        "passcode",
        "auth",
        "authorization",
        "signature",
        "sig",
        "session",
        "sessionid",
        "sid",
        "code",
        "email",
        "access_token",
        "refresh_token",
        "id_token",
        "api_key",
        "apikey",
        "csrf",
        "csrf_token",
        "xsrf",
        "otp",
        "pin",
        "state",
        "nonce",
        "credential",
        "credentials",
    }
)
"""Query-string keys whose values are removed by default.

Matching is done on a normalised form of the key (lower-cased, with ``-``,
``_`` and ``.`` removed) so ``API-Key``, ``api_key`` and ``apikey`` are all
recognised as the same key.
"""

SENSITIVE_QUERY_SUBSTRINGS: tuple[str, ...] = (
    "token",
    "secret",
    "password",
    "signature",
    "apikey",
    "session",
    "credential",
)
"""Substrings that make an otherwise unknown query key sensitive.

Short, ambiguous entries such as ``code`` or ``key`` are deliberately absent
here and matched exactly instead, so that ``postcode`` or ``keyword`` are not
redacted.
"""


def _normalise_key(name: str) -> str:
    """Return the comparison form of a header or query key."""
    return re.sub(r"[-_.\s]", "", name.strip().lower())


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    """Which names are sensitive, and how aggressive the projection is.

    The defaults are the product policy. Callers may add site-specific header
    names or query keys, but cannot remove entries from the default sets: a
    later ticket wanting to publish a value it believes is harmless should add
    an explicit detector-owned structural fact instead of widening the policy.
    """

    extra_header_names: frozenset[str] = frozenset()
    """Additional exact header names to treat as sensitive."""

    extra_query_keys: frozenset[str] = frozenset()
    """Additional exact query keys to treat as sensitive."""

    query_key_patterns: tuple[str, ...] = ()
    """Regular expressions matched (case-insensitively, fully) against the raw
    query key. Provided for sites whose keys are generated, for example
    ``sess[0-9]+``."""

    redact_fragment: bool = True
    """Replace a non-empty fragment with the redaction marker.

    Fragments are never needed for exported evidence and are a common carrier
    for OAuth implicit-flow access tokens, so they are removed by default
    while the *presence* of a fragment is preserved.
    """

    redact_emails_in_text: bool = True
    """Replace e-mail addresses found in free text and snippets."""

    def is_sensitive_header(self, name: str) -> bool:
        """Return whether the value of header *name* must be removed."""
        lowered = name.strip().lower()
        if lowered in DEFAULT_SENSITIVE_HEADERS:
            return True
        if lowered in {entry.strip().lower() for entry in self.extra_header_names}:
            return True
        return any(marker in lowered for marker in SENSITIVE_HEADER_SUBSTRINGS)

    def is_sensitive_query_key(self, key: str) -> bool:
        """Return whether the value of query parameter *key* must be removed."""
        normalised = _normalise_key(key)
        if normalised in {_normalise_key(entry) for entry in DEFAULT_SENSITIVE_QUERY_KEYS}:
            return True
        if normalised in {_normalise_key(entry) for entry in self.extra_query_keys}:
            return True
        if any(marker in normalised for marker in SENSITIVE_QUERY_SUBSTRINGS):
            return True
        return any(re.fullmatch(pattern, key, re.IGNORECASE) for pattern in self.query_key_patterns)


DEFAULT_POLICY = RedactionPolicy()
"""The policy used whenever a caller does not supply one."""


# --- Keyed correlation digests ------------------------------------------------


@dataclass(frozen=True, slots=True)
class CorrelationDigest:
    """A keyed digest used to correlate sensitive values without exposing them.

    The key is per-run by default, which means digests are comparable inside a
    single report and across the artifacts of a single run, but are not
    comparable across runs and cannot be pre-computed by somebody who obtains
    a report. That is the intended trade-off: correlation is a reporting
    convenience, whereas a cross-run rainbow table of low-entropy values would
    be a disclosure.

    Use :meth:`from_key` with a fixed key in tests and golden fixtures so the
    output is deterministic.
    """

    key: bytes = field(repr=False)
    run_id: str = ""

    @classmethod
    def for_run(cls, run_id: str = "") -> CorrelationDigest:
        """Create a digest with a freshly generated random per-run key."""
        return cls(key=secrets.token_bytes(32), run_id=run_id)

    @classmethod
    def from_key(cls, key: bytes | str, *, run_id: str = "") -> CorrelationDigest:
        """Create a digest from an explicit key, for deterministic output."""
        material = key.encode("utf-8") if isinstance(key, str) else key
        if len(material) < 16:
            raise ValueError("correlation digest key must be at least 16 bytes")
        return cls(key=material, run_id=run_id)

    def digest(self, value: str, *, domain: str = "value") -> str:
        """Return the keyed digest of *value* within a separation *domain*.

        The domain string keeps unrelated digest spaces apart, so that a URL
        digest and a cookie-name digest of the same text do not collide and
        cannot be cross-referenced by accident.
        """
        message = f"{domain}\x00{self.run_id}\x00{value}".encode()
        mac = hmac.new(self.key, message, hashlib.sha256).hexdigest()
        return f"hmac-sha256:{mac[:32]}"


# --- Registered literal secrets ------------------------------------------------


class SecretRegistry:
    """Literal secret values that must never appear in any output.

    Whenever the CLI loads a credential (a bearer token from an environment
    variable, a password from a file, a proxy password, a database DSN) it
    should register the value here. Registration is what turns the scrubbers
    from best-effort pattern matching into an exact guarantee for the values
    this process actually knows about.

    Values are stored only in memory, are never written anywhere, and are
    never exposed by this class; only the caller-supplied labels are readable
    so that an error message can name the source of a secret.
    """

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def register(self, value: str | None, *, label: str = "") -> None:
        """Register *value* (and its obvious encodings) as a literal secret."""
        if not value or len(value) < MIN_REGISTERED_SECRET_LENGTH:
            return
        candidates = [value, quote(value, safe=""), base64.b64encode(value.encode("utf-8")).decode("ascii")]
        for candidate in candidates:
            self._secrets[candidate] = label

    def register_basic_credentials(self, username: str, password: str, *, label: str = "basic-auth") -> None:
        """Register a password and the base64 form of the whole Basic pair."""
        self.register(password, label=label)
        pair = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        self.register(pair, label=label)

    def labels(self) -> tuple[str, ...]:
        """Return the labels of the registered secrets, never the values."""
        return tuple(sorted({label for label in self._secrets.values() if label}))

    def clear(self) -> None:
        """Forget every registered secret (used by tests between cases)."""
        self._secrets.clear()

    def contains_secret(self, text: str) -> bool:
        """Return whether *text* contains any registered secret verbatim."""
        return any(secret in text for secret in self._secrets)

    def scrub(self, text: str) -> str:
        """Replace every registered secret found in *text*.

        Longer secrets are replaced first so that a secret which happens to
        contain a shorter one is removed as a whole.
        """
        result = text
        for secret in sorted(self._secrets, key=len, reverse=True):
            if secret in result:
                result = result.replace(secret, REDACTED)
        return result

    def __len__(self) -> int:
        return len(self._secrets)


SECRETS = SecretRegistry()
"""Process-wide registry used by every scrubber in this module by default."""


# --- Free-text scrubbing --------------------------------------------------------

_PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z ]+ )?PRIVATE KEY-----"
)
_SET_COOKIE_LINE_RE = re.compile(r"(?i)(\bset-cookie\b\s*[:=]\s*)([^=;,\s]+)=([^;\r\n]*)")
_COOKIE_LINE_RE = re.compile(r"(?i)(?<!set-)(\bcookie\b\s*[:=]\s*)([^\r\n]+)")
_AUTH_SCHEME_RE = re.compile(r"(?i)\b(basic|bearer|token|digest|negotiate)\s+([A-Za-z0-9._~+/=-]{6,})")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}")
_URL_USERINFO_RE = re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.\-]*)://([^/\s:@]+):([^/\s@]*)@")
_AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_KEY_VALUE_RE = re.compile(
    r"(?i)\b(pass(?:word|wd|code)?|pwd|secret|token|api[_-]?key|access[_-]?key|access[_-]?token"
    r"|refresh[_-]?token|id[_-]?token|auth|authorization|signature|sig|session(?:[_-]?id)?"
    r"|csrf(?:[_-]?token)?|xsrf|otp|private[_-]?key)"
    r"(\s*[=:]\s*)"
    r"(\"?)([^\s&\"',;]{3,})"
)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
# A populated form input is one of the classic accidental disclosures: an HTML
# excerpt of a login or checkout form carries a CSRF token, a pre-filled
# password, or a hidden customer identifier. The attribute name (`value`) is
# generic, so the rule is anchored to an `<input>` tag rather than added to the
# generic key/value rule above.
_HTML_INPUT_VALUE_RE = re.compile(r"(?i)(<input\b[^>]*?\bvalue\s*=\s*)([\"']?)([^\"'>\s]+)")


def scrub_text(
    text: str,
    *,
    policy: RedactionPolicy = DEFAULT_POLICY,
    registry: SecretRegistry | None = None,
) -> str:
    """Remove credential-shaped material from an arbitrary string.

    This is the single entry point used by the log filter, the exception
    helpers, the snippet builder and the recursive structure scrubber. It is
    applied to text whose structure is unknown, so every rule is written to be
    safe when it does not match rather than clever when it does.
    """
    if not text:
        return text
    active_registry = SECRETS if registry is None else registry
    result = active_registry.scrub(text)
    result = _PEM_PRIVATE_KEY_RE.sub(f"{REDACTED}_PRIVATE_KEY", result)
    result = _SET_COOKIE_LINE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}={REDACTED}", result)
    result = _COOKIE_LINE_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", result)
    result = _URL_USERINFO_RE.sub(lambda m: f"{m.group(1)}://{REDACTED}@", result)
    result = _AUTH_SCHEME_RE.sub(lambda m: f"{m.group(1)} {REDACTED}", result)
    result = _JWT_RE.sub(REDACTED, result)
    result = _AWS_ACCESS_KEY_RE.sub(REDACTED, result)
    result = _KEY_VALUE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{REDACTED}", result)
    result = _HTML_INPUT_VALUE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", result)
    if policy.redact_emails_in_text:
        result = _EMAIL_RE.sub(REDACTED_EMAIL, result)
    return result


def scrub_structure(
    value: Any,
    *,
    policy: RedactionPolicy = DEFAULT_POLICY,
    registry: SecretRegistry | None = None,
) -> Any:
    """Recursively scrub an arbitrary JSON-shaped structure.

    Mapping keys are checked against the header and query-key policy, so a
    dictionary entry named ``authorization`` loses its value regardless of
    what that value looks like. Everything else is scrubbed as free text.
    """
    if isinstance(value, str):
        return scrub_text(value, policy=policy, registry=registry)
    if isinstance(value, Mapping):
        scrubbed: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if policy.is_sensitive_header(name) or policy.is_sensitive_query_key(name):
                scrubbed[name] = REDACTED
            else:
                scrubbed[name] = scrub_structure(item, policy=policy, registry=registry)
        return scrubbed
    if isinstance(value, (list, tuple, set)):
        return [scrub_structure(item, policy=policy, registry=registry) for item in value]
    return value


# --- Connection strings and proxies --------------------------------------------


def sanitize_url_credentials(url: str) -> str:
    """Return *url* with any userinfo component replaced.

    Used for database DSNs and proxy URLs, both of which routinely embed a
    username and password and both of which are printed in status output.
    """
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return REDACTED
    if "@" not in parts.netloc:
        return url
    host = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit((parts.scheme, f"{REDACTED}@{host}", parts.path, parts.query, parts.fragment))


def sanitize_dsn(dsn: str) -> str:
    """Return a database DSN safe to print, with credentials removed."""
    return sanitize_url_credentials(dsn)


def sanitize_proxy_url(proxy: str) -> str:
    """Return a proxy URL safe to print, with credentials removed."""
    return sanitize_url_credentials(proxy)


# --- URL projection -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UrlProjection:
    """The export-only view of a URL, alongside its untouched raw identity.

    ``raw`` is the crawler's internal identity: the frontier key, the value
    compared for canonical and redirect analysis, and the value stored in the
    ``urls`` table. It is kept on this object purely so that a caller holding
    the projection can still reach the identity it came from, and it is
    excluded from ``repr`` so that an accidental log or exception rendering of
    the projection cannot print it.

    Only :meth:`export` is safe to serialise.
    """

    raw: str = field(repr=False)
    redacted: str
    digest: str
    scheme: str
    host: str
    path: str
    had_userinfo: bool
    had_fragment: bool
    redacted_query_keys: tuple[str, ...]

    def export(self) -> dict[str, object]:
        """Return the redacted projection as a serialisable mapping."""
        return {
            "url": self.redacted,
            "url_digest": self.digest,
            "host": self.host,
            "path": self.path,
            "had_userinfo": self.had_userinfo,
            "had_fragment": self.had_fragment,
            "redacted_query_keys": list(self.redacted_query_keys),
        }


def redact_query_string(query: str, *, policy: RedactionPolicy = DEFAULT_POLICY) -> tuple[str, tuple[str, ...]]:
    """Redact the values of sensitive keys in a raw query string.

    Parameter names, their order, and their original percent-encoding are all
    preserved, because they are frequently the interesting part of a finding
    ("this page accepts a ``token`` parameter") and because re-encoding would
    make two different raw URLs look identical. Repeated keys are handled
    independently, and a bare flag with no ``=`` is left untouched.

    Returns the redacted query string and the tuple of keys that were
    redacted, in the order they appeared.
    """
    if not query:
        return "", ()
    redacted_keys: list[str] = []
    pieces: list[str] = []
    for piece in query.split("&"):
        if not piece:
            pieces.append(piece)
            continue
        raw_key, sep, _raw_value = piece.partition("=")
        if not sep:
            pieces.append(piece)
            continue
        decoded_key = unquote_plus(raw_key)
        if policy.is_sensitive_query_key(decoded_key):
            redacted_keys.append(decoded_key)
            pieces.append(f"{raw_key}={REDACTED}")
        else:
            pieces.append(piece)
    return "&".join(pieces), tuple(redacted_keys)


def project_url(
    raw_url: str,
    *,
    digest: CorrelationDigest,
    policy: RedactionPolicy = DEFAULT_POLICY,
) -> UrlProjection:
    """Build the redacted export projection of *raw_url*.

    This function never mutates anything. The caller keeps using ``raw_url``
    as the crawl identity; the returned projection is an additional value that
    exists only for reports, logs and database projections. Two URLs whose
    only difference is a redacted value produce the same ``redacted`` text but
    different ``digest`` values, so distinct records stay distinct.
    """
    try:
        parts = urlsplit(raw_url)
    except ValueError:
        return UrlProjection(
            raw=raw_url,
            redacted=REDACTED,
            digest=digest.digest(raw_url, domain="url"),
            scheme="",
            host="",
            path="",
            had_userinfo=False,
            had_fragment=False,
            redacted_query_keys=(),
        )
    had_userinfo = "@" in parts.netloc
    netloc = parts.netloc.rsplit("@", 1)[1] if had_userinfo else parts.netloc
    query, redacted_keys = redact_query_string(parts.query, policy=policy)
    had_fragment = bool(parts.fragment)
    fragment = parts.fragment
    if had_fragment and policy.redact_fragment:
        fragment = REDACTED
    redacted = urlunsplit((parts.scheme, netloc, parts.path, query, fragment))
    return UrlProjection(
        raw=raw_url,
        redacted=redacted,
        digest=digest.digest(raw_url, domain="url"),
        scheme=parts.scheme,
        host=netloc.split(":")[0].lower(),
        path=parts.path,
        had_userinfo=had_userinfo,
        had_fragment=had_fragment,
        redacted_query_keys=redacted_keys,
    )


# --- Headers and cookies ---------------------------------------------------------


def redact_header_pairs(
    pairs: Iterable[tuple[str, str]],
    *,
    policy: RedactionPolicy = DEFAULT_POLICY,
    registry: SecretRegistry | None = None,
) -> list[tuple[str, str]]:
    """Redact a list of header pairs, preserving name, order and duplicates.

    The pair form is the honest one for HTTP: a response may carry several
    ``Set-Cookie`` headers, and collapsing them into a dictionary before
    redaction would silently lose evidence about how many there were.
    """
    result: list[tuple[str, str]] = []
    for name, value in pairs:
        if policy.is_sensitive_header(name):
            result.append((name, REDACTED))
        else:
            result.append((name, scrub_text(str(value), policy=policy, registry=registry)))
    return result


def redact_headers(
    headers: Mapping[str, Any] | Iterable[tuple[str, str]],
    *,
    policy: RedactionPolicy = DEFAULT_POLICY,
    registry: SecretRegistry | None = None,
) -> dict[str, Any]:
    """Redact a header mapping, accepting single or multi-valued forms.

    Values may be plain strings or sequences of strings; the shape of each
    value is preserved so that a caller which stored a list of ``Set-Cookie``
    values still gets a list back.
    """
    if isinstance(headers, Mapping):
        items: list[tuple[str, Any]] = list(headers.items())
    else:
        items = list(headers)
    result: dict[str, Any] = {}
    for name, value in items:
        if policy.is_sensitive_header(name):
            result[name] = [REDACTED for _ in value] if isinstance(value, (list, tuple)) else REDACTED
        elif isinstance(value, (list, tuple)):
            result[name] = [scrub_text(str(item), policy=policy, registry=registry) for item in value]
        else:
            result[name] = scrub_text(str(value), policy=policy, registry=registry)
    return result


APPROVED_COOKIE_ATTRIBUTES: frozenset[str] = frozenset({"path", "domain", "samesite", "secure", "httponly", "priority"})
"""Cookie attributes a detector may retain. Never includes the cookie value."""


@dataclass(frozen=True, slots=True)
class CookieEvidence:
    """A ``Set-Cookie`` header reduced to its non-secret structural facts.

    The cookie *name* is retained because security findings are frequently
    about the name (a session cookie missing ``Secure``), while the value is
    never retained in any form other than a keyed digest, which lets a report
    say "the same cookie value was served on two hosts" without saying what it
    was.
    """

    name: str
    value_digest: str
    secure: bool
    http_only: bool
    same_site: str
    path: str
    domain: str
    has_expiry: bool
    attributes: tuple[str, ...]

    def export(self) -> dict[str, object]:
        """Return the cookie facts as a serialisable mapping."""
        return {
            "name": self.name,
            "value_digest": self.value_digest,
            "secure": self.secure,
            "http_only": self.http_only,
            "same_site": self.same_site,
            "path": self.path,
            "domain": self.domain,
            "has_expiry": self.has_expiry,
            "attributes": list(self.attributes),
        }


def parse_set_cookie_evidence(
    values: Sequence[str] | str,
    *,
    digest: CorrelationDigest,
) -> tuple[CookieEvidence, ...]:
    """Parse ``Set-Cookie`` header values into value-free cookie evidence.

    A single string or a sequence of strings is accepted, because backends
    differ in how they expose repeated headers. Each header is parsed
    independently; a header that carries no ``name=value`` pair is skipped
    rather than guessed at.
    """
    raw_values = [values] if isinstance(values, str) else list(values)
    evidence: list[CookieEvidence] = []
    for raw in raw_values:
        segments = [segment.strip() for segment in raw.split(";") if segment.strip()]
        if not segments:
            continue
        name, sep, value = segments[0].partition("=")
        if not sep:
            continue
        attributes: list[str] = []
        secure = False
        http_only = False
        same_site = ""
        path = ""
        domain = ""
        has_expiry = False
        for segment in segments[1:]:
            attr_name, attr_sep, attr_value = segment.partition("=")
            key = attr_name.strip().lower()
            if key in {"expires", "max-age"}:
                has_expiry = True
                attributes.append(key)
                continue
            if key not in APPROVED_COOKIE_ATTRIBUTES:
                # An unknown attribute is recorded by name only; its value is
                # not retained because unknown attributes are exactly where a
                # non-standard implementation might stash a token.
                attributes.append(key)
                continue
            attributes.append(key)
            if key == "secure":
                secure = True
            elif key == "httponly":
                http_only = True
            elif key == "samesite" and attr_sep:
                same_site = attr_value.strip()
            elif key == "path" and attr_sep:
                path = attr_value.strip()
            elif key == "domain" and attr_sep:
                domain = attr_value.strip()
        evidence.append(
            CookieEvidence(
                name=name.strip(),
                value_digest=digest.digest(value.strip(), domain="cookie-value"),
                secure=secure,
                http_only=http_only,
                same_site=same_site,
                path=path,
                domain=domain,
                has_expiry=has_expiry,
                attributes=tuple(attributes),
            )
        )
    return tuple(evidence)


# --- Form fields ------------------------------------------------------------------


def redact_form_fields(
    fields: Mapping[str, Any] | Iterable[tuple[str, str]],
    *,
    policy: RedactionPolicy = DEFAULT_POLICY,
) -> list[dict[str, object]]:
    """Reduce form fields to names and value metadata, never values.

    A populated password or hidden field is the classic accidental disclosure
    in a crawl artifact: a CSRF token or a pre-filled credential ends up in
    the report. The only facts retained here are the field name, whether it
    carried a value, and how long that value was.
    """
    items = list(fields.items()) if isinstance(fields, Mapping) else list(fields)
    result: list[dict[str, object]] = []
    for name, value in items:
        text = "" if value is None else str(value)
        result.append(
            {
                "name": scrub_text(str(name), policy=policy),
                "has_value": bool(text),
                "value_length": len(text),
            }
        )
    return result


# --- Bounded snippets ---------------------------------------------------------------

DEFAULT_SNIPPET_MAX_BYTES = 256
DEFAULT_SNIPPET_MAX_LINES = 3


@dataclass(frozen=True, slots=True)
class EvidenceSnippet:
    """A short, scrubbed excerpt with a hash of the material it came from.

    ``source_sha256`` is an unkeyed hash on purpose: it digests the *page
    content* the snippet was taken from, which is high entropy and not itself
    the secret, and downstream tooling needs it to be stable across runs so it
    can tell whether the underlying material changed.
    """

    text: str
    truncated: bool
    source_sha256: str
    source_bytes: int
    reason: str = ""

    def export(self) -> dict[str, object]:
        """Return the snippet as a serialisable mapping."""
        return {
            "text": self.text,
            "truncated": self.truncated,
            "source_sha256": self.source_sha256,
            "source_bytes": self.source_bytes,
            "reason": self.reason,
        }


def bounded_snippet(
    text: str,
    *,
    max_bytes: int = DEFAULT_SNIPPET_MAX_BYTES,
    max_lines: int = DEFAULT_SNIPPET_MAX_LINES,
    policy: RedactionPolicy = DEFAULT_POLICY,
    registry: SecretRegistry | None = None,
) -> EvidenceSnippet:
    """Build a whitespace-normalised, scrubbed, capped excerpt of *text*.

    When the source contains a registered secret verbatim, the excerpt falls
    back to a digest only and no text at all is retained. Pattern-based
    scrubbing would very likely have removed the secret anyway, but a value we
    positively know to be a secret is not something to gamble on.
    """
    source = text or ""
    source_bytes = len(source.encode("utf-8"))
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    active_registry = SECRETS if registry is None else registry
    if active_registry.contains_secret(source):
        return EvidenceSnippet(
            text="",
            truncated=True,
            source_sha256=source_hash,
            source_bytes=source_bytes,
            reason="registered_secret_present",
        )
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in source.splitlines()]
    lines = [line for line in lines if line]
    truncated = len(lines) > max_lines
    body = "\n".join(lines[:max_lines])
    body = scrub_text(body, policy=policy, registry=registry)
    encoded = body.encode("utf-8")
    if len(encoded) > max_bytes:
        truncated = True
        body = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return EvidenceSnippet(
        text=body,
        truncated=truncated,
        source_sha256=source_hash,
        source_bytes=source_bytes,
        reason="length_capped" if truncated else "",
    )


# --- Exceptions ---------------------------------------------------------------------


def missing_secret_message(field_name: str, source: str = "") -> str:
    """Build an error message that names the source of a secret, not its value.

    Every code path that fails to load a credential should use this so the
    resulting ``ValueError`` can be logged and printed without review.
    """
    if source:
        return f"No value for {field_name} (source: {source})"
    return f"No value for {field_name}"


def redact_exception(exc: BaseException, *, policy: RedactionPolicy = DEFAULT_POLICY) -> str:
    """Render an exception as a scrubbed ``Type: message`` string."""
    return f"{type(exc).__name__}: {scrub_text(str(exc), policy=policy)}"


def redact_traceback(exc: BaseException, *, policy: RedactionPolicy = DEFAULT_POLICY) -> str:
    """Render a full traceback with every line scrubbed.

    Tracebacks are a common leak: an exception raised inside a request helper
    prints the arguments of every frame, which can include an ``Authorization``
    header or a DSN. Any traceback that reaches an artifact, a log, or the
    terminal must be rendered through this function.
    """
    rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return scrub_text(rendered, policy=policy)


# --- Structured logging ---------------------------------------------------------------

_STANDARD_LOG_RECORD_FIELDS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()) | {"message"}


class SecretRedactingLogFilter(logging.Filter):
    """A logging filter that scrubs messages, arguments and structured extras.

    The filter rewrites the record in place and always returns ``True``: its
    job is redaction, not suppression. Attaching it to a *logger* covers
    records created by that logger; attaching it to a *handler* covers every
    record that reaches that handler, including records propagated from child
    loggers. :func:`install_log_redaction` does both.
    """

    def __init__(self, *, policy: RedactionPolicy = DEFAULT_POLICY, registry: SecretRegistry | None = None) -> None:
        super().__init__()
        self.policy = policy
        self.registry = registry

    def _scrub(self, value: Any) -> Any:
        return scrub_structure(value, policy=self.policy, registry=self.registry)

    def filter(self, record: logging.LogRecord) -> bool:
        # Structured arguments are scrubbed first, so that key-based rules
        # apply: a dictionary argument containing an ``Authorization`` entry
        # loses the value regardless of what the value looks like.
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(self._scrub(arg) for arg in record.args)
            elif isinstance(record.args, Mapping):
                record.args = self._scrub(record.args)
        # The message is then formatted once and the *result* is scrubbed. A
        # secret is very often only recognisable after interpolation: neither
        # the format string ``"fetched %s?token=%s"`` nor the bare argument
        # value looks like a credential on its own, but the formatted line
        # does. Formatting eagerly here is the price of catching that case.
        try:
            record.msg = scrub_text(record.getMessage(), policy=self.policy, registry=self.registry)
            record.args = None
        except Exception:  # pragma: no cover - malformed format strings
            record.msg = self._scrub(record.msg)
        for key, value in list(vars(record).items()):
            if key in _STANDARD_LOG_RECORD_FIELDS:
                continue
            setattr(record, key, self._scrub(value))
        if record.exc_info and record.exc_info[1] is not None:
            # Render the traceback once, scrubbed, and drop the live exception
            # so that the handler's own formatter cannot re-render the raw one.
            record.exc_text = redact_traceback(record.exc_info[1], policy=self.policy)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = scrub_text(record.exc_text, policy=self.policy, registry=self.registry)
        return True


def install_log_redaction(
    logger: logging.Logger | None = None,
    *,
    policy: RedactionPolicy = DEFAULT_POLICY,
    registry: SecretRegistry | None = None,
) -> SecretRedactingLogFilter:
    """Attach a :class:`SecretRedactingLogFilter` to a logger and its handlers.

    Passing ``None`` installs on the root logger, which is what a CLI entry
    point wants. The same filter instance is returned so a caller (typically a
    test) can attach it to a handler of its own.
    """
    target = logging.getLogger() if logger is None else logger
    log_filter = SecretRedactingLogFilter(policy=policy, registry=registry)
    target.addFilter(log_filter)
    for handler in target.handlers:
        handler.addFilter(log_filter)
    return log_filter


# --- CSV hygiene ---------------------------------------------------------------------

CSV_FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")
"""Leading characters a spreadsheet may interpret as the start of a formula."""


def csv_safe_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection in one CSV cell.

    A cell beginning with ``=``, ``+``, ``-``, ``@``, a tab or a carriage
    return is treated by Excel, LibreOffice and Google Sheets as a formula,
    which turns a crawled page title into remote code execution on the
    analyst's machine. Such cells are prefixed with an apostrophe, the
    conventional "this is text" marker, and embedded carriage returns and
    newlines are folded to spaces so a single logical row stays a single row
    in tools with a weaker CSV parser than Python's.

    Non-string values are returned unchanged: a negative *number* is not an
    injection risk, and quoting it would corrupt the data type.
    """
    if not isinstance(value, str):
        return value
    if not value:
        return value
    folded = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    # Leading whitespace is checked past, rather than trusted: a cell that
    # begins with a folded carriage return followed by "=" is still a formula
    # to a spreadsheet that trims the cell before parsing it.
    if folded.lstrip(" ").startswith(CSV_FORMULA_PREFIXES):
        return "'" + folded
    return folded


def csv_safe_row(row: Mapping[str, object]) -> dict[str, object]:
    """Apply :func:`csv_safe_cell` to every value in a CSV row mapping."""
    return {key: csv_safe_cell(value) for key, value in row.items()}
