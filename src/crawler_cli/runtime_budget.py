"""Implementation-owned proof for Portal runtime-budget dispatch.

This intentionally has no configuration or network side effects.  The Portal
worker probes it before enabling ``--max-requests``/``--max-bytes`` and treats
anything other than literal ``True`` as unsupported.
"""

from __future__ import annotations


def enforcement_capabilities() -> dict[str, bool]:
    """Declare the budget limits enforced at the guarded I/O boundary.

    ``max_requests`` is consumed by :class:`crawler_cli.budget.RunBudget`
    immediately before every policy-authorized aiohttp connection.  The same
    ledger leases every guarded body read and constrains decoder output, so
    ``max_bytes`` is enforced as the sum of
    ``max(response_wire_bytes, response_decoded_bytes)`` even for gzip/deflate
    responses. This function is deliberately narrow: it makes no claim about
    backends or paths which ``CrawlConfig`` rejects for a budgeted Portal run.
    """
    return {"max_requests": True, "max_bytes": True}
