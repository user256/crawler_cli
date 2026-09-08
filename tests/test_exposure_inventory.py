"""Candidate host derivation and authorisation (ticket 146).

The property under test throughout is that **deriving a hostname is not
permission to look it up**. A candidate the manifest does not name must reach
the report as `not_authorised_not_resolved`, with no DNS query attributable to
it, because the query is itself observable traffic about a host nobody
declared.
"""

from __future__ import annotations

import json
import socket
from types import SimpleNamespace

import pytest

from crawler_cli.destination_policy import DestinationPolicy
from crawler_cli.redaction import CorrelationDigest
from crawler_cli.exposure_inventory import (
    DEFAULT_NONPROD_LABELS,
    STATE_BLOCKED_BY_POLICY,
    STATE_NO_ADDRESS,
    STATE_NOT_AUTHORISED,
    STATE_NOT_TESTED,
    STATE_FETCH_FAILED,
    STATE_NXDOMAIN,
    STATE_REACHABLE,
    STATE_RESOLVED,
    STATE_RESOLVER_ERROR,
    STATE_TIMEOUT,
    CandidateDecision,
    ExposureInventoryError,
    authorise_candidates,
    build_inventory_artifact,
    candidate_probe_url,
    compare_to_error_template,
    authorised_origins,
    derive_candidate_hosts,
    fetchable_candidates,
    host_from_url,
    normalise_labels,
    probe_candidates,
    registrable_domain,
    resolve_candidates,
)


# ---------------------------------------------------------------------------
# Registrable domain — the Public Suffix List, not "the last two labels"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hostname", "expected"),
    [
        ("example.com", "example.com"),
        ("www.example.com", "example.com"),
        ("deep.sub.example.com", "example.com"),
        # The case that defeats last-two-labels: co.uk is a public suffix, so
        # the registrable domain has three labels, not two.
        ("www.example.co.uk", "example.co.uk"),
        ("shop.example.com.au", "example.com.au"),
        # Trailing dot and case are normalised.
        ("WWW.Example.COM.", "example.com"),
    ],
)
def test_registrable_domain_uses_the_public_suffix_list(hostname, expected):
    assert registrable_domain(hostname) == expected


def test_registrable_domain_respects_private_suffixes():
    """`github.io` is a private suffix, so a candidate never crosses onto
    somebody else's project on the same host."""
    assert registrable_domain("a.b.example.github.io") == "example.github.io"


@pytest.mark.parametrize("hostname", ["localhost", "co.uk", "", "   "])
def test_registrable_domain_is_none_when_there_is_nothing_to_derive_from(hostname):
    assert registrable_domain(hostname) is None


def test_host_from_url_extracts_and_normalises():
    assert host_from_url("https://WWW.Example.CO.UK./path?q=1") == "www.example.co.uk"
    assert host_from_url("not a url") is None


# ---------------------------------------------------------------------------
# Labels — a finite named set, never a brute-force dictionary
# ---------------------------------------------------------------------------


def test_default_labels_are_a_finite_sorted_set():
    assert DEFAULT_NONPROD_LABELS == ("cms", "dev", "preview", "stage", "staging", "test", "uat")


def test_operator_labels_are_normalised_and_deduplicated():
    assert normalise_labels([" DEV ", "dev", "sandbox"]) == ("dev", "sandbox")


@pytest.mark.parametrize("bad", [["*"], ["dev*"], ["a?b"]])
def test_wildcard_labels_are_rejected(bad):
    """Ticket 144: this is an inventory of a named set, not a subdomain
    brute-forcer."""
    with pytest.raises(ExposureInventoryError, match="wildcard"):
        normalise_labels(bad)


def test_a_hostname_is_not_a_label():
    with pytest.raises(ExposureInventoryError, match="single DNS label"):
        normalise_labels(["dev.example.com"])


def test_a_bare_string_is_not_a_label_list():
    with pytest.raises(ExposureInventoryError, match="list of DNS labels"):
        normalise_labels("dev")


def test_an_empty_label_list_is_an_error_not_a_silent_default():
    with pytest.raises(ExposureInventoryError, match="no usable"):
        normalise_labels(["", "  "])


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def test_candidates_are_derived_from_the_registrable_domain():
    candidates = derive_candidate_hosts(["www.example.co.uk"], labels=("dev", "staging"))

    assert [c.hostname for c in candidates] == ["dev.example.co.uk", "staging.example.co.uk"]
    assert {c.source for c in candidates} == {"derived_label"}


