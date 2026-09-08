"""Candidate non-production host derivation and authorisation (ticket 146).

This module answers two questions, in this order, and nothing else:

1. Which non-production hostnames does a crawled domain *suggest*?
2. Which of those has the operator actually *declared* in their scope manifest?

The order matters, and so does the separation. Deriving a hostname is a string
operation on a domain the crawler already visited. It is not permission to look
that hostname up, and it is certainly not permission to connect to it. A
candidate that the manifest does not name is reported as
``not_authorised_not_resolved`` and **no DNS query is made for it** — because a
lookup is itself observable traffic about a host nobody authorised.

Everything here is pure. Resolution, connection and HTTP evidence belong to the
caller, gated behind :func:`authorise_candidates`.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlsplit

from publicsuffixlist import PublicSuffixList

from .comparison import DEFAULT_SIMHASH_THRESHOLD
from .destination_policy import DestinationPolicy, classify_address
from .hashing import hamming64
from .redaction import CorrelationDigest, project_url

# Outcome states. Ticket 146 requires these to stay distinct so that "we never
# looked" can never be read as "we looked and it was clean".
STATE_NOT_TESTED = "not_tested"
STATE_NOT_AUTHORISED = "not_authorised_not_resolved"
STATE_NXDOMAIN = "nxdomain"
STATE_NO_ADDRESS = "no_address"
STATE_RESOLVER_ERROR = "resolver_error"
STATE_TIMEOUT = "resolver_timeout"
STATE_BLOCKED_BY_POLICY = "blocked_by_policy"
STATE_RESOLVED = "resolved"
STATE_FETCH_FAILED = "fetch_failed"
STATE_REACHABLE = "reachable"
STATE_FINDING_CANDIDATE = "finding_candidate"

# The default label set is deliberately finite, versioned and documented.
# Operators may add labels; wildcard or brute-force dictionaries are out of
# scope for this product (ticket 144) and are not accepted here.
DEFAULT_NONPROD_LABELS: tuple[str, ...] = ("cms", "dev", "preview", "stage", "staging", "test", "uat")

CANDIDATE_LABEL_SET_VERSION = "crawler-cli/nonprod-labels/1"

EXPOSURE_INVENTORY_SCHEMA_VERSION = "crawler-cli/exposure-inventory/1"

_psl = PublicSuffixList()


class ExposureInventoryError(ValueError):
    """Raised when candidate derivation is asked for something unusable."""


@dataclass(frozen=True, slots=True)
class HostCandidate:
    """One derived hostname and how it came to be considered.

    ``source`` records *why* this host is a candidate, so an operator reading
    the report can tell a derived guess from a hostname their own sitemap
    published.
    """

    hostname: str
    source: str
    label: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"hostname": self.hostname, "source": self.source, "label": self.label}


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    """An authorisation decision made before any network activity."""

    candidate: HostCandidate
    authorised: bool
    state: str
    origin: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            **self.candidate.as_dict(),
            "authorised": self.authorised,
            "state": self.state,
            "origin": self.origin,
        }


def registrable_domain(hostname: str) -> str | None:
    """Return the registrable domain, or ``None`` when there is not one.

    Uses the Public Suffix List rather than assuming the last two labels, so
    ``www.example.co.uk`` yields ``example.co.uk`` and not ``co.uk``. Private
    suffixes count: ``a.example.github.io`` yields ``example.github.io``, so a
    candidate is never derived across a hosting boundary onto someone else's
    project.

    ``localhost``, a bare public suffix and an IP literal all return ``None``:
    none of them has a registrable domain to hang a ``dev.`` label on.
    """
    host = hostname.strip().rstrip(".").lower()
    if not host:
        return None
    suffix = _psl.privatesuffix(host)
    return str(suffix) if suffix else None


def host_from_url(url: str) -> str | None:
    """Return the lowercased hostname of *url*, or ``None`` if it has none."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if not parsed.hostname:
        return None
    return parsed.hostname.strip().rstrip(".").lower()


