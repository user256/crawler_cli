# Ticket 098: Align packaging metadata, extras, and README with the shipped product

## Goal
Make installation instructions and distribution metadata accurate enough for a
reliable internal or public release.

## Background
The package builds successfully, but release/docs hygiene has visible gaps:

- README advertises `pip install -e ".[api]"`, while `pyproject.toml` defines no
  `api` extra and says the HTTP API is a separate repository.
- The documented 200-page default disagrees with runtime (addressed by ticket 090).
- Project metadata omits README declaration, license, authors/maintainers,
  project URLs, classifiers, and a release/versioning policy.
- Browser CI/install expectations are unclear (ticket 097).
- The source distribution includes the full test tree without an explicit
  packaging policy.

## Tasks
- Remove the nonexistent `[api]` instruction or define a justified extra; link
  clearly to the separate `crawler_api` repository.
- Declare `readme`, license, maintainers/authors, project URLs, classifiers, and
  supported Python/platform policy in `pyproject.toml`.
- Add/choose a repository license before public distribution.
- Document extras as a small install matrix (`base`, `playwright`, `intent`,
  `embeddings-local`, `ann`, `test`) and verify each in clean-environment CI.
- Define versioning/changelog/release steps and add metadata validation
  (`build` + `twine check` or equivalent).
- Reconcile README package layout and defaults after tickets 090/097.

## Definition of Done
- Every documented install command resolves to a real, CI-tested extra.
- Wheel/sdist metadata identifies the project, license, documentation, source,
  and supported runtimes accurately.
- A clean build and metadata check are CI-green.

## Status
done (2026-07-15) (Priority: **P3**) — MIT LICENSE; pyproject metadata (readme/license/authors/URLs/classifiers); README install matrix without `[api]`; CHANGELOG + RELEASING; MANIFEST.in sdist policy; CI `packaging` + `extras` jobs (`build`/`twine check`, clean-env extras; embeddings-local resolve-only).

