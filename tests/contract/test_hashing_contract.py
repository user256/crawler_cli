"""Frozen hash-algorithm contract (ticket 3344).

The exact sha256/simhash64 values for fixed inputs are part of the integration
contract: the portal stores fingerprints from one release and compares them
against crawls from another, so the algorithm (normalization included) must not
drift silently. If any constant here changes, that is a BREAKING contract
change requiring a major/minor version bump and a changelog entry.
"""

from __future__ import annotations

from contract_fixtures import (
    HTML_ALPHA,
    HTML_ALPHA_NEAR,
    HTML_CHANGED,
    SIMHASH_HIGHBIT_SIGNED,
    SIMHASH_HIGHBIT_UNSIGNED,
)

from crawler_cli.hashing import (
    hamming64,
    normalize_html_for_hashing,
    sha256_hash,
    simhash64,
    simhash_to_signed,
    simhash_to_unsigned,
)


def test_sha256_of_fixture_page_is_frozen() -> None:
    assert sha256_hash(HTML_ALPHA) == "eb44bf891485053a7983b4e5bc08bea0b42e2d5340bb79bee84a660596d75624"


def test_simhash64_of_fixture_pages_is_frozen() -> None:
    assert simhash64(HTML_ALPHA) == 1149681161556551646
    assert simhash64(HTML_ALPHA_NEAR) == 1140673962301810654
    assert simhash64("<p>apple cedar ember</p>") == SIMHASH_HIGHBIT_UNSIGNED


def test_normalization_strips_scripts_styles_and_dynamic_attrs() -> None:
    html = (
        '<html><body data-reactid="7" nonce="abc"><script>var x=1;</script>'
        "<style>p{}</style><noscript>no</noscript><p>hello   world</p></body></html>"
    )
    assert normalize_html_for_hashing(html) == "hello world"


def test_fixture_distances_are_frozen() -> None:
    assert hamming64(simhash64(HTML_ALPHA), simhash64(HTML_ALPHA_NEAR)) == 1
    assert hamming64(simhash64(HTML_ALPHA), simhash64(HTML_CHANGED)) == 27


def test_signed_unsigned_bigint_mapping_round_trips() -> None:
    assert simhash_to_signed(SIMHASH_HIGHBIT_UNSIGNED) == SIMHASH_HIGHBIT_SIGNED
    assert simhash_to_unsigned(SIMHASH_HIGHBIT_SIGNED) == SIMHASH_HIGHBIT_UNSIGNED
    # Values under 2^63 are unchanged in both directions.
    assert simhash_to_signed(1149681161556551646) == 1149681161556551646
    assert simhash_to_unsigned(1149681161556551646) == 1149681161556551646
    assert simhash_to_signed(None) is None
    assert simhash_to_unsigned(None) is None


def test_hamming64_accepts_either_representation() -> None:
    # signed-vs-unsigned of the SAME fingerprint is distance 0 …
    assert hamming64(SIMHASH_HIGHBIT_SIGNED, SIMHASH_HIGHBIT_UNSIGNED) == 0
    # … and mixed representations of DIFFERENT fingerprints agree with the
    # pure unsigned computation.
    other = simhash64(HTML_ALPHA)
    assert hamming64(SIMHASH_HIGHBIT_SIGNED, other) == hamming64(SIMHASH_HIGHBIT_UNSIGNED, other)
