import time

from crawler_cli.circuit_breaker import CircuitBreaker, CircuitState


def test_circuit_breaker_opens_and_transitions_half_open():
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=0.01)
    assert breaker.should_allow() is True

    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    assert breaker.should_allow() is False

    time.sleep(0.02)
    assert breaker.should_allow() is True
    assert breaker.state == CircuitState.HALF_OPEN

    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED

