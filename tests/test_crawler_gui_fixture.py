"""Regression coverage for the static crawler_gui fixture generator."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "crawler_gui" / "generate_sample_data.py"
FIXTURE = ROOT / "crawler_gui" / "sample-data.json"


def test_crawler_gui_fixture_matches_generator_and_schedule_contract() -> None:
    """The checked-in fixture remains generated and keeps the schedule UI usable."""
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    nav = {item["id"]: item for item in data["nav"]}
    assert nav["schedule"]["enabled"] is True
    assert data["configDefaults"] == {
        "maxPages": 200,
        "concurrency": 5,
        "delay": 0.2,
        "respectRobots": True,
        "useJs": False,
        "ignoreNoFollow": False,
        "crawlImages": False,
        "userAgent": "Mozilla/5.0 (compatible; crawler_gui/1.0; +https://example.com/bot)",
        "backend": "aiohttp",
    }
