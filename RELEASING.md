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

5. Tag the release: `git tag -a vX.Y.Z -m "crawler-cli X.Y.Z"`.
6. Publish the tag / GitHub Release with the changelog section as notes.
7. If publishing to an index: `twine upload dist/*` (internal or PyPI as
   appropriate). Confirm the wheel metadata shows license, requires-python,
   project URLs, and classifiers.
