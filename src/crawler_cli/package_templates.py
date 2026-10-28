"""Bundled JSON templates shipped inside the ``crawler_cli`` package.

The audit question registry, ticket language, site-profile example and Google
Sheets template contract live in ``crawler_cli/templates/`` so an installed
wheel finds them; they used to sit in a repository-level ``templates/``
directory that was never packaged.  Callers that accept a custom path keep
reading that path; only the defaults come from here.
"""

from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

TEMPLATE_NAMES = (
    "google-sheets-template-contract.json",
    "site-profile.example.json",
    "technical-audit-questions.json",
    "technical-audit-ticket-language.json",
)


def template_resource(name: str) -> Traversable:
    """Return the bundled template ``name`` as an importlib resource."""
    if name not in TEMPLATE_NAMES:
        raise KeyError(f"unknown bundled template {name!r}")
    return files("crawler_cli").joinpath("templates", name)


def template_path(name: str) -> Path:
    """Filesystem path of a bundled template (installs are unzipped, so this is a real file)."""
    return Path(str(template_resource(name)))


def template_source(path: str | Path | None, name: str) -> Path | Traversable:
    """``path`` as a ``Path`` when given, else the bundled template ``name``.

    Both results support ``read_text(encoding=...)`` and render a readable
    location with ``str()``, so loaders keep one read/error path for both.
    """
    return Path(path) if path else template_resource(name)
