"""Canonical process exit codes for crawler_cli automation (tickets 092, 3344).

| Code | Meaning |
|------|---------|
| 0    | Complete success — crawl finished and required persistence succeeded |
| 1    | Persistence or frontier-bookkeeping incompleteness, or total crawl failure |
| 2    | Validation / usage error (bad args, missing config, run selection) |
| 3    | Findings gate tripped — the run itself succeeded, but ``--fail-on`` matched (``compare-urls``, ``intent-overlap``) |
| 130  | Interrupted by signal (SIGINT/SIGTERM drain) |

Precedence when multiple conditions apply: interruption (130) wins over
persistence or frontier-bookkeeping incompleteness (1). Validation errors (2)
are returned before the crawl runs. Findings (3) are only reported after a run
that completed cleanly — a validation error or crawl failure always takes
precedence, so automation can distinguish "the tool could not do its job"
(1/2) from "the job ran and the data failed the gate" (3). Use
``--allow-persist-failures`` only when callers explicitly accept best-effort
durability (exit 0 despite ``persist_error`` counts); it does not hide failed
frontier completion.
"""

from __future__ import annotations

from .models import CrawlJobResult

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_VALIDATION = 2
EXIT_FINDINGS = 3
EXIT_INTERRUPTED = 130


def resolve_crawl_exit_code(
    job: CrawlJobResult,
    *,
    allow_persist_failures: bool = False,
) -> int:
    """Map a finished crawl job to a process exit code.

    Interrupted crawls always return ``EXIT_INTERRUPTED`` (130), even when some
    pages also failed to persist — the signal is the primary stop reason.
    Otherwise failed frontier completion always yields ``EXIT_FAILURE`` (1),
    because the affected URLs remain pending for ``--resume``. Required
    persistence failures also yield ``EXIT_FAILURE`` unless
    ``allow_persist_failures`` is set.
    """
    if job.interrupted:
        return EXIT_INTERRUPTED
    if job.frontier_mark_done_error_count:
        return EXIT_FAILURE
    if job.persist_error_count and not allow_persist_failures:
        return EXIT_FAILURE
    return EXIT_SUCCESS