def test_derivation_is_deterministic_across_repeated_calls():
    first = derive_candidate_hosts(["b.example.com", "a.example.org"])
    second = derive_candidate_hosts(["a.example.org", "b.example.com"])
    assert [c.hostname for c in first] == [c.hostname for c in second]


def test_multiple_hosts_on_one_domain_derive_one_candidate_set():
    candidates = derive_candidate_hosts(["www.example.com", "shop.example.com", "example.com"], labels=("dev",))
    assert [c.hostname for c in candidates] == ["dev.example.com"]


def test_hosts_without_a_registrable_domain_derive_nothing():
    assert derive_candidate_hosts(["localhost"], labels=("dev",)) == []


def test_published_sitemap_hosts_are_recorded_as_a_distinct_source():
    """Publication is evidence the operator's own output mentions the host.

    It is a stronger signal than a guess, but ticket 146 is explicit that it is
    still not permission to resolve or fetch it.
    """
    candidates = derive_candidate_hosts(["www.example.com"], labels=("dev",), published_hosts=["en.example.com"])
    by_host = {c.hostname: c for c in candidates}

    assert by_host["en.example.com"].source == "published_sitemap_host"
    assert by_host["dev.example.com"].source == "derived_label"


def test_a_published_host_outranks_a_derived_guess_for_the_same_name():
    candidates = derive_candidate_hosts(["www.example.com"], labels=("dev",), published_hosts=["dev.example.com"])
    assert [c.source for c in candidates] == ["published_sitemap_host"]


# ---------------------------------------------------------------------------
# Authorisation — the gate that must precede any DNS
# ---------------------------------------------------------------------------


def test_undeclared_candidates_are_reported_without_being_resolved():
    candidates = derive_candidate_hosts(["www.example.com"], labels=("dev", "staging"))

    decisions = authorise_candidates(candidates, ["https://dev.example.com"])
    by_host = {d.candidate.hostname: d for d in decisions}

    assert by_host["dev.example.com"].authorised is True
    assert by_host["dev.example.com"].state == STATE_NOT_TESTED

    undeclared = by_host["staging.example.com"]
    assert undeclared.authorised is False
    assert undeclared.state == STATE_NOT_AUTHORISED
    assert undeclared.origin is None


def test_an_undeclared_candidate_yields_no_resolvable_origin():
    """The caller resolves only what this returns, so the gate is the list."""
    candidates = derive_candidate_hosts(["www.example.com"], labels=("dev", "staging"))
    decisions = authorise_candidates(candidates, ["https://dev.example.com"])

    assert authorised_origins(decisions) == ["https://dev.example.com"]


def test_a_parent_domain_does_not_authorise_a_subdomain():
    """Manifest v1 uses exact origins; this must not widen them."""
    candidates = derive_candidate_hosts(["www.example.com"], labels=("dev",))
    decisions = authorise_candidates(candidates, ["https://example.com"])

    assert decisions[0].authorised is False
    assert decisions[0].state == STATE_NOT_AUTHORISED


def test_either_scheme_may_declare_a_candidate():
    candidates = derive_candidate_hosts(["www.example.com"], labels=("dev",))

    http_only = authorise_candidates(candidates, ["http://dev.example.com"])
    assert http_only[0].authorised is True
    assert http_only[0].origin == "http://dev.example.com"


def test_no_manifest_origins_authorises_nothing():
    candidates = derive_candidate_hosts(["www.example.com"], labels=("dev",))

    assert authorise_candidates(candidates, []) == [
        CandidateDecision(
            candidate=candidates[0],
            authorised=False,
            state=STATE_NOT_AUTHORISED,
            origin=None,
        )
    ]
    assert authorise_candidates(candidates, None)[0].authorised is False


def test_authorised_origins_are_deterministic_and_deduplicated():
    candidates = derive_candidate_hosts(["www.example.com"], labels=("dev", "test"))
    decisions = authorise_candidates(candidates, ["https://test.example.com", "https://dev.example.com"])
    assert authorised_origins(decisions) == ["https://dev.example.com", "https://test.example.com"]


def test_decision_serialisation_keeps_source_and_state_distinct():
    candidates = derive_candidate_hosts(["www.example.com"], labels=("dev",))
    payload = authorise_candidates(candidates, [])[0].as_dict()

    assert payload == {
        "hostname": "dev.example.com",
        "source": "derived_label",
        "label": "dev",
        "authorised": False,
        "state": STATE_NOT_AUTHORISED,
        "origin": None,
    }


