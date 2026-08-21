"""Operator authorisation and run-scope manifest (ticket 148).

This module owns the single, portable description of what a security-adjacent
run is permitted to touch: which exact origins, which normalized path prefixes,
which HTTP methods, and during which UTC time window. It also records the
operator's own attestation that the work is authorised.

The manifest is **evidence of operator attestation only**. It is not proof of
legal permission, it does not verify ownership of the target, and it is not a
substitute for whatever approval process the operator's organisation requires.
Every surface that surfaces manifest data — CLI output, ``--help`` text, saved
artifacts — repeats that statement so a reader never mistakes the record for a
warrant.

Design notes that follow directly from the ticket and its review:

* Version 1 uses **exact origins**. A parent domain never implicitly authorises
  a subdomain and wildcards do not exist in this schema version.
* The validity window is **mandatory** and is checked while the manifest is
  loaded, which happens before any backend is constructed and therefore before
  any DNS or HTTP activity.
* Exactly one predicate is compiled per run. Callers must route every URL class
  — seeds, discovered anchors, hreflang targets, sitemap documents, sitemap
  locs, robots.txt, redirect hops, probes — through :meth:`ScopePredicate.decide`
  rather than re-deriving their own scope logic.
* Existing command-line scope flags may narrow the manifest, never widen it.
  :func:`assert_cli_narrows_scope` fails closed on a contradiction at startup.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping
from urllib.parse import unquote, urlparse

SCOPE_MANIFEST_SCHEMA_VERSION = "crawler-cli/scope-manifest/1"
"""Schema identifier that a version 1 manifest document must declare."""

SCOPE_SNAPSHOT_SCHEMA_VERSION = "crawler-cli/scope-snapshot/1"
"""Schema identifier stamped on the canonical, secret-free scope snapshot.

The snapshot is the portable projection of a manifest that is written into run
metadata and saved artifacts. It is versioned separately from the manifest
document because the two evolve for different reasons: the document is an
operator-authored input, the snapshot is a machine-generated record.
"""

ATTESTATION_NOTICE = (
    "This scope manifest records the operator's own attestation of authorisation. "
    "It is not proof of legal permission and does not replace organisational approval."
)
"""One-line non-proof statement repeated in CLI output, help text, and artifacts."""

SUPPORTED_METHODS = ("GET", "HEAD")
"""HTTP methods the crawler actually implements.

Listing anything else in a manifest is rejected rather than quietly ignored: a
manifest that appears to authorise ``POST`` would misrepresent what the tool can
do, and a future reader might take the manifest as evidence that a write request
was permitted and attempted.
"""

SECURITY_ADJACENT_COMMANDS: frozenset[str] = frozenset()
"""Commands that must refuse to run without a valid scope manifest.

The set is deliberately empty today. Tickets 145-146, 150-152, and 154 add the
security-adjacent commands; each of those tickets adds its own command name
here rather than inventing a private ``--authorised`` flag. Ordinary
technical-SEO crawling stays manifest-optional and is never listed.
"""

ScopePurpose = Literal["seed", "discovered", "sitemap", "robots", "redirect", "probe"]
"""URL classes that pass through the compiled predicate.

``seed`` covers operator-supplied inputs, ``discovered`` covers anchors,
hreflang targets, sitemap locs, and archive-derived candidates, ``sitemap``
covers sitemap documents and sitemap indexes, ``robots`` covers a well-known
``/robots.txt`` resolution, ``redirect`` covers every hop of a redirect chain,
and ``probe`` covers generated URLs such as soft-404 or comparison probes.
"""

_RFC3339_UTC = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt](?P<time>\d{2}:\d{2}:\d{2})(?P<frac>\.\d+)?([Zz]|\+00:00)$")
"""Accepted timestamp shape: an RFC 3339 date-time that is explicitly UTC.

