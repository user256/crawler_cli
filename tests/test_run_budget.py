"""Ticket 3685: run-budget admission is decided before request emission."""

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
async def test_aggregate_budget_reserves_response_cap_before_dispatch() -> None:
    budget = RunBudget(max_bytes=25, max_response_bytes=20)
    first = await budget.reserve()

    # Even though the first body may ultimately be tiny, a concurrent 20-byte
    # request cannot be emitted while its full response cap is reserved.
    with pytest.raises(RunBudgetExhausted, match="max_bytes"):
        await budget.reserve()

    await budget.settle(first, 5)
    second = await budget.reserve()
    await budget.settle(second, 20)
    snapshot = await budget.snapshot()
    assert snapshot.response_bytes == 25


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

    outcomes = await asyncio.gather(budget.reserve(), budget.reserve(), return_exceptions=True)

    reservations = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
    failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    assert len(reservations) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], RunBudgetExhausted)
    await budget.settle(reservations[0], 20)


@pytest.mark.asyncio
async def test_distinct_equal_size_reservations_settle_independently() -> None:
    budget = RunBudget(max_response_bytes=10)
    first, second = await asyncio.gather(budget.reserve(), budget.reserve())

    assert first.reservation_id != second.reservation_id
    await budget.settle(first, 1)
    await budget.settle(second, 2)
    assert (await budget.snapshot()).response_bytes == 3
