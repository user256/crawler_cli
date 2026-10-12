"""Resolve the database a PostgreSQL DSN selects, exactly as asyncpg does.

asyncpg (0.32, ``connect_utils._parse_connect_dsn_and_args``) picks the
database in this order: any non-empty URL path (even ``/``), percent-decoded;
then the ``dbname`` / ``database`` query parameters (last value wins); then a
``dbname`` from a connection service file; then ``PGDATABASE``; then the user
name. A path therefore beats a query parameter, so
``postgresql://h/crawler?dbname=crawler_cli_test_x`` connects to ``crawler``.

Callers that confirm, truncate or drop a database need the name asyncpg will
actually use, and must not guess. :func:`resolve_dsn_database` returns that
name and raises :class:`AmbiguousDatabaseError` wherever the answer is unclear
or comes from outside the DSN in a way an operator could miss. It never
defaults to ``postgres``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import parse_qsl, unquote, urlparse

DSN_SCHEMES = frozenset({"postgresql", "postgres"})
DSN_DATABASE_PARAMS = ("dbname", "database")


class AmbiguousDatabaseError(ValueError):
    """The DSN's effective database cannot be determined unambiguously."""


def resolve_dsn_database(dsn: str, *, environ: Mapping[str, str] | None = None) -> str:
    """Return the database asyncpg connects to for ``dsn`` (passed alone).

    Raises :class:`AmbiguousDatabaseError` for:

    * a non-URL DSN (libpq ``key=value`` form), which asyncpg cannot use;
    * a malformed query string;
    * ``dbname`` / ``database`` given more than once in the query;
    * a path and a query parameter that name different databases;
    * no database in the DSN when a connection service could supply one;
    * no database in the DSN and no ``PGDATABASE`` (asyncpg would use the
      user name);
    * an empty name (``postgresql://h/``; the server would pick the user name).
    """
    env = os.environ if environ is None else environ
    # urlparse, not urlsplit: asyncpg uses urlparse, which also strips ;params
    # from the last path segment.
    parsed = urlparse(dsn)
    if parsed.scheme not in DSN_SCHEMES:
        raise AmbiguousDatabaseError(
            "DSN must be a postgresql:// or postgres:// URL (asyncpg does not accept the libpq key=value form)"
        )
    try:
        query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True) if parsed.query else []
    except ValueError as exc:
        raise AmbiguousDatabaseError(f"DSN has a malformed query string ({exc})") from None
    query_names = [(key, value) for key, value in query if key in DSN_DATABASE_PARAMS]
    if len(query_names) > 1:
        raise AmbiguousDatabaseError(
            "DSN names the database more than once in its query string ("
            + ", ".join(f"{key}={value!r}" for key, value in query_names)
            + ")"
        )
    query_name = query_names[0][1] if query_names else None

    if parsed.path:
        # asyncpg: any non-empty path (even "/") is the database, decoded.
        path_name = unquote(parsed.path[1:] if parsed.path.startswith("/") else parsed.path)
        if query_name is not None and query_name != path_name:
            raise AmbiguousDatabaseError(
                f"DSN names database {path_name!r} in its path but {query_names[0][0]}={query_name!r} in its "
                "query string; asyncpg connects to the path's database"
            )
        name = path_name
    elif query_name is not None:
        name = query_name
    else:
        if any(key == "service" for key, _ in query) or env.get("PGSERVICE"):
            raise AmbiguousDatabaseError("DSN names no database and a connection service file could supply one")
        env_name = env.get("PGDATABASE")
        if env_name is None:
            raise AmbiguousDatabaseError("DSN names no database, so asyncpg would fall back to the user name")
        name = env_name
    if not name:
        raise AmbiguousDatabaseError("DSN names an empty database, so the server would pick the user name")
    return name