# ---------------------------------------------------------------------------
# Resolution — only for authorised candidates, with distinguishable outcomes
# ---------------------------------------------------------------------------


class _RecordingResolver:
    """Resolver stand-in that records every hostname it was asked about."""

    def __init__(self, answers=None, error=None):
        self.answers = answers or {}
        self.error = error
        self.asked: list[str] = []

    async def __call__(self, hostname: str, port: int) -> list[str]:
        self.asked.append(hostname)
        if self.error is not None:
            raise self.error
        return self.answers.get(hostname, [])


def _decisions(labels, origins):
    return authorise_candidates(derive_candidate_hosts(["www.example.com"], labels=labels), origins)


@pytest.mark.asyncio
async def test_an_unauthorised_candidate_is_never_handed_to_the_resolver():
    """The central safety property of ticket 146.

    A DNS query is observable traffic about a host nobody declared, so an
    undeclared candidate must not reach the resolver at all.
    """
    resolver = _RecordingResolver({"dev.example.com": ["93.184.216.34"]})
    decisions = _decisions(("dev", "staging"), ["https://dev.example.com"])

    results = await resolve_candidates(decisions, resolver=resolver)

    assert resolver.asked == ["dev.example.com"]
    by_host = {r.decision.candidate.hostname: r for r in results}
    assert by_host["staging.example.com"].state == STATE_NOT_AUTHORISED
    assert by_host["staging.example.com"].addresses == ()
    assert by_host["staging.example.com"].fetchable is False


@pytest.mark.asyncio
async def test_a_resolved_authorised_candidate_becomes_fetchable():
    resolver = _RecordingResolver({"dev.example.com": ["93.184.216.34"]})
    results = await resolve_candidates(_decisions(("dev",), ["https://dev.example.com"]), resolver=resolver)

    assert results[0].state == STATE_RESOLVED
    assert results[0].addresses == ("93.184.216.34",)
    assert results[0].fetchable is True
    assert fetchable_candidates(results) == results


@pytest.mark.asyncio
async def test_nxdomain_is_a_reportable_result_not_an_error():
    """A dev. label that does not exist is a useful inventory fact."""
    resolver = _RecordingResolver(error=socket.gaierror(socket.EAI_NONAME, "Name or service not known"))
    results = await resolve_candidates(_decisions(("dev",), ["https://dev.example.com"]), resolver=resolver)

    assert results[0].state == STATE_NXDOMAIN
    assert results[0].fetchable is False


@pytest.mark.asyncio
async def test_resolver_states_stay_distinguishable():
    """ "Does not exist" and "we could not ask" are different facts."""
    cases = {
        socket.gaierror(socket.EAI_AGAIN, "try again"): STATE_TIMEOUT,
        socket.gaierror(socket.EAI_FAIL, "fail"): STATE_RESOLVER_ERROR,
        TimeoutError(): STATE_TIMEOUT,
    }
    for error, expected in cases.items():
        resolver = _RecordingResolver(error=error)
        results = await resolve_candidates(_decisions(("dev",), ["https://dev.example.com"]), resolver=resolver)
        assert results[0].state == expected, error


@pytest.mark.asyncio
async def test_an_empty_answer_set_is_reported_as_no_address():
    resolver = _RecordingResolver({"dev.example.com": []})
    results = await resolve_candidates(_decisions(("dev",), ["https://dev.example.com"]), resolver=resolver)

    assert results[0].state == STATE_NO_ADDRESS
    assert results[0].fetchable is False


@pytest.mark.asyncio
async def test_a_private_address_is_blocked_by_the_destination_policy():
    """Ticket 149 decides where a connection may go; 146 records that it did."""
    resolver = _RecordingResolver({"dev.example.com": ["10.0.0.8"]})
    results = await resolve_candidates(
        _decisions(("dev",), ["https://dev.example.com"]), policy=DestinationPolicy(), resolver=resolver
    )

    assert results[0].state == STATE_BLOCKED_BY_POLICY
    assert results[0].detail == "private_address"
    assert results[0].fetchable is False


@pytest.mark.asyncio
async def test_a_mixed_answer_set_fails_closed_as_a_unit():
    """Same rule as ticket 149: narrowing to the public member keeps the
    rebinding primitive the guard exists to remove."""
    resolver = _RecordingResolver({"dev.example.com": ["93.184.216.34", "127.0.0.1"]})
    results = await resolve_candidates(
        _decisions(("dev",), ["https://dev.example.com"]), policy=DestinationPolicy(), resolver=resolver
    )

    assert results[0].state == STATE_BLOCKED_BY_POLICY
    assert results[0].fetchable is False


