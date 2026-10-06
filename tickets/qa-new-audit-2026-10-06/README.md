# New technical audit — post-merge QA, 2026-10-06

**The regression suite passes, but the new audit is not ready for an unconditional correctness sign-off.** Seven functional defects and one formatting-gate failure are filed as tickets **410–417**. Five functional findings are P1. Existing gaps remain in the original question tickets.

Reviewed **merged PR #118**, master `72629af137e0803aface1f4ce94a9a18ba7f0eb1`, in the isolated `qa/new-tech-audit-20261006` branch. The original workspace's older `feature/technical-audit-183` checkout was left untouched. Product code was not changed; this delivery files fixes, evidence and acceptance criteria.

## Verification

| Check | Result |
|---|---|
| Full suite, no ignored files | **1,866 passed, 60 skipped**, 6 deprecation warnings, 66.73 s |
| `ruff check src tests`, pinned 0.16.6 | Pass |
| `ruff format --check src tests`, pinned 0.16.6 | **Fail**, three files; ticket 417 |
| Saved Rainbet audit + saved TLS observations | **1 Issue / 22 Needs validation / 1 Healthy / 80 Pending**; all 104 answer/status/count/denominator/ticket summaries match the saved merged output |
| Question/ticket mapping | All Q1–Q104 mapped to their individual tickets |
| Runtime answerer registration | **63 registered, 40 missing, 1 manual/external (Q104)** |
| Additional adversarial checks | Seven functional failures reproduced; existing 393 and 406 gaps reconfirmed |

The 104-row output is not 104 implemented checks. Registered answerers also include partial rules and questions that need a collection the CLI does not yet produce. The [question matrix](./question-matrix.md) distinguishes registration from availability and lists textual test references; it does not assert full acceptance coverage from a test mentioning a question ID.

The saved-run replay used `rainbet-20260925-v4`, no site profile, and `rainbet-obs-tls.json`. It did not recollect the database or refetch the site. The input paths, counts and comparison outcome are in [saved-run-replay.json](./saved-run-replay.json); large client artifacts were not copied into the repository.

## New fix tickets

| Ticket | Priority | Reproduced defect |
|---|---|---|
| [410](../ticket-410-ai-governance-unread-robots-bundle.md) | P1 | Failed robots fetch aborts the entire observation bundle instead of retaining unknown evidence. |
| [411](../ticket-411-ai-governance-capped-coverage.md) | P1 | Two eligible hosts, cap one: coverage is complete and Q96 reports Healthy. |
| [412](../ticket-412-locale-probe-failed-fetch-verdict.md) | P1 | A language-variant fetch error becomes Q25 Issue and an automatic ticket (`200->0`). |
| [413](../ticket-413-locale-probe-primary-content.md) | P1 | Changing only a head script's locale produces a confirmed “primary content differs” defect. |
| [414](../ticket-414-tls-final-response-identity.md) | P1 | Stored final-response HSTS headers are attributed to the requested host after redirects. |
| [415](../ticket-415-q63-shared-hsts-parser.md) | P2 | Q63's second HSTS parser flags valid whitespace and accepts invalid duplicate max-age as Healthy. |
| [416](../ticket-416-question-ticket-denominator-units.md) | P2 | Draft tickets call every denominator “pages”, including host and policy populations. |
| [417](../ticket-417-postmerge-format-gate.md) | P2 | The pinned CI format gate fails on archive.py and two test files. |

Fix 410–414 before relying on the reattached probes for client conclusions. Each ticket describes the mechanism, reproduction and expected regression coverage. Filing is not implementation.

## Existing gaps retained under their original tickets

- **393 / Q39:** an empty heading-link population still reports Healthy using parsed pages as its denominator. Reconfirmed in the reproduction output; already filed, so no duplicate ticket.
- **406 / publisher:** an absent Tickets header still defaults to A2 and clears A2:H10000 in the copied workbook. The existing ticket now includes the current implementation and explicit fail-before-write criteria. Source template contents are not changed.
- **394:** question-specific ticket language remains open. **395:** true homepage BFS remains a documented follow-up. **399:** smaller integration gaps remain open; this review does not mark them fixed.
- **409 / missing producers:** the replacement intentionally removed the former probe implementations. Registered answerers for external-link rechecks, utility paths, mobile renders and render traces still require supplied evidence or new producers. `compare-renders` does not supply Q46 footer data. These remain within the existing question/producer follow-ups, not new duplicate bug tickets.
- **344, 362, 370:** status prose predates the reattached adapters. Q25 and Q63 now have partial producer paths; Q96 now has a live path. That does not close their full acceptance criteria, and 410–415 identify defects in those paths.
- **400 and 408:** their original control-contract integration plans predate the chosen replacement architecture. Do not treat their old checkbox state as the current implementation inventory. The matrix and ticket 409 describe the merged architecture.

The queue and ticket 409 now record PR #118 as merged and preserve its outstanding producer work.

## Reproduction and limits

From this worktree, with the project environment activated:

```sh
python -m pytest -q
ruff check src tests
ruff format --check src tests
PYTHONPATH=src python tickets/qa-new-audit-2026-10-06/reproduce.py
```

[reproduce.py](./reproduce.py) exercises production command orchestration, the Accept-Language collector, adapters and answerers with deterministic I/O fixtures. It prints the observed failures; it is a diagnostic, not a passing regression test for desired behavior. [results.json](./results.json) records the output. Ticket 414 combines inspected production SQL with a response-identity projection fixture. Ticket 406 uses a fake Sheets service and makes no external writes.

The existing suite includes a real-engine loopback Accept-Language test. This QA did **not** run a fresh public-site `--ai-governance`/`--probe-accept-language` audit, a fresh PostgreSQL integration round-trip, or a live Sheets publication. Those paths are not certified by the green baseline. The 60 existing skips remain skips. Full individual-rule acceptance for every registered answerer was not established; coverage here is the complete ticket/registry inventory, the existing full suite, saved-run replay and targeted adversarial integration checks.