def normalise_labels(labels: Iterable[str] | None) -> tuple[str, ...]:
    """Validate an operator label list into a sorted, deduplicated tuple.

    Rejects wildcards outright. A label is one DNS label: this is an inventory
    of a named finite set, not a subdomain brute-forcer (ticket 144).
    """
    if labels is None:
        return DEFAULT_NONPROD_LABELS
    if isinstance(labels, str) or not hasattr(labels, "__iter__"):
        raise ExposureInventoryError("non-production labels must be a list of DNS labels")
    cleaned: set[str] = set()
    for raw in labels:
        label = str(raw).strip().lower().strip(".")
        if not label:
            continue
        if "*" in label or "?" in label:
            raise ExposureInventoryError(f"wildcard labels are not supported: {raw!r}")
        if "." in label:
            raise ExposureInventoryError(f"expected a single DNS label, not a hostname: {raw!r}")
        if not all(character.isalnum() or character == "-" for character in label):
            raise ExposureInventoryError(f"label contains unsupported characters: {raw!r}")
        cleaned.add(label)
    if not cleaned:
        raise ExposureInventoryError("no usable non-production labels were supplied")
    return tuple(sorted(cleaned))


def derive_candidate_hosts(
    crawled_hosts: Iterable[str] | str,
    *,
    labels: tuple[str, ...] | None = None,
    published_hosts: Iterable[str] | str = (),
) -> list[HostCandidate]:
    """Derive the finite candidate host set for an inventory run.

    Two sources, kept distinct in the output:

    * ``derived_label`` — ``<label>.<registrable domain>`` for each crawled
      domain. A guess, and marked as one.
    * ``published_sitemap_host`` — a host an already-authorised sitemap named.
      That is evidence the operator's own publishing mentions it; ticket 146 is
      explicit that publication is still not permission to resolve or fetch it.

    Deterministic: same inputs, same order, no wall clock and no randomness.
    """
    label_set = normalise_labels(labels) if labels is not None else DEFAULT_NONPROD_LABELS
    crawled = [crawled_hosts] if isinstance(crawled_hosts, str) else list(crawled_hosts or ())
    published = [published_hosts] if isinstance(published_hosts, str) else list(published_hosts or ())

    candidates: dict[str, HostCandidate] = {}

    domains: list[str] = []
    for raw in crawled:
        host = str(raw).strip().rstrip(".").lower()
        domain = registrable_domain(host)
        if domain and domain not in domains:
            domains.append(domain)

    for domain in sorted(domains):
        for label in label_set:
            hostname = f"{label}.{domain}"
            candidates.setdefault(
                hostname,
                HostCandidate(hostname=hostname, source="derived_label", label=label),
            )

    for raw in published:
        host = str(raw).strip().rstrip(".").lower()
        if not host:
            continue
        # A published host is a stronger signal than a guess, so it wins the
        # source label if both would produce the same hostname.
        candidates[host] = HostCandidate(hostname=host, source="published_sitemap_host", label=None)

    return [candidates[name] for name in sorted(candidates)]


def _candidate_origins(hostname: str) -> tuple[str, str]:
    """Return the https and http origins a candidate hostname could occupy."""
    return (f"https://{hostname}", f"http://{hostname}")


def authorise_candidates(
    candidates: list[HostCandidate],
    allowed_origins: Iterable[str] | None,
) -> list[CandidateDecision]:
    """Decide which candidates the manifest actually declared, before any DNS.

    Deriving a hostname is not authorisation. A candidate whose origin the
    manifest does not name is returned as ``not_authorised_not_resolved`` and
    the caller must not look it up: the DNS query would itself be traffic about
    a host nobody declared.

    ``allowed_origins`` are the exact origins from the ticket-148 manifest.
    Version 1 of that manifest uses exact origins, so a parent domain never
    implicitly authorises a subdomain here either.
    """
    origins = frozenset(str(origin).strip().rstrip("/").lower() for origin in (allowed_origins or ()))
    decisions: list[CandidateDecision] = []
    for candidate in candidates:
        matched: str | None = None
        for origin in _candidate_origins(candidate.hostname):
            if origin in origins:
                matched = origin
                break
        if matched is None:
            decisions.append(
                CandidateDecision(
                    candidate=candidate,
                    authorised=False,
                    state=STATE_NOT_AUTHORISED,
                    origin=None,
                )
            )
            continue
        # Authorised only means "may now be resolved". The resolution and any
        # HTTP evidence are the caller's next step, and each has its own state.
        decisions.append(
            CandidateDecision(
                candidate=candidate,
                authorised=True,
                state=STATE_NOT_TESTED,
                origin=matched,
            )
        )
    return decisions