@pytest.mark.asyncio
async def test_resolution_serialisation_keeps_every_state_distinct():
    resolver = _RecordingResolver({"dev.example.com": ["93.184.216.34"]})
    results = await resolve_candidates(_decisions(("dev",), ["https://dev.example.com"]), resolver=resolver)

    payload = results[0].as_dict()
    assert payload["state"] == STATE_RESOLVED
    assert payload["addresses"] == ["93.184.216.34"]
    assert payload["authorised"] is True
    assert payload["source"] == "derived_label"


# ---------------------------------------------------------------------------
# Bounded probe — one request, one path, no bypass
# ---------------------------------------------------------------------------


class _RecordingFetcher:
    """Fetch stand-in recording every URL requested."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requested: list[str] = []

    async def __call__(self, url: str):
        self.requested.append(url)
        if self.error is not None:
            raise self.error
        return self.response


def _response(status=200, headers=None, title="Staging", final_url=None):
    return SimpleNamespace(
        status=status,
        headers=headers or {},
        extracted=SimpleNamespace(title=title),
        final_url=final_url,
    )


async def _resolved_candidate(addresses=("93.184.216.34",)):
    decisions = authorise_candidates(
        derive_candidate_hosts(["www.example.com"], labels=("dev",)), ["https://dev.example.com"]
    )
    return await resolve_candidates(decisions, resolver=_RecordingResolver({"dev.example.com": list(addresses)}))


@pytest.mark.asyncio
async def test_probe_makes_exactly_one_request_at_one_exact_path():
    """Ticket 146: one bounded GET. Never search the host."""
    resolutions = await _resolved_candidate()
    fetcher = _RecordingFetcher(_response())

    evidence = await probe_candidates(resolutions, fetcher)

    assert fetcher.requested == ["https://dev.example.com/"]
    assert evidence[0].state == STATE_REACHABLE
    assert evidence[0].status == 200


@pytest.mark.asyncio
async def test_probe_never_requests_an_unfetchable_candidate():
    """A refusal is never upgraded into an attempt by a later stage."""
    decisions = authorise_candidates(
        derive_candidate_hosts(["www.example.com"], labels=("dev", "staging")), ["https://dev.example.com"]
    )
    resolutions = await resolve_candidates(
        decisions,
        policy=DestinationPolicy(),
        resolver=_RecordingResolver({"dev.example.com": ["10.0.0.8"]}),
    )
    fetcher = _RecordingFetcher(_response())

    evidence = await probe_candidates(resolutions, fetcher)

    # dev resolved to a private address; staging was never authorised.
    assert fetcher.requested == []
    assert {e.state for e in evidence} == {STATE_BLOCKED_BY_POLICY, STATE_NOT_AUTHORISED}


@pytest.mark.asyncio
async def test_probe_records_a_credential_demand_without_attempting_it():
    """A 401 is the finding. Ticket 144 rules out trying to get past it."""
    resolutions = await _resolved_candidate()
    fetcher = _RecordingFetcher(_response(status=401, title=None))

    evidence = await probe_candidates(resolutions, fetcher)

    assert evidence[0].auth_demanded is True
    assert evidence[0].status == 401
    # One request only: no retry with credentials, no second path.
    assert len(fetcher.requested) == 1


@pytest.mark.asyncio
async def test_probe_records_x_robots_tag_case_insensitively():
    resolutions = await _resolved_candidate()
    fetcher = _RecordingFetcher(_response(headers={"X-Robots-Tag": "noindex"}))

    evidence = await probe_candidates(resolutions, fetcher)

    assert evidence[0].x_robots_tag == "noindex"
    assert evidence[0].title == "Staging"


@pytest.mark.asyncio
async def test_probe_records_a_redirect_target():
    resolutions = await _resolved_candidate()
    fetcher = _RecordingFetcher(_response(final_url="https://www.example.com/"))

    evidence = await probe_candidates(resolutions, fetcher)

    assert evidence[0].redirect_target == "https://www.example.com/"


@pytest.mark.asyncio
async def test_a_failed_probe_is_a_state_not_a_crash():
    resolutions = await _resolved_candidate()
    fetcher = _RecordingFetcher(error=TimeoutError())

    evidence = await probe_candidates(resolutions, fetcher)

    assert evidence[0].state == STATE_FETCH_FAILED
    assert evidence[0].detail == "TimeoutError"


@pytest.mark.asyncio
async def test_probe_honours_an_operator_supplied_exact_path():
    resolutions = await _resolved_candidate()
    fetcher = _RecordingFetcher(_response())

    await probe_candidates(resolutions, fetcher, path="/health")

    assert fetcher.requested == ["https://dev.example.com/health"]


@pytest.mark.parametrize("path", ["health", "/search?q=*", "/*"])
def test_a_probe_path_must_be_one_exact_absolute_path(path):
    with pytest.raises(ExposureInventoryError):
        candidate_probe_url("https://dev.example.com", path)


@pytest.mark.asyncio
async def test_evidence_serialisation_preserves_the_whole_chain():
    resolutions = await _resolved_candidate()
    fetcher = _RecordingFetcher(_response(headers={"x-robots-tag": "noindex"}))

    payload = (await probe_candidates(resolutions, fetcher))[0].as_dict()

    assert payload["hostname"] == "dev.example.com"
    assert payload["source"] == "derived_label"
    assert payload["authorised"] is True
    assert payload["addresses"] == ["93.184.216.34"]
    assert payload["state"] == STATE_REACHABLE
    assert payload["http"]["status"] == 200
    assert payload["http"]["x_robots_tag"] == "noindex"
    assert payload["http"]["auth_demanded"] is False


# ---------------------------------------------------------------------------
# Artifact — versioned, redacted, and honest about what was never tested
# ---------------------------------------------------------------------------


_FIXED_DIGEST = CorrelationDigest.from_key(b"exposure-inventory-test-key")


async def _evidence_for_artifact():
    decisions = authorise_candidates(
        derive_candidate_hosts(["www.example.com"], labels=("dev", "staging")),
        ["https://dev.example.com"],
    )
    resolutions = await resolve_candidates(
        decisions, resolver=_RecordingResolver({"dev.example.com": ["93.184.216.34"]})
    )
    fetcher = _RecordingFetcher(_response(headers={"x-robots-tag": "noindex"}))
    return await probe_candidates(resolutions, fetcher)


@pytest.mark.asyncio
async def test_artifact_is_versioned_and_carries_the_scope_digest():
    artifact = build_inventory_artifact(
        await _evidence_for_artifact(),
        scope_manifest_digest="sha256:abc",
        labels=("dev", "staging"),
        digest=_FIXED_DIGEST,
    )

    assert artifact["schema_version"] == "crawler-cli/exposure-inventory/1"
    assert artifact["label_set_version"] == "crawler-cli/nonprod-labels/1"
    assert artifact["scope_manifest_digest"] == "sha256:abc"
    assert artifact["labels"] == ["dev", "staging"]


@pytest.mark.asyncio
async def test_artifact_counts_keep_never_looked_separate_from_looked_and_clean():
    """Ticket 146: absent enrichment must never read as a clean result."""
    artifact = build_inventory_artifact(
        await _evidence_for_artifact(),
        scope_manifest_digest=None,
        labels=("dev", "staging"),
        digest=_FIXED_DIGEST,
    )
    summary = artifact["summary"]

    assert summary["candidates"] == 2
    assert summary["states"][STATE_REACHABLE] == 1
    assert summary["states"][STATE_NOT_AUTHORISED] == 1
    # Exactly one HTTP request was made, and the artifact says so.
    assert summary["requested"] == 1


@pytest.mark.asyncio
async def test_artifact_redacts_sensitive_values_in_urls_it_did_not_compose():
    """A redirect target is chosen by the site, not by this command."""
    decisions = authorise_candidates(
        derive_candidate_hosts(["www.example.com"], labels=("dev",)), ["https://dev.example.com"]
    )
    resolutions = await resolve_candidates(
        decisions, resolver=_RecordingResolver({"dev.example.com": ["93.184.216.34"]})
    )
    fetcher = _RecordingFetcher(_response(final_url="https://dev.example.com/?token=SUPERSECRET123"))
    evidence = await probe_candidates(resolutions, fetcher)

    artifact = build_inventory_artifact(evidence, scope_manifest_digest=None, labels=("dev",), digest=_FIXED_DIGEST)
    serialised = json.dumps(artifact)

    assert "SUPERSECRET123" not in serialised
    assert artifact["candidates"][0]["http"]["redirect_target"] is not None


@pytest.mark.asyncio
async def test_artifact_states_the_derived_is_not_a_finding_caveat():
    artifact = build_inventory_artifact(
        await _evidence_for_artifact(), scope_manifest_digest=None, labels=("dev",), digest=_FIXED_DIGEST
    )
    assert "not findings" in str(artifact["caveat"]) or "not a vulnerability" in str(artifact["caveat"])


@pytest.mark.asyncio
async def test_artifact_serialises_to_json():
    artifact = build_inventory_artifact(
        await _evidence_for_artifact(), scope_manifest_digest=None, labels=("dev",), digest=_FIXED_DIGEST
    )
    assert json.loads(json.dumps(artifact))["summary"]["candidates"] == 2


# ---------------------------------------------------------------------------
# Soft-404 comparison — similarity and indexability are separate claims
# ---------------------------------------------------------------------------


def _fingerprint(simhash=0b0, title="Page not found"):
    return SimpleNamespace(simhash=simhash, title=title)


def _page(url, status=200, simhash=0b0, title="Page not found", noindex=False):
    return SimpleNamespace(url=url, status=status, simhash=simhash, title=title, noindex=noindex)


def test_an_indexable_page_matching_the_error_template_is_a_finding_candidate():
    """The sapiens case: /page-404/ served as an indexable 200."""
    matches = compare_to_error_template(_fingerprint(), [_page("https://example.com/page-404/")])

    assert len(matches) == 1
    assert matches[0].similar is True
    assert matches[0].indexable is True
    assert matches[0].finding_candidate is True
    assert matches[0].path_hint == "404"


def test_a_genuine_404_resembling_the_template_is_not_a_finding():
    """Similarity and indexability are separate claims.

    A real 404 that looks like the error template is the site working
    correctly, so it must not be reported as a candidate.
    """
    matches = compare_to_error_template(_fingerprint(), [_page("https://example.com/missing", status=404)])

    assert matches[0].similar is True
    assert matches[0].indexable is False
    assert matches[0].finding_candidate is False


def test_a_noindexed_error_page_is_not_a_finding_candidate():
    matches = compare_to_error_template(_fingerprint(), [_page("https://example.com/page-404/", noindex=True)])
    assert matches[0].indexable is False
    assert matches[0].finding_candidate is False


def test_a_dissimilar_page_is_not_reported_at_all():
    far = 0xFFFF_FFFF_FFFF_FFFF
    matches = compare_to_error_template(
        _fingerprint(simhash=0), [_page("https://example.com/about", simhash=far, title="About us")]
    )
    assert matches == []


def test_similarity_uses_the_shared_simhash_threshold():
    """One definition of "near duplicate" across the codebase."""
    within = 0b111  # distance 3, inside the default threshold of 4
    beyond = 0b111_1111  # distance 7, outside it

    assert compare_to_error_template(_fingerprint(), [_page("https://a/", simhash=within, title="x")])
    assert compare_to_error_template(_fingerprint(), [_page("https://b/", simhash=beyond, title="x")]) == []


def test_a_matching_title_alone_is_enough_to_compare():
    """Sites often serve the error template with an identical title."""
    matches = compare_to_error_template(_fingerprint(simhash=None), [_page("https://example.com/x", simhash=None)])
    assert matches[0].title_matches is True
    assert matches[0].simhash_distance is None


@pytest.mark.parametrize(
    ("url", "hint"),
    [
        ("https://example.com/page-for-tests/", "page-for-tests"),
        ("https://example.com/page-404/", "404"),
        ("https://example.com/error/", "error"),
        ("https://example.com/about/", None),
    ],
)
def test_path_hints_are_provenance_not_a_verdict(url, hint):
    """Ticket 146: a URL containing 404 or test is a candidate, not a finding.

    The hint only ever annotates a comparison that already stands on its own
    evidence, so a benign URL is never promoted by its spelling alone.
    """
    matches = compare_to_error_template(_fingerprint(), [_page(url)])
    assert matches[0].path_hint == hint


def test_a_suspicious_path_without_similarity_is_not_reported():
    far = 0xFFFF_FFFF_FFFF_FFFF
    matches = compare_to_error_template(
        _fingerprint(simhash=0),
        [_page("https://example.com/page-404/", simhash=far, title="Real content")],
    )
    assert matches == []


def test_comparison_makes_no_requests():
    """The fingerprint came from one probe; the pages were already crawled."""
    matches = compare_to_error_template(_fingerprint(), [_page("https://example.com/page-404/")])
    assert matches[0].as_dict()["finding_candidate"] is True
