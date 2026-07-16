"""Ticket 122: Hamming distance on 64-bit simhash fingerprints."""

from crawler_cli.hashing import hamming64, simhash_to_signed, simhash_to_unsigned


def test_identical_fingerprints_are_zero_distance():
    assert hamming64(0, 0) == 0
    assert hamming64(0xDEADBEEF, 0xDEADBEEF) == 0


def test_single_bit_difference():
    assert hamming64(0b0, 0b1) == 1
    assert hamming64(0b1010, 0b1000) == 1


def test_full_64_bit_difference():
    all_ones = (1 << 64) - 1
    assert hamming64(0, all_ones) == 64


def test_high_bit_sign_mapping_edge():
    # A fingerprint with the high bit set round-trips through the signed BIGINT
    # representation Postgres stores; hamming64 must treat both forms alike.
    unsigned = 1 << 63
    signed = simhash_to_signed(unsigned)
    assert signed is not None and signed < 0
    # Same value in either representation -> distance 0.
    assert hamming64(unsigned, signed) == 0
    assert hamming64(signed, unsigned) == 0
    # And still one bit away from an all-zero fingerprint.
    assert hamming64(signed, 0) == 1


def test_consistent_across_signed_unsigned_roundtrip():
    a = 0xF0F0F0F0F0F0F0F0
    b = 0x0F0F0F0F0F0F0F0F
    direct = hamming64(a, b)
    via_store = hamming64(simhash_to_signed(a), simhash_to_signed(b))
    assert direct == via_store == 64
    assert simhash_to_unsigned(simhash_to_signed(a)) == a