def authorised_origins(decisions: list[CandidateDecision]) -> list[str]:
    """Return only the origins a caller may resolve, in deterministic order."""
    return sorted({decision.origin for decision in decisions if decision.authorised and decision.origin})


@dataclass(frozen=True, slots=True)
class CandidateResolution:
    """What one authorised candidate resolved to, and whether it may be fetched.

    A DNS result is an inventory fact in its own right. ``nxdomain`` for a
    ``dev.`` label is a useful answer, not a failure to report.
    """

    decision: CandidateDecision
    state: str
    addresses: tuple[str, ...] = ()
    detail: str | None = None

    @property
    def fetchable(self) -> bool:
        """True only when an HTTP request is permitted for this candidate."""
        return self.state == STATE_RESOLVED

    def as_dict(self) -> dict[str, object]:
        return {
            **self.decision.as_dict(),
            "state": self.state,
            "addresses": list(self.addresses),
            "detail": self.detail,
        }


async def _default_resolver(hostname: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(hostname, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    return sorted({str(record[4][0]) for record in records})


def _dns_failure_state(exc: BaseException) -> tuple[str, str]:
    """Map a resolver failure onto a distinct, reportable state.

    Ticket 146 requires NXDOMAIN, no-address, timeout and resolver error to
    stay distinguishable: "this name does not exist" and "we could not ask" are
    different facts about a site, and collapsing them hides the difference.
    """
    if isinstance(exc, TimeoutError):
        return STATE_TIMEOUT, "resolution timed out"
    if isinstance(exc, socket.gaierror):
        code = getattr(exc, "errno", None)
        if code in {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME)}:
            return STATE_NXDOMAIN, "name does not resolve"
        if code == socket.EAI_AGAIN:
            return STATE_TIMEOUT, "resolver temporarily unavailable"
        return STATE_RESOLVER_ERROR, "resolver error"
    return STATE_RESOLVER_ERROR, "resolver error"


async def resolve_candidates(
    decisions: list[CandidateDecision],
    *,
    policy: DestinationPolicy | None = None,
    resolver: Callable[[str, int], Awaitable[list[str]]] | None = None,
    timeout_seconds: float = 5.0,
) -> list[CandidateResolution]:
    """Resolve only the authorised candidates, and classify what comes back.

    Unauthorised candidates are passed straight through untouched: they are
    never handed to the resolver, because the lookup would itself be traffic
    about a host the operator never declared.

    Every returned address is then checked against the ticket-149 destination
    policy, and a mixed answer set fails closed as a unit exactly as it does
    there — narrowing to the permitted member would leave the same rebinding
    primitive.
    """
    resolve = resolver or _default_resolver
    results: list[CandidateResolution] = []
    for decision in decisions:
        if not decision.authorised or decision.origin is None:
            results.append(CandidateResolution(decision=decision, state=decision.state))
            continue
        hostname = decision.candidate.hostname
        port = 443 if decision.origin.startswith("https://") else 80
        try:
            async with asyncio.timeout(timeout_seconds):
                addresses = await resolve(hostname, port)
        except Exception as exc:  # noqa: BLE001 - every failure maps to a state
            state, detail = _dns_failure_state(exc)
            results.append(CandidateResolution(decision=decision, state=state, detail=detail))
            continue
        if not addresses:
            results.append(CandidateResolution(decision=decision, state=STATE_NO_ADDRESS, detail="no address records"))
            continue
        if policy is not None:
            denied = {address: classify_address(address, policy) for address in addresses}
            reasons = sorted({reason for reason in denied.values() if reason is not None})
            if reasons:
                results.append(
                    CandidateResolution(
                        decision=decision,
                        state=STATE_BLOCKED_BY_POLICY,
                        addresses=tuple(addresses),
                        detail=", ".join(reasons),
                    )
                )
                continue
        results.append(CandidateResolution(decision=decision, state=STATE_RESOLVED, addresses=tuple(addresses)))
    return results


def fetchable_candidates(resolutions: list[CandidateResolution]) -> list[CandidateResolution]:
    """Return only the candidates an HTTP request is permitted for."""
    return [resolution for resolution in resolutions if resolution.fetchable]


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    """Bounded HTTP evidence from one candidate origin.

    ``auth_demanded`` records that the host asked for credentials. Ticket 146
    is explicit that this is where the inventory stops: a 401 is the finding.
    Trying to get past it would make this a different product (ticket 144).
    """

    resolution: CandidateResolution
    state: str
    status: int | None = None
    final_url: str | None = None
    title: str | None = None
    x_robots_tag: str | None = None
    auth_demanded: bool = False
    redirect_target: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            **self.resolution.as_dict(),
            "state": self.state,
            "http": {
                "status": self.status,
                "final_url": self.final_url,
                "title": self.title,
                "x_robots_tag": self.x_robots_tag,
                "auth_demanded": self.auth_demanded,
                "redirect_target": self.redirect_target,
            },
            "detail": self.detail,
        }


