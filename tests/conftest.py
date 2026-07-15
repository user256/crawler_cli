from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-playwright-smoke",
        action="store_true",
        default=False,
        help="Run real Chromium-backed Playwright smoke tests.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-playwright-smoke"):
        return
    skip_playwright_smoke = pytest.mark.skip(
        reason="need --run-playwright-smoke to run real Chromium-backed Playwright smoke tests"
    )
    for item in items:
        if "playwright_smoke" in item.keywords:
            item.add_marker(skip_playwright_smoke)


# Postgres connection env vars that _build_dsn / _postgres_config_supplied read.
# A developer shell that exports these (e.g. CRAWLER_CLI_POSTGRES_DSN pointing at a
# local crawler DB) otherwise leaks into tests that assert the "no Postgres
# configured" default, silently flipping MemoryStore -> AsyncpgStore. Note: the
# integration suite's CRAWLER_CLI_TEST_DSN is deliberately NOT in this set.
_POSTGRES_ENV_VARS = tuple(
    f"{prefix}_{key}"
    for prefix in ("CRAWLER_CLI", "PostgreSQLCrawler")
    for key in (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_DSN",
    )
)


@pytest.fixture(autouse=True)
def _clear_postgres_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test from ambient Postgres DSN env vars in the dev shell.

    Runs during setup, before the test body, so tests that intentionally set one
    of these via their own monkeypatch.setenv still see exactly what they set.
    """
    for var in _POSTGRES_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