Offsets other than UTC are rejected on purpose. A manifest is read by people
auditing a run after the fact and a local-offset window invites arithmetic
mistakes at exactly the moment when correctness matters most.
"""

_REQUIRED_FIELDS = (
    "schema_version",
    "authorization_reference",
    "operator",
    "valid_from",
    "valid_until",
    "allowed_origins",
    "allowed_path_prefixes",
)

_OPTIONAL_FIELDS = (
    "excluded_path_prefixes",
    "allowed_methods",
    "allow_private_network",
    "allow_ignore_robots",
    "notes",
)


class ScopeManifestError(ValueError):
    """Raised when a manifest document cannot be loaded or is not valid.

    Every path that raises this exception does so before a backend exists, so a
    caller can rely on the failure having produced no network activity.
    """


class ScopeManifestDenied(RuntimeError):
    """Raised when a URL is refused by the compiled scope predicate.

    This is deliberately a distinct exception type rather than an HTTP failure:
    no request was made, so recording it as a fetch error or as a status code
    would misdescribe what happened. Call sites translate it into the
    ``scope_manifest_denied:<reason>`` skip reason.
    """

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"scope manifest denied {url!r}: {reason}")
        self.url = url
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ScopeDecision:
    """The outcome of one scope check.

    ``reason`` is a small closed vocabulary — ``origin``, ``path``, ``method``,
    ``time_window``, ``scheme``, ``userinfo``, ``malformed_url`` — so that
    downstream reporting can distinguish scope refusals from transport failures
    without parsing free text.
    """

    allowed: bool
    reason: str | None = None
    normalized_url: str | None = None

    @property
    def skip_reason(self) -> str | None:
        """Return the engine-facing skip reason, or None when the URL is allowed."""
        if self.allowed:
            return None
        return f"scope_manifest_denied:{self.reason}"


@dataclass(frozen=True, slots=True)
class ScopeCapabilities:
    """Public statement of what a run's guards actually cover (ticket 148 task 6).

    A caller inspecting a run should be able to tell the difference between
    "the operator declared an intent scope", "individual connections are pinned
    by a Portal policy", and "browser navigation is entirely unguarded" without
    inferring any of it from flag names.
    """

    intent_scope: bool
    connection_pinning: bool
    unguarded_browser_paths: bool
    scope_manifest_digest: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "intent_scope": self.intent_scope,
            "connection_pinning": self.connection_pinning,
            "unguarded_browser_paths": self.unguarded_browser_paths,
            "scope_manifest_digest": self.scope_manifest_digest,
            "attestation_notice": ATTESTATION_NOTICE,
        }


@dataclass(frozen=True, slots=True)
class ScopeManifest:
    """A validated, normalized version 1 authorisation and scope manifest."""

    authorization_reference: str
    operator: str
    valid_from: datetime
    valid_until: datetime
    allowed_origins: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    excluded_path_prefixes: tuple[str, ...] = ()
    allowed_methods: tuple[str, ...] = ("GET", "HEAD")
    allow_private_network: bool = False
    allow_ignore_robots: bool = False
    notes: str = ""
    schema_version: str = SCOPE_MANIFEST_SCHEMA_VERSION

    def snapshot(self) -> dict[str, Any]:
        """Return the canonical, secret-free scope snapshot.

        ``notes`` is intentionally excluded. It is free-form operator prose, it
        has no bearing on any scope decision, and copying it into portable
        artifacts is the most likely way for a customer name or an internal
        ticket summary to escape into a downstream system. The snapshot is also
        free of the manifest's filesystem path for the same reason.
        """
        return {
            "schema_version": SCOPE_SNAPSHOT_SCHEMA_VERSION,
            "manifest_schema_version": self.schema_version,
            "authorization_reference": self.authorization_reference,
            "operator": self.operator,
            "valid_from": _format_timestamp(self.valid_from),
            "valid_until": _format_timestamp(self.valid_until),
            "allowed_origins": list(self.allowed_origins),
            "allowed_path_prefixes": list(self.allowed_path_prefixes),
            "excluded_path_prefixes": list(self.excluded_path_prefixes),
            "allowed_methods": list(self.allowed_methods),
            "allow_private_network": self.allow_private_network,
            "allow_ignore_robots": self.allow_ignore_robots,
            "attestation_notice": ATTESTATION_NOTICE,
        }

    @property
    def digest(self) -> str:
        """Return the SHA-256 digest of the canonical scope snapshot.

        The digest covers only the material scope, so re-wording ``notes`` does
        not invalidate a resumable run while adding an origin or moving the
        validity window does.
        """
        payload = json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _format_timestamp(value: datetime) -> str:
    """Render a UTC datetime back into the canonical RFC 3339 form."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(raw: object, *, field: str) -> datetime:
    if not isinstance(raw, str) or not _RFC3339_UTC.match(raw.strip()):
        raise ScopeManifestError(f"{field} must be a UTC RFC 3339 timestamp such as 2026-08-21T09:00:00Z, got {raw!r}")
    text = raw.strip()
    normalized = text[:-1] + "+00:00" if text[-1] in "Zz" else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:  # pragma: no cover - the regex already constrains the shape
        raise ScopeManifestError(f"{field} is not a valid timestamp: {raw!r}") from exc
    return parsed.astimezone(timezone.utc)


