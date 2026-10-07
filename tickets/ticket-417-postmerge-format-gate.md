# Ticket 417: Restore the pinned formatting gate after PR #118

## Problem and evidence

On merged master `72629af`, `ruff check src tests` passes but the separate CI
command `ruff format --check src/ tests/` fails with the pinned Ruff 0.16.6:

- `src/crawler_cli/archive.py`
- `tests/test_crawler_gui_server.py`
- `tests/test_tech_audit_tickets_skill.py`

The workflow in `.github/workflows/ci.yml` requires the format check. This is
an observed integrated-tree failure, not a claim that the audit replacement
introduced every formatting change. No functional defect is implied.

## Acceptance criteria

- [x] Apply the pinned formatter only to the three named files.
- [x] `ruff check src tests` and `ruff format --check src tests` both pass.
- [x] Keep the formatting-only change separate from functional fixes.

## Status

done (Priority: **P2**). Post-merge QA, 2026-10-06.

Fixed on `fix/postmerge-qa-misc`: ran pinned Ruff 0.16.6 `ruff format` on only the three named
files, in a formatting-only commit. `ruff check src tests` and `ruff format --check src tests` pass.
