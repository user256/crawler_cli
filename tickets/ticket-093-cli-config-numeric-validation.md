# Ticket 093: Validate CLI and library numeric configuration at the boundary

## Goal
Reject invalid concurrency, timeout, size, retry, memory, and threshold values
with clear errors before constructing the engine or opening resources.

## Background
Argparse currently accepts negative values for `--max-workers`, `--max-pages`,
`--timeout`, and related controls. A reproduction with `--max-workers=-2`
reached `asyncio.Semaphore` and emitted a raw traceback (`Semaphore initial
value must be >= 0`) instead of a CLI usage error. Other invalid combinations
can disable limits accidentally or produce nonsensical runtime behavior.

## Tasks
- Add reusable argparse types/validators for positive int, non-negative int,
  positive float, percentage, probability, and bounded thresholds.
- Validate cross-field constraints: memory recovery below high watermark,
  positive response cap, non-negative retries/delays, and valid ANN/overlap
  thresholds.
- Add `CrawlConfig.validate()` or `__post_init__` validation so library callers
  receive the same guarantees as CLI users.
- Convert validation failures into concise exit-code-2 messages without
  tracebacks or partially-created output directories.
- Cover boundary values, zero-as-explicit-sentinel fields, negative values, NaN,
  infinity, and conflicting aliases.

## Definition of Done
- Invalid numeric configuration is rejected before engine/resource creation.
- CLI and direct-library validation rules are consistent and comprehensively tested.

## Status
done (Priority: **P2**) — `agent/ticket-093-cli-config-numeric-validation`; argparse type validators + `CrawlConfig.validate()`/`__post_init__`; cross-field memory watermark + alias checks; intent-overlap thresholds validated before store/output; exit code 2 without traceback.