def normalize_origin(raw: object, *, field: str = "allowed_origins") -> str:
    """Return the canonical ``scheme://host:port`` form of one origin entry.

    Hostnames are IDNA-encoded, lower-cased, and stripped of a trailing dot so
    that ``https://WWW.Example.COM.``, ``https://www.example.com``, and an
    internationalised spelling of the same host cannot disagree about whether
    they are in scope. The port is always made explicit, which removes the
    default-port ambiguity between ``https://host`` and ``https://host:443``.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ScopeManifestError(f"{field} entries must be non-empty strings, got {raw!r}")
    text = raw.strip()
    if "*" in text:
        raise ScopeManifestError(
            f"{field} does not support wildcards in {SCOPE_MANIFEST_SCHEMA_VERSION}; "
            f"declare each exact origin instead, got {text!r}"
        )
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise ScopeManifestError(f"{field} entries must use http or https, got {text!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ScopeManifestError(f"{field} entries must not carry userinfo, got {text!r}")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.params:
        raise ScopeManifestError(f"{field} entries are origins, not URLs; drop the path/query/fragment from {text!r}")
    host = _normalize_hostname(parsed.hostname, field=field, source=text)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ScopeManifestError(f"{field} entry has an invalid port: {text!r}") from exc
    effective_port = port or (443 if parsed.scheme == "https" else 80)
    return f"{parsed.scheme}://{host}:{effective_port}"


def _normalize_hostname(hostname: str | None, *, field: str, source: str) -> str:
    """IDNA-normalise a hostname, lower-case it, and strip a trailing dot."""
    if not hostname:
        raise ScopeManifestError(f"{field} entry has no hostname: {source!r}")
    host = hostname.strip().rstrip(".").lower()
    if not host:
        raise ScopeManifestError(f"{field} entry has no hostname: {source!r}")
    try:
        # ``encode("idna")`` rejects empty labels and over-long labels, which is
        # exactly the validation we want; ASCII hosts round-trip unchanged.
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ScopeManifestError(f"{field} entry has an invalid hostname: {source!r}") from exc
    return host


def normalize_path_prefix(raw: object, *, field: str) -> str:
    """Return a canonical, leading-slash path prefix with no trailing slash.

    ``/`` is preserved as the root prefix. Everything else loses its trailing
    slash so that prefix comparison can apply an explicit segment boundary and
    ``/shop`` cannot silently authorise ``/shopping``.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ScopeManifestError(f"{field} entries must be non-empty strings, got {raw!r}")
    text = raw.strip()
    if "*" in text:
        raise ScopeManifestError(f"{field} does not support wildcards, got {text!r}")
    if not text.startswith("/"):
        raise ScopeManifestError(f"{field} entries must start with '/', got {text!r}")
    normalized = _normalize_path(text)
    if normalized != "/":
        normalized = normalized.rstrip("/") or "/"
    return normalized


def _normalize_path(path: str) -> str:
    """Collapse dot segments and duplicate slashes in a URL path."""
    if not path:
        return "/"
    segments: list[str] = []
    for segment in path.split("/"):
        if segment in {"", "."}:
            continue
        if segment == "..":
            if segments:
                segments.pop()
            continue
        segments.append(segment)
    collapsed = "/" + "/".join(segments)
    if len(path) > 1 and path.endswith("/") and collapsed != "/":
        collapsed += "/"
    return collapsed