def candidate_probe_url(origin: str, path: str = "/") -> str:
    """Return the single URL this inventory may request on a candidate origin.

    One exact path, defaulting to ``/``. The host is never searched: ticket 146
    inventories what an authorised origin serves at a declared path, and
    guessing further paths is forced browsing, which ticket 144 excludes.
    """
    if not path.startswith("/"):
        raise ExposureInventoryError(f"candidate path must be absolute, got {path!r}")
    if "*" in path or "?" in path:
        raise ExposureInventoryError(f"candidate path must be one exact path, got {path!r}")
    return f"{origin.rstrip('/')}{path}"


async def probe_candidates(
    resolutions: list[CandidateResolution],
    fetch: Callable[[str], Awaitable[object]],
    *,
    path: str = "/",
) -> list[CandidateEvidence]:
    """Make at most one bounded GET per fetchable candidate.

    Candidates that were never authorised, never resolved, or blocked by the
    destination policy are passed through with their existing state: this stage
    adds evidence, and never upgrades a refusal into an attempt.

    Exactly one request per candidate. There is no retry and no second path,
    because a retry loop against a host that refused is the behaviour ticket
    144 rules out.
    """
    evidence: list[CandidateEvidence] = []
    for resolution in resolutions:
        if not resolution.fetchable or resolution.decision.origin is None:
            evidence.append(CandidateEvidence(resolution=resolution, state=resolution.state))
            continue
        url = candidate_probe_url(resolution.decision.origin, path)
        try:
            response = await fetch(url)
        except Exception as exc:  # noqa: BLE001 - a failed probe is a state, not a crash
            evidence.append(
                CandidateEvidence(
                    resolution=resolution,
                    state=STATE_FETCH_FAILED,
                    detail=type(exc).__name__,
                )
            )
            continue
        status = int(getattr(response, "status", 0) or 0)
        headers = dict(getattr(response, "headers", {}) or {})
        extracted = getattr(response, "extracted", None)
        final_url = str(getattr(response, "final_url", url) or url)
        evidence.append(
            CandidateEvidence(
                resolution=resolution,
                state=STATE_REACHABLE,
                status=status,
                final_url=final_url,
                title=getattr(extracted, "title", None) if extracted is not None else None,
                x_robots_tag=_header(headers, "x-robots-tag"),
                # A demand for credentials is the finding. The inventory records
                # it and stops; it never attempts to satisfy it.
                auth_demanded=status in {401, 403},
                redirect_target=final_url if final_url != url else None,
            )
        )
    return evidence


def _header(headers: dict[str, object], name: str) -> str | None:
    """Case-insensitive header lookup."""
    for key, value in headers.items():
        if str(key).lower() == name:
            return str(value)
    return None


