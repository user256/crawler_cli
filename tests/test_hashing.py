from crawler_cli.hashing import sha256_hash, simhash64


def test_hashes_are_stable_for_dynamic_attributes():
    html_a = '<html><body><div data-ts="1">Hello world</div></body></html>'
    html_b = '<html><body><div data-ts="999">Hello world</div></body></html>'

    assert sha256_hash(html_a) == sha256_hash(html_b)
    assert simhash64(html_a) == simhash64(html_b)

