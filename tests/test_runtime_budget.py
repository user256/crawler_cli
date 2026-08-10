"""No-network proof consumed by Portal's worker capability probe."""

from crawler_cli.runtime_budget import enforcement_capabilities


def test_enforcement_capabilities_proves_only_runtime_budget_limits() -> None:
    assert enforcement_capabilities() == {"max_requests": True, "max_bytes": True}
