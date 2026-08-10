"""Run-scoped request and streamed response-body accounting (ticket 3685).

The ledger is deliberately *not* an up-front reservation of
``max_response_bytes``.  That value is commonly the 25 MB safety ceiling and
using it for admission makes a modest ``--max-bytes`` run unable to start at
all.  Instead each connection reserves only the next bounded wire read, then
settles it with the bytes actually returned by the transport.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal


BudgetStopReason = Literal["max_requests", "max_bytes"]


class RunBudgetExhausted(RuntimeError):
    """A run cannot emit/read more work for the supplied budget reason."""

    def __init__(self, reason: BudgetStopReason) -> None:
        self.reason = reason
        super().__init__(f"{reason} exhausted")


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    """One request slot.  Body bytes are leased separately while streaming."""

    reservation_id: int
    # Kept for source compatibility with the foundation PR.  It is always
    # zero: no default response-size reservation is made at request admission.
    reserved_response_bytes: int = 0


@dataclass(frozen=True, slots=True)
class ByteReservation:
    """A bounded wire-read lease belonging to an active request."""

    reservation_id: int
    reserved_bytes: int
    # Leases are tracked by their own identity, not by (request, size): two
    # equal-sized leases on one request must not collapse into one entry.
    lease_id: int = 0


@dataclass(frozen=True, slots=True)
class RunBudgetSnapshot:
    """Read-only terminal accounting suitable for artifacts and diagnostics.

    ``accounted_bytes`` is the value charged to ``max_bytes``: the sum, for
    each response, of the conservative maximum of its wire bytes read and
    decoded bytes emitted.  This avoids double-charging ordinary responses
    while preventing compressed expansion from bypassing a run-wide ceiling.
    """

    requests_started: int
    requests_in_flight: int
    wire_bytes: int
    decoded_bytes: int
    accounted_bytes: int
    bytes_reserved: int
    stop_reason: BudgetStopReason | None

    @property
    def response_bytes(self) -> int:
        """Backward-compatible name for the aggregate charged byte count."""
        return self.accounted_bytes

    @property
    def response_bytes_reserved(self) -> int:
        """Backward-compatible name for outstanding streaming leases."""
        return self.bytes_reserved


class RunBudget:
    """Async-safe admission and streamed accounted-byte budget ledger.

    Request admission consumes a request slot but reserves no speculative body
    capacity.  A backend must obtain a :class:`ByteReservation` immediately
    before every bounded ``read(n)``, constrain both the wire read and decoded
    output to that lease, and settle it even when that read fails.  This makes
    concurrent streamed reads fail closed for both compressed and plain
    responses without treating the per-response ceiling as a reservation.
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
        self._wire_bytes = 0
        self._decoded_bytes = 0
        self._accounted_bytes = 0
        self._bytes_reserved = 0
        self._active_reservations: set[int] = set()
        self._response_bytes: dict[int, tuple[int, int]] = {}
        self._active_byte_leases: dict[int, int] = {}
        self._next_reservation_id = 0
        self._next_lease_id = 0
        self._stop_reason: BudgetStopReason | None = None
        self._lock = asyncio.Lock()

    def _record_response_bytes(self, reservation_id: int, wire_bytes: int, decoded_bytes: int) -> None:
        """Apply one response-local byte delta while callers hold ``_lock``.

        The contract is ``sum(max(response_wire, response_decoded))``, not
        ``max(sum(wire), sum(decoded))``.  Retaining the two dimensions per
        active request is what keeps a wire-heavy response plus a
        decoded-heavy response from being undercounted together.
        """
        old_wire, old_decoded = self._response_bytes[reservation_id]
        before = max(old_wire, old_decoded)
        new_wire = old_wire + wire_bytes
        new_decoded = old_decoded + decoded_bytes
        self._response_bytes[reservation_id] = (new_wire, new_decoded)
        self._wire_bytes += wire_bytes
        self._decoded_bytes += decoded_bytes
        self._accounted_bytes += max(new_wire, new_decoded) - before

    @property
    def enabled(self) -> bool:
        return self.max_requests > 0 or self.max_bytes > 0

    async def reserve(self) -> BudgetReservation:
        """Consume a request slot before a network connection is emitted."""
        async with self._lock:
            if self.max_requests and self._requests_started >= self.max_requests:
                self._stop_reason = self._stop_reason or "max_requests"
                raise RunBudgetExhausted("max_requests")
            self._requests_started += 1
            self._requests_in_flight += 1
            reservation_id = self._next_reservation_id
            self._next_reservation_id += 1
            self._active_reservations.add(reservation_id)
            self._response_bytes[reservation_id] = (0, 0)
            return BudgetReservation(reservation_id)

    async def reserve_bytes(self, reservation: BudgetReservation, wanted: int) -> ByteReservation:
        """Lease up to ``wanted`` bytes for the next wire read.

        A non-zero short lease is valid and tells the caller to perform that
        final bounded read then stop.  A zero lease raises the typed terminal
        exhaustion exception before any further body bytes are pulled.
        """
        if wanted <= 0:
            raise ValueError("wanted must be > 0")
        async with self._lock:
            if reservation.reservation_id not in self._active_reservations:
                raise ValueError("reservation was not active or was already settled")
            allowed = wanted
            if self.max_bytes:
                # Each active lease bounds both dimensions. Reserving from the
                # conservative aggregate keeps a compressed response from
                # racing another response past ``max_bytes`` when its decoded
                # output is larger than the wire read.
                remaining = self.max_bytes - self._accounted_bytes - self._bytes_reserved
                if remaining <= 0:
                    self._stop_reason = self._stop_reason or "max_bytes"
                    raise RunBudgetExhausted("max_bytes")
                allowed = min(wanted, remaining)
            lease_id = self._next_lease_id
            self._next_lease_id += 1
            lease = ByteReservation(reservation.reservation_id, allowed, lease_id)
            self._bytes_reserved += allowed
            self._active_byte_leases[lease_id] = lease.reservation_id
            return lease

    async def settle_bytes(
        self,
        lease: ByteReservation,
        *,
        wire_bytes: int,
        decoded_bytes: int,
    ) -> None:
        """Commit one bounded read and release its accounted-byte lease."""
        if wire_bytes < 0 or decoded_bytes < 0:
            raise ValueError("byte counts must be >= 0")
        if wire_bytes > lease.reserved_bytes:
            raise ValueError("wire_bytes exceeds the streaming lease")
        if decoded_bytes > lease.reserved_bytes:
            raise ValueError("decoded_bytes exceeds the streaming lease")
        async with self._lock:
            if self._active_byte_leases.get(lease.lease_id) != lease.reservation_id:
                raise ValueError("byte lease was not active or was already settled")
            del self._active_byte_leases[lease.lease_id]
            self._bytes_reserved -= lease.reserved_bytes
            self._record_response_bytes(lease.reservation_id, wire_bytes, decoded_bytes)

    async def record_decoded_bytes(self, reservation: BudgetReservation, decoded_bytes: int) -> None:
        """Record decoder-buffer output that has no additional wire read.

        A gzip/deflate stream can emit a final few bytes during ``flush()``
        after its zero-byte EOF read has already settled.  These bytes do not
        consume wire capacity, but they still consume accounted capacity.
        """
        if decoded_bytes < 0:
            raise ValueError("decoded_bytes must be >= 0")
        async with self._lock:
            if reservation.reservation_id not in self._active_reservations:
                raise ValueError("reservation was not active or was already settled")
            old_wire, old_decoded = self._response_bytes[reservation.reservation_id]
            charge = max(old_wire, old_decoded + decoded_bytes) - max(old_wire, old_decoded)
            if self.max_bytes and self._accounted_bytes + charge > self.max_bytes:
                self._stop_reason = self._stop_reason or "max_bytes"
                raise RunBudgetExhausted("max_bytes")
            self._record_response_bytes(reservation.reservation_id, 0, decoded_bytes)

    async def settle(self, reservation: BudgetReservation, response_bytes: int = 0) -> None:
        """Release a request slot after all of its stream leases are settled.

        ``response_bytes`` remains accepted for callers of the groundwork API;
        new backends use :meth:`settle_bytes` so accounting reflects every
        actual stream read.
        """
        if response_bytes < 0:
            raise ValueError("response_bytes must be >= 0")
        async with self._lock:
            if reservation.reservation_id not in self._active_reservations:
                raise ValueError("reservation was not active or was already settled")
            if reservation.reservation_id in self._active_byte_leases.values():
                raise ValueError("all byte leases must be settled before the request")
            self._active_reservations.remove(reservation.reservation_id)
            self._requests_in_flight -= 1
            # Compatibility only: current production callers always account
            # reads through settle_bytes().
            self._record_response_bytes(reservation.reservation_id, response_bytes, response_bytes)
            del self._response_bytes[reservation.reservation_id]

    async def snapshot(self) -> RunBudgetSnapshot:
        async with self._lock:
            return RunBudgetSnapshot(
                requests_started=self._requests_started,
                requests_in_flight=self._requests_in_flight,
                wire_bytes=self._wire_bytes,
                decoded_bytes=self._decoded_bytes,
                accounted_bytes=self._accounted_bytes,
                bytes_reserved=self._bytes_reserved,
                stop_reason=self._stop_reason,
            )
