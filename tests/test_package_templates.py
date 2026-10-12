"""The runtime JSON templates ship inside the package (QA finding on PR #119).

They used to live in a repository-level ``templates/`` directory that the
wheel never contained, so ``GoogleSheetsTemplatePublisher`` raised
``TemplateContractError`` from an installed wheel.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

import crawler_cli
from crawler_cli import package_templates
from crawler_cli.google_sheets import (
    GoogleSheetsTemplatePublisher,
    default_template_contract_path,
    load_template_contract,
)
from crawler_cli.package_templates import TEMPLATE_NAMES, template_resource
from crawler_cli.technical_audit_questions import (
    default_question_registry_path,
    default_site_profile_example_path,
)
from crawler_cli.technical_audit_tickets import default_ticket_language_path, load_ticket_language

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = Path(crawler_cli.__file__).resolve().parent


def test_every_bundled_template_lives_inside_the_package():
    for name in TEMPLATE_NAMES:
        resource = template_resource(name)
        assert resource.is_file(), name
        assert Path(str(resource)).resolve().parent == PACKAGE_DIR / "templates"
        json.loads(resource.read_text(encoding="utf-8"))
    for default in (
        default_template_contract_path(),
        default_question_registry_path(),
        default_site_profile_example_path(),
        default_ticket_language_path(),
    ):
        assert default.resolve().parent == PACKAGE_DIR / "templates"


def test_no_second_repo_level_copy_can_drift():
    # One source of truth: the package copy. A revived repo-level templates/
    # directory would silently diverge from what the wheel ships.
    assert not (ROOT / "templates").exists()


def test_publisher_loads_the_contract_through_importlib_resources(tmp_path, monkeypatch):
    # Point importlib.resources at a fake package root holding only a marked
    # contract: the publisher must read it from there, not from a repo path.
    contract = json.loads(template_resource("google-sheets-template-contract.json").read_text(encoding="utf-8"))
    contract["tickets"]["tab"] = "Tickets (from resources)"
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "google-sheets-template-contract.json").write_text(json.dumps(contract), "utf-8")
    calls: list[str] = []

    def fake_files(package: str) -> Path:
        calls.append(package)
        return tmp_path

    monkeypatch.setattr(package_templates, "files", fake_files)

    publisher = GoogleSheetsTemplatePublisher(drive=None, sheets=None)

    assert calls == ["crawler_cli"]
    assert publisher.contract["tickets"]["tab"] == "Tickets (from resources)"


def test_explicit_paths_still_override_the_bundled_templates(tmp_path):
    contract = load_template_contract()
    contract["tickets"]["tab"] = "Custom Tickets"
    custom = tmp_path / "contract.json"
    custom.write_text(json.dumps(contract), "utf-8")
    assert load_template_contract(custom)["tickets"]["tab"] == "Custom Tickets"

    language = load_ticket_language()
    language["marker"] = "custom"
    custom_language = tmp_path / "language.json"
    custom_language.write_text(json.dumps(language), "utf-8")
    assert load_ticket_language(custom_language)["marker"] == "custom"


def test_package_copied_outside_the_repo_loads_every_template(tmp_path):
    # Simulates an installed layout without building: only the package
    # directory is importable and the working directory is outside the repo.
    site = tmp_path / "site-packages"
    shutil.copytree(PACKAGE_DIR, site / "crawler_cli", ignore=shutil.ignore_patterns("__pycache__", ".mypy_cache"))
    script = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, sys.argv[1])
        from crawler_cli.google_sheets import GoogleSheetsTemplatePublisher
        from crawler_cli.technical_audit_questions import load_question_registry
        from crawler_cli.technical_audit_tickets import load_ticket_language
        import crawler_cli
        assert crawler_cli.__file__.startswith(sys.argv[1]), crawler_cli.__file__
        publisher = GoogleSheetsTemplatePublisher(drive=None, sheets=None)
        load_question_registry()
        load_ticket_language()
        print(publisher.contract["tickets"]["tab"])
        """
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(site)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == load_template_contract()["tickets"]["tab"]


@pytest.mark.slow
@pytest.mark.skipif(
    importlib.util.find_spec("setuptools") is None,
    reason="building the wheel offline needs setuptools in this environment (CI's build job covers it)",
)
def test_built_wheel_contains_every_bundled_template(tmp_path):
    out = tmp_path / "dist"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(out),
            str(ROOT),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    (wheel,) = out.glob("crawler_cli-*.whl")
    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())
        for name in TEMPLATE_NAMES:
            member = f"crawler_cli/templates/{name}"
            assert member in names, member
            assert zf.read(member) == template_resource(name).read_bytes()
