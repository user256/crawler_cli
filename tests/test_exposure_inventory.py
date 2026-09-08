"""Candidate host derivation and authorisation (ticket 146).

The property under test throughout is that **deriving a hostname is not
permission to look it up**. A candidate the manifest does not name must reach
the report as `not_authorised_not_resolved`, with no DNS query attributable to
it, because the query is itself observable traffic about a host nobody
declared.
"""

from __future__ import annotations

import pytest

from crawler_cli.exposure_inventory import (
    DEFAULT_NONPROD_LABELS,
    STATE_NOT_AUTHORISED,
    STATE_NOT_TESTED,
    CandidateDecision,
    ExposureInventoryError,
    authorise_candidates,
    authorised_origins,
    derive_candidate_hosts,
    host_from_url,
    normalise_labels,
    registrable_domain,
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
