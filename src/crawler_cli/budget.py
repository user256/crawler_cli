"""Run-scoped request and response-body budget accounting (ticket 3685).

``RunBudget`` deliberately reserves a full per-response cap before allowing a
request to be emitted.  A response can settle for fewer bytes afterwards, but
concurrent requests can never collectively exceed the configured aggregate
response-body budget.  Backends must call :meth:`reserve` immediately before
their network operation and :meth:`settle` in a ``finally`` block; merely
counting completed responses is not a pre-emission guard.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


class RunBudgetExhausted(RuntimeError):
    """Raised when dispatching another request would exceed a run budget."""


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    """One request slot and its conservative response-body reservation."""

    reservation_id: int
    reserved_response_bytes: int


@dataclass(frozen=True, slots=True)
class RunBudgetSnapshot:
    """Read-only accounting state, suitable for diagnostics and tests."""

    requests_started: int
    requests_in_flight: int
    response_bytes: int
    response_bytes_reserved: int


class RunBudget:
    """Async-safe, per-run admission control for network requests.

    Zero limits mean unlimited.  ``max_response_bytes`` is the maximum a
    compliant streaming backend can read for one response.  Reserving it up
    front is intentionally conservative: with a 10-byte remaining aggregate
    budget and a 20-byte per-response cap, the next request is refused rather
    than emitted and allowed to overshoot the aggregate cap.
    """

    def __init__(
        self,
        *,
        max_requests: int = 0,
        max_bytes: int = 0,
        max_response_bytes: int,
    ) -> None:
        if max_requests < 0:
            raise ValueError("max_requests must be >= 0")
        if max_bytes < 0:
            raise ValueError("max_bytes must be >= 0")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be > 0")
        self.max_requests = max_requests
        self.max_bytes = max_bytes
        self.max_response_bytes = max_response_bytes
        self._requests_started = 0
        self._requests_in_flight = 0
        self._response_bytes = 0
        self._response_bytes_reserved = 0
        self._active_reservations: set[int] = set()
        self._next_reservation_id = 0
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self.max_requests > 0 or self.max_bytes > 0

    async def reserve(self) -> BudgetReservation:
        """Reserve capacity before a network request is emitted.

        The returned reservation must be settled exactly once, including when
        connection setup fails, because a failed connection attempt still
        consumes one request from the run budget.
        """
        async with self._lock:
            if self.max_requests and self._requests_started >= self.max_requests:
                raise RunBudgetExhausted("max_requests exhausted before request emission")
            if (
                self.max_bytes
                and self._response_bytes + self._response_bytes_reserved + self.max_response_bytes
                > self.max_bytes
            ):
                raise RunBudgetExhausted("max_bytes exhausted before request emission")

            self._requests_started += 1
            self._requests_in_flight += 1
            self._response_bytes_reserved += self.max_response_bytes
            reservation_id = self._next_reservation_id
            self._next_reservation_id += 1
            self._active_reservations.add(reservation_id)
            return BudgetReservation(reservation_id, self.max_response_bytes)

    async def settle(self, reservation: BudgetReservation, response_bytes: int) -> None:
        """Commit actual bytes read and release unused reserved capacity."""
        if response_bytes < 0:
            raise ValueError("response_bytes must be >= 0")
        if response_bytes > reservation.reserved_response_bytes:
            raise ValueError("response_bytes exceeds the reservation cap")
        async with self._lock:
            if reservation.reservation_id not in self._active_reservations:
                raise ValueError("reservation was not active or was already settled")
            self._active_reservations.remove(reservation.reservation_id)
            self._requests_in_flight -= 1
            self._response_bytes_reserved -= reservation.reserved_response_bytes
            self._response_bytes += response_bytes

    async def snapshot(self) -> RunBudgetSnapshot:
        async with self._lock:
            return RunBudgetSnapshot(
                requests_started=self._requests_started,
                requests_in_flight=self._requests_in_flight,
                response_bytes=self._response_bytes,
                response_bytes_reserved=self._response_bytes_reserved,
            )
