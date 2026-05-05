from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass(slots=True)
class CircuitBreaker:
    failure_threshold: int
    recovery_timeout_seconds: float
    failure_count: int = 0
    opened_at: float | None = None
    state: CircuitState = CircuitState.CLOSED

    def should_allow(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if self.opened_at is None:
                return False
            if (time.monotonic() - self.opened_at) >= self.recovery_timeout_seconds:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True

    def record_success(self) -> None:
        self.failure_count = 0
        self.opened_at = None
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self.opened_at = time.monotonic()
            self.failure_count = self.failure_threshold
            return
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = time.monotonic()


class CircuitBreakerRegistry:
    def __init__(self, failure_threshold: int, recovery_timeout_seconds: float) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self._circuits: dict[str, CircuitBreaker] = {}

    def for_host(self, host: str) -> CircuitBreaker:
        circuit = self._circuits.get(host)
        if circuit is None:
            circuit = CircuitBreaker(self.failure_threshold, self.recovery_timeout_seconds)
            self._circuits[host] = circuit
        return circuit