def _path_forms(path: str) -> tuple[str, str]:
    """Return the raw-normalized and percent-decoded-normalized path forms.

    Both forms are checked. A URL is admitted only when both are inside the
    allowed prefixes, and it is excluded when either is inside an excluded
    prefix. Percent-encoding is a common way to make one path look like another,
    and evaluating both forms means an encoded spelling can only ever be more
    restrictive, never less.
    """
    raw = _normalize_path(path or "/")
    decoded = _normalize_path(unquote(path or "/"))
    return raw, decoded


def _prefix_matches(path: str, prefix: str) -> bool:
    """Return True when *path* is at or below *prefix* on a segment boundary."""
    if prefix == "/":
        return True
    candidate = path.rstrip("/") or "/"
    return candidate == prefix or candidate.startswith(prefix + "/")


def parse_scope_manifest(document: Mapping[str, Any], *, source: str = "<document>") -> ScopeManifest:
    """Validate and normalize a manifest mapping into a :class:`ScopeManifest`.

    The parse is strict: unknown keys, a missing validity window, a wildcard
    origin, a method the crawler does not implement, or an unknown schema
    version all raise :class:`ScopeManifestError`. Nothing here touches the
    network, so a caller that loads a manifest first can guarantee that an
    invalid manifest produced zero requests.
    """
    if not isinstance(document, Mapping):
        raise ScopeManifestError(f"{source}: scope manifest must be a JSON object")

    known = set(_REQUIRED_FIELDS) | set(_OPTIONAL_FIELDS)
    unknown = sorted(set(document) - known)
    if unknown:
        raise ScopeManifestError(f"{source}: unknown scope manifest field(s): {', '.join(unknown)}")

    schema_version = document.get("schema_version")
    if schema_version != SCOPE_MANIFEST_SCHEMA_VERSION:
        raise ScopeManifestError(
            f"{source}: unsupported scope manifest schema_version {schema_version!r}; "
            f"this build understands {SCOPE_MANIFEST_SCHEMA_VERSION}"
        )

    missing = [name for name in _REQUIRED_FIELDS if name not in document]
    if missing:
        raise ScopeManifestError(f"{source}: scope manifest is missing required field(s): {', '.join(missing)}")

    reference = _require_identifier(document.get("authorization_reference"), field="authorization_reference")
    operator = _require_identifier(document.get("operator"), field="operator")

    valid_from = _parse_timestamp(document.get("valid_from"), field="valid_from")
    valid_until = _parse_timestamp(document.get("valid_until"), field="valid_until")
    if valid_until <= valid_from:
        raise ScopeManifestError(
            f"{source}: valid_until must be after valid_from "
            f"({_format_timestamp(valid_until)} <= {_format_timestamp(valid_from)})"
        )

    origins = _require_string_list(document.get("allowed_origins"), field="allowed_origins", allow_empty=False)
    normalized_origins = tuple(dict.fromkeys(normalize_origin(entry) for entry in origins))

    allowed_paths = _require_string_list(
        document.get("allowed_path_prefixes"), field="allowed_path_prefixes", allow_empty=False
    )
    normalized_allowed = tuple(
        dict.fromkeys(normalize_path_prefix(entry, field="allowed_path_prefixes") for entry in allowed_paths)
    )

    excluded_paths = _require_string_list(
        document.get("excluded_path_prefixes", []), field="excluded_path_prefixes", allow_empty=True
    )
    normalized_excluded = tuple(
        dict.fromkeys(normalize_path_prefix(entry, field="excluded_path_prefixes") for entry in excluded_paths)
    )

    methods_raw = document.get("allowed_methods", list(SUPPORTED_METHODS))
    methods = _require_string_list(methods_raw, field="allowed_methods", allow_empty=False)
    normalized_methods: list[str] = []
    for method in methods:
        upper = method.strip().upper()
        if upper not in SUPPORTED_METHODS:
            raise ScopeManifestError(
                f"{source}: allowed_methods may list only methods this crawler implements "
                f"({', '.join(SUPPORTED_METHODS)}); {method!r} is not one of them"
            )
        if upper not in normalized_methods:
            normalized_methods.append(upper)

    allow_private_network = _require_bool(document.get("allow_private_network", False), field="allow_private_network")
    allow_ignore_robots = _require_bool(document.get("allow_ignore_robots", False), field="allow_ignore_robots")

    notes = document.get("notes", "")
    if not isinstance(notes, str):
        raise ScopeManifestError(f"{source}: notes must be a string when present")

    return ScopeManifest(
        authorization_reference=reference,
        operator=operator,
        valid_from=valid_from,
        valid_until=valid_until,
        allowed_origins=normalized_origins,
        allowed_path_prefixes=normalized_allowed,
        excluded_path_prefixes=normalized_excluded,
        allowed_methods=tuple(normalized_methods),
        allow_private_network=allow_private_network,
        allow_ignore_robots=allow_ignore_robots,
        notes=notes,
        schema_version=SCOPE_MANIFEST_SCHEMA_VERSION,
    )


