"""Reusable argparse types and numeric config checks (ticket 093).

Argparse ``type=`` callables raise :class:`argparse.ArgumentTypeError` so the
CLI exits with code 2 and a concise usage message (no traceback). Library
callers use the same rules via :meth:`crawler_cli.config.CrawlConfig.validate`.
"""

from __future__ import annotations

import argparse
import math
from typing import Callable


def _parse_int(value: str, *, label: str) -> int:
    try:
        # Reject bool-like and floats: int("1.5") fails; int(True) is not reached
        # because argparse always passes str.
        return int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"{label} must be an integer, got {value!r}") from exc


def _parse_finite_float(value: str, *, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"{label} must be a number, got {value!r}") from exc
    if not math.isfinite(parsed):
        raise argparse.ArgumentTypeError(f"{label} must be finite, got {value!r}")
    return parsed


def positive_int(value: str) -> int:
    """Parse an integer ``> 0`` (concurrency, batch sizes, ANN k, …)."""
    parsed = _parse_int(value, label="value")
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer (> 0), got {value!r}")
    return parsed


def non_negative_int(value: str) -> int:
    """Parse an integer ``>= 0`` (0 often means unlimited / disabled)."""
    parsed = _parse_int(value, label="value")
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"must be a non-negative integer (>= 0), got {value!r}")
    return parsed


def positive_float(value: str) -> float:
    """Parse a finite float ``> 0`` (timeouts, recovery delays, …)."""
    parsed = _parse_finite_float(value, label="value")
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive number (> 0), got {value!r}")
    return parsed


def non_negative_float(value: str) -> float:
    """Parse a finite float ``>= 0`` (0 often disables a delay / rate limit)."""
    parsed = _parse_finite_float(value, label="value")
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"must be a non-negative number (>= 0), got {value!r}")
    return parsed


def percentage(value: str) -> float:
    """Parse a finite percentage in ``[0, 100]`` (memory watermarks)."""
    parsed = _parse_finite_float(value, label="percentage")
    if parsed < 0.0 or parsed > 100.0:
        raise argparse.ArgumentTypeError(f"must be a percentage in [0, 100], got {value!r}")
    return parsed


def probability(value: str) -> float:
    """Parse a finite probability / similarity score in ``[0, 1]``."""
    parsed = _parse_finite_float(value, label="probability")
    if parsed < 0.0 or parsed > 1.0:
        raise argparse.ArgumentTypeError(f"must be a probability in [0, 1], got {value!r}")
    return parsed


def bounded_float(low: float, high: float, *, label: str = "value") -> Callable[[str], float]:
    """Return an argparse type for a finite float in ``[low, high]``."""

    def _parser(value: str) -> float:
        parsed = _parse_finite_float(value, label=label)
        if parsed < low or parsed > high:
            raise argparse.ArgumentTypeError(f"must be in [{low}, {high}], got {value!r}")
        return parsed

    _parser.__name__ = f"bounded_float_{low}_{high}"
    return _parser


def require_finite_number(value: float, *, field: str) -> float:
    """Library-side check: reject NaN / ±inf with a :class:`ValueError`."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field} must be a number, got {value!r}")
    as_float = float(value)
    if not math.isfinite(as_float):
        raise ValueError(f"{field} must be finite, got {value!r}")
    return as_float


def require_positive_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer, got {value!r}")
    if value <= 0:
        raise ValueError(f"{field} must be a positive integer (> 0), got {value}")
    return value


def require_non_negative_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer, got {value!r}")
    if value < 0:
        raise ValueError(f"{field} must be a non-negative integer (>= 0), got {value}")
    return value


def require_positive_float(value: float, *, field: str) -> float:
    as_float = require_finite_number(value, field=field)
    if as_float <= 0:
        raise ValueError(f"{field} must be a positive number (> 0), got {value}")
    return as_float


def require_non_negative_float(value: float, *, field: str) -> float:
    as_float = require_finite_number(value, field=field)
    if as_float < 0:
        raise ValueError(f"{field} must be a non-negative number (>= 0), got {value}")
    return as_float


def require_percentage(value: float, *, field: str) -> float:
    as_float = require_finite_number(value, field=field)
    if as_float < 0.0 or as_float > 100.0:
        raise ValueError(f"{field} must be a percentage in [0, 100], got {value}")
    return as_float


def require_probability(value: float, *, field: str) -> float:
    as_float = require_finite_number(value, field=field)
    if as_float < 0.0 or as_float > 1.0:
        raise ValueError(f"{field} must be a probability in [0, 1], got {value}")
    return as_float
