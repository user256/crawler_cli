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

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from publicsuffixlist import PublicSuffixList

# Outcome states. Ticket 146 requires these to stay distinct so that "we never
# looked" can never be read as "we looked and it was clean".
STATE_NOT_TESTED = "not_tested"
STATE_NOT_AUTHORISED = "not_authorised_not_resolved"
STATE_NXDOMAIN = "nxdomain"
STATE_NO_ADDRESS = "no_address"
STATE_RESOLVER_ERROR = "resolver_error"
STATE_TIMEOUT = "resolver_timeout"
STATE_BLOCKED_BY_POLICY = "blocked_by_policy"
STATE_REACHABLE = "reachable"
STATE_FINDING_CANDIDATE = "finding_candidate"

# The default label set is deliberately finite, versioned and documented.
# Operators may add labels; wildcard or brute-force dictionaries are out of
# scope for this product (ticket 144) and are not accepted here.
DEFAULT_NONPROD_LABELS: tuple[str, ...] = ("cms", "dev", "preview", "stage", "staging", "test", "uat")

CANDIDATE_LABEL_SET_VERSION = "crawler-cli/nonprod-labels/1"

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
