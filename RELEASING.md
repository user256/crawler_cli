# Releasing crawler-cli

## Versioning

- Version lives in `pyproject.toml` under `[project].version`.
- Follow [Semantic Versioning](https://semver.org/):
  - **MAJOR** — incompatible API or CLI contract changes
  - **MINOR** — backward-compatible features
  - **PATCH** — backward-compatible fixes
- Supported runtimes: **Python 3.11+** on POSIX-like platforms (Linux/macOS).
  CI currently exercises 3.11 and 3.12. Windows is best-effort (native extras
  such as Playwright/Obscura may need extra setup).
- Optional extras (`playwright`, `intent`, `embeddings-local`, `ann`, `test`)
  may bump independently of the base package only when their declared
  dependency floors change; document those floors in the changelog entry.

## Changelog

1. Move notes from `[Unreleased]` in `CHANGELOG.md` into a new
   `## [X.Y.Z] - YYYY-MM-DD` section before tagging.
2. Keep the entry focused on user-visible install/API/CLI changes.

## Packaging policy

- **Wheel**: package code under `src/crawler_cli` only (no tests, tickets, or
  run artifacts).
- **sdist**: source tree plus `tests/`, `README.md`, `LICENSE`, `CHANGELOG.md`,
  `RELEASING.md`, and `pyproject.toml` so downstreams can verify installs.
  Local-only paths (`tickets/`, `runs/`, agent notes) stay out of the sdist.
- There is **no** `[api]` extra. The HTTP API is the separate sibling
  repository `crawler_api` (depends on this package; not distributed here).

## Immutable artifact evidence

A version number or a Git tag alone is not an immutable release record. For
each release, build from the exact reviewed release commit in a clean tree and
attach the resulting wheel and sdist to its GitHub Release. Record all of the
following in the release notes:

- annotated tag name and peeled commit (`git rev-parse vX.Y.Z^{}`);
- the SHA-256 and filename of each uploaded `dist/*` artifact;
- successful `twine check dist/*` output; and
- the CI run URL for that exact commit, including unit, PostgreSQL,
  Playwright, lint, packaging, and extras jobs.

Before upload, inspect the archives as well as their metadata:

```bash
rm -rf dist build *.egg-info
python -m build
twine check dist/*
sha256sum dist/*
python - <<'PY'
from pathlib import Path
from zipfile import ZipFile

wheel = next(Path("dist").glob("*.whl"))
with ZipFile(wheel) as archive:
    names = archive.namelist()
for forbidden in ("tickets/", "runs/", "tests/"):
    assert not any(name.startswith(forbidden) for name in names), forbidden
assert any(name.endswith("METADATA") for name in names)
print(f"wheel contents verified: {wheel}")
PY
tar -tzf dist/*.tar.gz | sort
```

For `v0.2.2`, do not reuse, move, or publish the existing `v0.2.1` tag: it
points to the closed, unmerged PR #50 and is not an ancestor of `master`.
`v0.2.2` is the first safe patch tag for the reviewed hook on `master`.

## Release checklist

1. Update `[project].version` in `pyproject.toml`.
2. Finalize `CHANGELOG.md` for that version.
3. Ensure CI is green on the release commit (unit, integration, Playwright
   smoke, lint, packaging, extras matrix).
4. Build and validate locally:

   ```bash
   python -m pip install build twine
   python -m build
   twine check dist/*
   ```

5. Confirm the intended tag does not already exist, then tag the exact release
   commit: `git tag -a vX.Y.Z -m "crawler-cli X.Y.Z"`.
6. Publish the tag / GitHub Release with the changelog section, immutable
   artifact evidence, and the wheel/sdist as release assets.
7. If publishing to an index: `twine upload dist/*` (internal or PyPI as
   appropriate). Confirm the wheel metadata shows license, requires-python,
   project URLs, and classifiers.