def _require_identifier(value: object, *, field: str) -> str:
    """Validate an opaque, non-secret identifier such as a change reference."""
    if not isinstance(value, str) or not value.strip():
        raise ScopeManifestError(f"{field} must be a non-empty string")
    text = value.strip()
    if len(text) > 200:
        raise ScopeManifestError(f"{field} must be a short opaque identifier, not a document (max 200 characters)")
    if "\n" in text or "\r" in text:
        raise ScopeManifestError(f"{field} must be a single line")
    return text


def _require_string_list(value: object, *, field: str, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(entry, str) for entry in value):
        raise ScopeManifestError(f"{field} must be a list of strings")
    if not value and not allow_empty:
        raise ScopeManifestError(f"{field} must list at least one entry")
    return [str(entry) for entry in value]


def _require_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ScopeManifestError(f"{field} must be true or false")
    return bool(value)


def load_scope_manifest(path: str | Path, *, now: datetime | None = None) -> ScopeManifest:
    """Read, parse, and time-validate a manifest file.

    The validity window is enforced here rather than at first use so that an
    expired or not-yet-valid manifest stops the run at preflight, before a
    backend is constructed and therefore before any DNS or HTTP activity.
    """
    manifest_path = Path(path).expanduser()
    try:
        raw_text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScopeManifestError(f"Unable to read scope manifest {manifest_path}: {exc.strerror or exc}") from exc
    try:
        document = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ScopeManifestError(f"Scope manifest {manifest_path} is not valid JSON: {exc}") from exc
    manifest = parse_scope_manifest(document, source=str(manifest_path))
    assert_within_validity_window(manifest, now=now)
    return manifest


def assert_within_validity_window(manifest: ScopeManifest, *, now: datetime | None = None) -> None:
    """Raise :class:`ScopeManifestError` when the manifest is not currently valid."""
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if moment < manifest.valid_from:
        raise ScopeManifestError(
            f"Scope manifest {manifest.authorization_reference} is not valid until "
            f"{_format_timestamp(manifest.valid_from)}; refusing to start"
        )
    if moment >= manifest.valid_until:
        raise ScopeManifestError(
            f"Scope manifest {manifest.authorization_reference} expired at "
            f"{_format_timestamp(manifest.valid_until)}; refusing to start"
        )