def _redacted_url(url: str | None, digest: CorrelationDigest) -> str | None:
    """Apply the ticket-153 projection to a URL this command did not compose.

    Candidate and redirect URLs can carry sensitive query values even though
    the inventory only ever requested one bare path: a redirect target is
    chosen by the site, not by us.
    """
    if not url:
        return None
    return project_url(url, digest=digest).redacted


def build_inventory_artifact(
    evidence: list[CandidateEvidence],
    *,
    scope_manifest_digest: str | None,
    labels: tuple[str, ...],
    digest: CorrelationDigest | None = None,
) -> dict[str, object]:
    """Assemble the versioned, redacted exposure-inventory artifact.

    Counts are reported per state so that "never looked" can never be read as
    "looked and found nothing": ``not_authorised_not_resolved`` and
    ``reachable`` are separate lines, and absent enrichment is never a clean
    result.
    """
    correlation = digest or CorrelationDigest.for_run()
    rows: list[dict[str, object]] = []
    counts: dict[str, int] = {}
    for item in evidence:
        row = item.as_dict()
        row["hostname"] = str(row["hostname"])
        http = cast("dict[str, object]", row["http"])
        http["final_url"] = _redacted_url(item.final_url, correlation)
        http["redirect_target"] = _redacted_url(item.redirect_target, correlation)
        row["origin"] = _redacted_url(item.resolution.decision.origin, correlation)
        rows.append(row)
        counts[item.state] = counts.get(item.state, 0) + 1
    return {
        "schema_version": EXPOSURE_INVENTORY_SCHEMA_VERSION,
        "label_set_version": CANDIDATE_LABEL_SET_VERSION,
        "observed_at": datetime.now(UTC).isoformat(),
        "scope_manifest_digest": scope_manifest_digest,
        "labels": list(labels),
        "summary": {
            "candidates": len(evidence),
            "states": counts,
            # Requested is the honest cost figure: how many HTTP requests this
            # command actually made against the operator's systems.
            "requested": counts.get(STATE_REACHABLE, 0) + counts.get(STATE_FETCH_FAILED, 0),
        },
        "candidates": rows,
        "caveat": (
            "Derived hostnames are candidates, not findings. A resolving host is an "
            "inventory fact, not a vulnerability, and an unauthorised candidate was "
            "never resolved or requested."
        ),
    }


@dataclass(frozen=True, slots=True)
class ErrorTemplateMatch:
    """How closely one crawled 200 resembles the site's own error page.

    ``similar`` and ``indexable`` are separate fields on purpose. Ticket 146
    requires similarity to be classified separately from indexability: a page
    that looks like the 404 template is a *candidate*, and it only becomes
    interesting when the site also serves it as an indexable 200.
    """

    url: str
    status: int
    similar: bool
    indexable: bool
    simhash_distance: int | None = None
    title_matches: bool = False
    path_hint: str | None = None

    @property
    def finding_candidate(self) -> bool:
        """An indexable 200 that resembles the error template."""
        return self.similar and self.indexable

    def as_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "status": self.status,
            "similar_to_error_template": self.similar,
            "indexable": self.indexable,
            "simhash_distance": self.simhash_distance,
            "title_matches": self.title_matches,
            "path_hint": self.path_hint,
            "finding_candidate": self.finding_candidate,
        }


def _path_hint(url: str) -> str | None:
    """Return the suspicious token in a URL path, if it carries one.

    A hint is provenance, never a verdict. Ticket 146 is explicit that a URL
    containing ``404`` or ``test`` is a candidate and not a finding by itself,
    so this only ever annotates a comparison that stands on its own evidence.
    """
    path = (urlsplit(url).path or "").lower()
    for token in ("page-for-tests", "404", "not-found", "notfound", "error", "test"):
        if token in path:
            return token
    return None


