"""Canonical process exit codes for crawler_cli automation (ticket 092).

| Code | Meaning |
|------|---------|
| 0    | Complete success — crawl finished and required persistence succeeded |
| 1    | Partial persistence failure, or total crawl failure |
| 2    | Validation / usage error (bad args, missing config, run selection) |
| 130  | Interrupted by signal (SIGINT/SIGTERM drain) |

Precedence when multiple conditions apply: interruption (130) wins over
persistence failure (1). Validation errors (2) are returned before the crawl
runs. Use ``--allow-persist-failures`` only when callers explicitly accept
best-effort durability (exit 0 despite ``persist_error`` counts).
"""

from __future__ import annotations

from .models import CrawlJobResult

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_VALIDATION = 2
EXIT_INTERRUPTED = 130


def resolve_crawl_exit_code(
    job: CrawlJobResult,
    *,
    allow_persist_failures: bool = False,
) -> int:
    """Map a finished crawl job to a process exit code.

    Interrupted crawls always return ``EXIT_INTERRUPTED`` (130), even when some
    pages also failed to persist — the signal is the primary stop reason.
    Otherwise any required persistence failure yields ``EXIT_FAILURE`` (1)
    unless ``allow_persist_failures`` is set.
    """
    if job.interrupted:
        return EXIT_INTERRUPTED
    if job.persist_error_count and not allow_persist_failures:
        return EXIT_FAILURE
    return EXIT_SUCCESS