class ScopePredicate:
    """The single compiled scope decision for one run.

    Compile this once, attach it to the run configuration, and call
    :meth:`decide` at the shared URL admission boundary and at the redirect
    boundary. Nothing else in the codebase should re-implement origin or path
    scope logic for an active manifest: a second implementation is a second
    place for the two answers to drift apart.
    """

    __slots__ = ("_manifest", "_origins", "_digest", "_snapshot")

    def __init__(self, manifest: ScopeManifest) -> None:
        self._manifest = manifest
        # Normalization happened during parsing, so the origin set is already
        # canonical; freeze it here so a decision is a set membership test.
        self._origins = frozenset(manifest.allowed_origins)
        self._snapshot = manifest.snapshot()
        self._digest = manifest.digest

    @property
    def manifest(self) -> ScopeManifest:
        return self._manifest

    @property
    def digest(self) -> str:
        """SHA-256 digest of the canonical scope snapshot."""
        return self._digest

    def snapshot(self) -> dict[str, Any]:
        """Return a copy of the canonical, secret-free scope snapshot."""
        return dict(self._snapshot)

    def decide(
        self,
        url: str,
        *,
        purpose: ScopePurpose = "discovered",
        method: str = "GET",
        now: datetime | None = None,
    ) -> ScopeDecision:
        """Return the scope decision for one URL.

        The checks run in a fixed order — time window, method, URL shape,
        origin, then path — so that the recorded reason names the first and
        most fundamental thing that was wrong.

        A ``robots`` purpose is the one place where the path policy is relaxed,
        and only for the exact well-known ``/robots.txt`` document. A manifest
        that authorises a subtree of an origin still authorises reading that
        origin's robots policy, because refusing to read it would leave the
        crawler unable to honour the site's own rules.
        """
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if moment < self._manifest.valid_from or moment >= self._manifest.valid_until:
            return ScopeDecision(False, "time_window")

        if method.strip().upper() not in self._manifest.allowed_methods:
            return ScopeDecision(False, "method")

        parsed = urlparse(url or "")
        if parsed.scheme not in {"http", "https"}:
            return ScopeDecision(False, "scheme" if parsed.scheme else "malformed_url")
        if parsed.username is not None or parsed.password is not None:
            return ScopeDecision(False, "userinfo")
        try:
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            return ScopeDecision(False, "malformed_url")
        if not hostname:
            return ScopeDecision(False, "malformed_url")
        try:
            host = _normalize_hostname(hostname, field="url", source=url)
        except ScopeManifestError:
            return ScopeDecision(False, "malformed_url")
        effective_port = port or (443 if parsed.scheme == "https" else 80)
        origin = f"{parsed.scheme}://{host}:{effective_port}"
        if origin not in self._origins:
            return ScopeDecision(False, "origin", normalized_url=origin)

        raw_path, decoded_path = _path_forms(parsed.path)
        if purpose == "robots" and raw_path == "/robots.txt" and decoded_path == "/robots.txt":
            return ScopeDecision(True, None, normalized_url=f"{origin}{raw_path}")

        for excluded in self._manifest.excluded_path_prefixes:
            if _prefix_matches(raw_path, excluded) or _prefix_matches(decoded_path, excluded):
                return ScopeDecision(False, "path", normalized_url=f"{origin}{raw_path}")
        allowed = all(
            any(_prefix_matches(candidate, prefix) for prefix in self._manifest.allowed_path_prefixes)
            for candidate in (raw_path, decoded_path)
        )
        if not allowed:
            return ScopeDecision(False, "path", normalized_url=f"{origin}{raw_path}")
        return ScopeDecision(True, None, normalized_url=f"{origin}{raw_path}")

    def is_allowed(self, url: str, *, purpose: ScopePurpose = "discovered", method: str = "GET") -> bool:
        """Convenience wrapper around :meth:`decide` for boolean call sites."""
        return self.decide(url, purpose=purpose, method=method).allowed

    def require(self, url: str, *, purpose: ScopePurpose = "discovered", method: str = "GET") -> None:
        """Raise :class:`ScopeManifestDenied` when *url* is outside the manifest."""
        decision = self.decide(url, purpose=purpose, method=method)
        if not decision.allowed:
            raise ScopeManifestDenied(url, decision.reason or "unknown")

    def partition(
        self, urls: Iterable[str], *, purpose: ScopePurpose = "seed"
    ) -> tuple[list[str], list[tuple[str, str]]]:
        """Split *urls* into in-scope entries and ``(url, reason)`` rejections."""
        accepted: list[str] = []
        rejected: list[tuple[str, str]] = []
        for url in urls:
            decision = self.decide(url, purpose=purpose)
            if decision.allowed:
                accepted.append(url)
            else:
                rejected.append((url, decision.reason or "unknown"))
        return accepted, rejected


def compile_scope_predicate(manifest: ScopeManifest | None) -> ScopePredicate | None:
    """Compile the one predicate for a run, or None when no manifest is active."""
    if manifest is None:
        return None
    return ScopePredicate(manifest)


def assert_inputs_in_scope(
    predicate: ScopePredicate | None,
    urls: Iterable[str],
    *,
    label: str = "seed",
) -> None:
    """Fail the whole input set when any operator-supplied URL is out of scope.

    A partially-valid input set is rejected as a whole rather than silently
    reduced to its valid members. Silently dropping entries would let a run
    report success while quietly not covering what the operator asked for, and
    the operator would have no signal that the manifest and the request had
    disagreed.
    """
    if predicate is None:
        return
    accepted, rejected = predicate.partition(urls, purpose="seed")
    del accepted
    if rejected:
        detail = "; ".join(f"{url} ({reason})" for url, reason in rejected[:10])
        raise ScopeManifestError(
            f"{len(rejected)} {label} URL(s) fall outside scope manifest "
            f"{predicate.manifest.authorization_reference}: {detail}. "
            "No request was made. Correct the input set or the manifest; a mixed set is refused as a whole."
        )