def compare_to_error_template(
    fingerprint: object,
    crawled: Iterable[object],
    *,
    simhash_threshold: int = DEFAULT_SIMHASH_THRESHOLD,
) -> list[ErrorTemplateMatch]:
    """Compare already-crawled 200s against the site's own error fingerprint.

    Makes no requests: the fingerprint came from one bounded probe and the
    pages were already fetched by the parent crawl.

    Similarity uses the same SimHash distance and default threshold as
    ``comparison.py`` rather than a second scale, so "near-duplicate" means one
    thing across this codebase.
    """
    reference_simhash = getattr(fingerprint, "simhash", None)
    reference_title = (getattr(fingerprint, "title", None) or "").strip().lower()
    matches: list[ErrorTemplateMatch] = []
    for page in crawled:
        status = int(getattr(page, "status", 0) or 0)
        url = str(getattr(page, "url", "") or getattr(page, "final_url", "") or "")
        if not url:
            continue
        page_simhash = getattr(page, "simhash", None)
        distance: int | None = None
        if reference_simhash is not None and page_simhash is not None:
            distance = hamming64(int(reference_simhash), int(page_simhash))
        title = (getattr(page, "title", None) or "").strip().lower()
        title_matches = bool(reference_title) and title == reference_title
        similar = (distance is not None and distance <= simhash_threshold) or title_matches
        if not similar:
            continue
        matches.append(
            ErrorTemplateMatch(
                url=url,
                status=status,
                similar=True,
                # Indexability is the site's own claim about the page, kept
                # apart from how much it resembles the error template.
                indexable=status == 200 and not bool(getattr(page, "noindex", False)),
                simhash_distance=distance,
                title_matches=title_matches,
                path_hint=_path_hint(url),
            )
        )
    return matches


@dataclass(frozen=True, slots=True)
class SitemapHostRecord:
    """One host an already-authorised sitemap published, and its standing.

    A sitemap is the operator's own statement about what they publish, so a
    host appearing there is evidence worth reporting even when it is dead. It
    is still not permission to resolve or fetch that host: ``authorised``
    reflects the manifest, never the sitemap.
    """

    hostname: str
    loc_count: int
    is_preferred_host: bool
    authorised: bool
    sample_paths: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "hostname": self.hostname,
            "loc_count": self.loc_count,
            "is_preferred_host": self.is_preferred_host,
            "authorised": self.authorised,
            "sample_paths": list(self.sample_paths),
        }


def inventory_sitemap_hosts(
    sitemap_locs: Iterable[str],
    *,
    preferred_host: str | None = None,
    allowed_origins: Iterable[str] | None = None,
    sample_limit: int = 3,
) -> list[SitemapHostRecord]:
    """Inventory every host an authorised sitemap explicitly published.

    Reports hosts the sitemap names even when they are dead, on a legacy CDN,
    or a leftover ``content.`` / ``en.`` prefix: a sitemap advertising a host
    the operator no longer runs is exactly the finding this is for, and it is
    visible without a single request.

    Publication is not permission. ``authorised`` is decided against the
    ticket-148 manifest origins only, so an unauthorised host is inventoried
    and reported without becoming eligible for DNS or HTTP enrichment.
    """
    origins = frozenset(str(origin).strip().rstrip("/").lower() for origin in (allowed_origins or ()))
    preferred = (preferred_host or "").strip().rstrip(".").lower()

    counts: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    for loc in sitemap_locs:
        host = host_from_url(str(loc))
        if not host:
            continue
        counts[host] = counts.get(host, 0) + 1
        paths = samples.setdefault(host, [])
        if len(paths) < sample_limit:
            path = urlsplit(str(loc)).path or "/"
            if path not in paths:
                paths.append(path)

    records: list[SitemapHostRecord] = []
    for host in sorted(counts):
        authorised = any(f"{scheme}://{host}" in origins for scheme in ("https", "http"))
        records.append(
            SitemapHostRecord(
                hostname=host,
                loc_count=counts[host],
                is_preferred_host=bool(preferred) and host == preferred,
                authorised=authorised,
                sample_paths=tuple(samples.get(host, ())),
            )
        )
    return records


def non_preferred_sitemap_hosts(records: list[SitemapHostRecord]) -> list[SitemapHostRecord]:
    """Return the published hosts that are not the site's preferred host.

    These are the interesting ones: a sitemap that advertises a host other than
    the canonical one is publishing something the operator may not know about.
    """
    return [record for record in records if not record.is_preferred_host]
