"""Ticket 3685: request admission and streamed byte accounting."""

from __future__ import annotations

import asyncio

import pytest

from crawler_cli.budget import RunBudget, RunBudgetExhausted


@pytest.mark.asyncio
async def test_request_limit_blocks_a_second_dispatch_before_it_starts() -> None:
    budget = RunBudget(max_requests=1, max_response_bytes=20)
    first = await budget.reserve()

    with pytest.raises(RunBudgetExhausted, match="max_requests"):
        await budget.reserve()

    await budget.settle(first, 3)
    snapshot = await budget.snapshot()
    assert snapshot.requests_started == 1
    assert snapshot.requests_in_flight == 0
    assert snapshot.response_bytes == 3


@pytest.mark.asyncio
async def test_aggregate_budget_does_not_reserve_the_default_response_cap() -> None:
    budget = RunBudget(max_bytes=25, max_response_bytes=20)
    first = await budget.reserve()
    second = await budget.reserve()

    # A 25 MB-style per-response ceiling must not prevent a small aggregate
    # run from starting two connections. Capacity is leased per actual read.
    first_read = await budget.reserve_bytes(first, 20)
    await budget.settle_bytes(first_read, wire_bytes=5, decoded_bytes=5)
    second_read = await budget.reserve_bytes(second, 20)
    await budget.settle_bytes(second_read, wire_bytes=20, decoded_bytes=20)
    await budget.settle(first)
    await budget.settle(second)

    snapshot = await budget.snapshot()
    assert snapshot.wire_bytes == snapshot.decoded_bytes == snapshot.accounted_bytes == 25


@pytest.mark.asyncio
async def test_failed_request_still_uses_request_slot_but_releases_byte_reservation() -> None:
    budget = RunBudget(max_requests=1, max_bytes=10, max_response_bytes=10)
    reservation = await budget.reserve()
    await budget.settle(reservation, 0)

    with pytest.raises(RunBudgetExhausted, match="max_requests"):
        await budget.reserve()
    assert (await budget.snapshot()).response_bytes_reserved == 0


@pytest.mark.asyncio
async def test_parallel_reservations_cannot_race_past_aggregate_cap() -> None:
    budget = RunBudget(max_bytes=20, max_response_bytes=20)
    first, second = await asyncio.gather(budget.reserve(), budget.reserve())

    outcomes = await asyncio.gather(
        budget.reserve_bytes(first, 20), budget.reserve_bytes(second, 20), return_exceptions=True
    )

    reservations = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
    failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    assert len(reservations) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], RunBudgetExhausted)
    await budget.settle_bytes(reservations[0], wire_bytes=20, decoded_bytes=20)
    await budget.settle(first)
    await budget.settle(second)


@pytest.mark.asyncio
async def test_distinct_equal_size_reservations_settle_independently() -> None:
    budget = RunBudget(max_response_bytes=10)
    first, second = await asyncio.gather(budget.reserve(), budget.reserve())

    assert first.reservation_id != second.reservation_id
    await budget.settle(first, 1)
    await budget.settle(second, 2)
    assert (await budget.snapshot()).response_bytes == 3


@pytest.mark.asyncio
async def test_short_final_stream_lease_sets_typed_max_bytes_stop_reason() -> None:
    budget = RunBudget(max_bytes=7, max_response_bytes=1_000)
    request = await budget.reserve()

    lease = await budget.reserve_bytes(request, 64)
    assert lease.reserved_bytes == 7
    await budget.settle_bytes(lease, wire_bytes=7, decoded_bytes=7)

    with pytest.raises(RunBudgetExhausted, match="max_bytes") as exc_info:
        await budget.reserve_bytes(request, 1)
    assert exc_info.value.reason == "max_bytes"
    assert (await budget.snapshot()).stop_reason == "max_bytes"
    await budget.settle(request)


@pytest.mark.asyncio
async def test_accounted_bytes_uses_the_larger_decoded_compressed_dimension() -> None:
    budget = RunBudget(max_bytes=10, max_response_bytes=1_000)
    request = await budget.reserve()

    # A compressed read can emit more decoded data than it consumed on the
    # wire. The read is lease-bounded in both dimensions, so the aggregate
    # remains within the configured cap.
    lease = await budget.reserve_bytes(request, 10)
    await budget.settle_bytes(lease, wire_bytes=3, decoded_bytes=10)
    snapshot = await budget.snapshot()
    assert snapshot.wire_bytes == 3
    assert snapshot.decoded_bytes == snapshot.accounted_bytes == 10

    with pytest.raises(RunBudgetExhausted, match="max_bytes"):
        await budget.reserve_bytes(request, 1)
    await budget.settle(request)


@pytest.mark.asyncio
async def test_accounted_bytes_sums_each_response_conservative_dimension() -> None:
    """A wire-heavy page and decoded-heavy page must not cancel each other."""
    budget = RunBudget(max_bytes=200, max_response_bytes=1_000)
    first, second = await asyncio.gather(budget.reserve(), budget.reserve())
    first_lease = await budget.reserve_bytes(first, 100)
    await budget.settle_bytes(first_lease, wire_bytes=100, decoded_bytes=1)
    second_lease = await budget.reserve_bytes(second, 100)
    await budget.settle_bytes(second_lease, wire_bytes=1, decoded_bytes=100)
    snapshot = await budget.snapshot()

    assert snapshot.wire_bytes == snapshot.decoded_bytes == 101
    assert snapshot.accounted_bytes == 200
    await budget.settle(first)
    await budget.settle(second)


@pytest.mark.asyncio
async def test_settlement_rejects_unleased_decoder_expansion() -> None:
    budget = RunBudget(max_bytes=10, max_response_bytes=1_000)
    request = await budget.reserve()
    lease = await budget.reserve_bytes(request, 5)

    with pytest.raises(ValueError, match="decoded_bytes exceeds"):
        await budget.settle_bytes(lease, wire_bytes=1, decoded_bytes=6)

    # The failed settlement intentionally leaves the lease active for its
    # owner to settle correctly, preserving accounting rather than leaking it.
    await budget.settle_bytes(lease, wire_bytes=1, decoded_bytes=5)
    await budget.settle(request)


@pytest.mark.asyncio
async def test_equal_sized_concurrent_leases_on_one_request_are_distinct() -> None:
    """Leases are identified individually, not by (request, size)."""
    budget = RunBudget(max_requests=0, max_bytes=1000, max_response_bytes=1000)
    reservation = await budget.reserve()
    first = await budget.reserve_bytes(reservation, 100)
    second = await budget.reserve_bytes(reservation, 100)
    assert first.lease_id != second.lease_id
    assert (await budget.snapshot()).bytes_reserved == 200

    await budget.settle_bytes(first, wire_bytes=100, decoded_bytes=100)
    assert (await budget.snapshot()).bytes_reserved == 100
    await budget.settle_bytes(second, wire_bytes=50, decoded_bytes=50)
    snapshot = await budget.snapshot()
    assert snapshot.bytes_reserved == 0
    assert snapshot.wire_bytes == 150

    await budget.settle(reservation)