def assert_cli_narrows_scope(
    predicate: ScopePredicate | None,
    *,
    allowed_hosts: Iterable[str] = (),
    offsite: bool = False,
    ignore_robots: bool = False,
    ignore_robots_confirmed: bool = False,
    seed_from_archive: bool = False,
) -> None:
    """Reject command-line options that would widen the manifest scope.

    Narrowing is always permitted: a smaller host list, a path restriction, or
    additional path exclusions simply reduce what the run touches. Widening is
    refused with an actionable message, because an option that appears to grant
    reach beyond the attested scope would make the manifest meaningless as
    evidence.
    """
    if predicate is None:
        return
    manifest = predicate.manifest

    if offsite:
        raise ScopeManifestError(
            "--offsite cannot be combined with --scope-manifest: off-site following would reach origins the "
            "manifest does not attest to. Remove --offsite, or declare the additional exact origins in the "
            "manifest."
        )

    manifest_hosts = {origin.split("://", 1)[1].rsplit(":", 1)[0] for origin in manifest.allowed_origins}
    widening_hosts = sorted(
        host
        for host in {entry.strip().rstrip(".").lower() for entry in allowed_hosts if entry.strip()}
        if host.split(":", 1)[0] not in manifest_hosts
    )
    if widening_hosts:
        raise ScopeManifestError(
            "--allowed-hosts may only narrow the scope manifest. These host(s) are not declared in manifest "
            f"{manifest.authorization_reference}: {', '.join(widening_hosts)}. "
            "Add the exact origins to the manifest, or drop them from --allowed-hosts."
        )

    if ignore_robots:
        if not manifest.allow_ignore_robots:
            raise ScopeManifestError(
                f"--ignore-robots is refused: scope manifest {manifest.authorization_reference} sets "
                "allow_ignore_robots to false."
            )
        if not ignore_robots_confirmed:
            raise ScopeManifestError(
                "--ignore-robots requires the explicit robots-override confirmation in addition to the "
                "manifest permission. The manifest permits the choice; it does not make it."
            )

    if seed_from_archive:
        archive_origins = {"https://web.archive.org:443", "http://web.archive.org:80"}
        if not archive_origins & set(manifest.allowed_origins):
            raise ScopeManifestError(
                "--archive-org-check fetches https://web.archive.org, which scope manifest "
                f"{manifest.authorization_reference} does not declare. Add that exact origin to the manifest "
                "or drop the archive seeding option."
            )


def run_capabilities(
    predicate: ScopePredicate | None,
    *,
    connection_pinning: bool = False,
    browser_backend: bool = False,
) -> ScopeCapabilities:
    """Describe what a run's guards actually cover.

    ``connection_pinning`` is true only when a Portal connection policy is
    active, which is the only path that pins an approved IP address for each
    connection. ``unguarded_browser_paths`` is true whenever a browser backend
    is in use, because URL-level interception is not the same guarantee as a
    pinned connection and must not be presented as one.
    """
    return ScopeCapabilities(
        intent_scope=predicate is not None,
        connection_pinning=connection_pinning,
        unguarded_browser_paths=browser_backend,
        scope_manifest_digest=None if predicate is None else predicate.digest,
    )


def describe_manifest(manifest: ScopeManifest) -> str:
    """Return the one-paragraph, secret-free operator summary for CLI output.

    Logs and console output name the digest and the opaque reference; they never
    print the manifest body, which could contain operator prose in ``notes``.
    """
    return (
        f"Scope manifest {manifest.authorization_reference} (operator {manifest.operator}), "
        f"digest {manifest.digest[:16]}…, valid {_format_timestamp(manifest.valid_from)} to "
        f"{_format_timestamp(manifest.valid_until)}, {len(manifest.allowed_origins)} exact origin(s). "
        f"{ATTESTATION_NOTICE}"
    )
