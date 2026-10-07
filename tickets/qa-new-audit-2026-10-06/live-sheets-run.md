# Ticket 420: live Google Sheets publish QA, 2026-10-07

Branch `fix/ticket-420` (based on `fix/ticket-424`). Every write went to scratch
workbooks in a scratch Drive folder created for this run. All of them, and the folder,
were moved to the trash afterwards. The real template
`1T9BRLgaFDZ99Lx3q53Av75eZZM32BIJc0nahVPQpGmU` was only read. Its `Tickets!A1:J40`
and `Config!A1:Z200` formulas were snapshotted before the runs and were identical
afterwards, with tabs `Tickets` (index 0, 5 frozen rows) and `Config` (index 1).
No client workbook was opened.

## Inputs and tokens

- Answers: the saved Rainbet replay inputs from the 2026-10-06 QA
  (`rainbet-audit-merged.json` + `rainbet-obs-tls.json`, crawl run
  `rainbet-20260925-v4`; see [saved-run-replay.json](./saved-run-replay.json)). Each run
  reproduced **104 answers, 9 draft tickets (Issue 1, Needs validation 22, Healthy 1,
  Pending 80)**.
- Tokens found (checked against Google's tokeninfo endpoint after a refresh):

| Token file (`~/.config/google/`) | Granted scopes | Account | Used for |
|---|---|---|---|
| `google-drive-oauth-token.json` | `drive.file`, `spreadsheets` | john@canonicals.co.uk | runs 2, 2c, 3a, 3b, 4 |
| `google-drive-oauth-token.pre-sheets-20260915.json` | `drive.file` only | john@canonicals.co.uk | run 2d / 4b |
| `yoma-docs-oauth-token.json` | `documents`, `drive.file` | a different (Yoma) account | not used |
| `festive-folio-397710-…json` (service account) | any (requested `drive`) | `yoma-drive-docs@…` | not usable: 404 on the template, storage quota 0 |

**No token with the full `drive` scope exists**, and getting one needs an interactive
browser consent, so step 1 was not run (see "What the user must run").

## Scratch IDs (all trashed)

| ID | What |
|---|---|
| `15Gp7M6Nm-6GA7uuKzZDDyY65EL2vr_4d` | scratch folder "crawler_cli ticket-420 live QA scratch 2026-10-07" |
| `1RC3721Iz_4qzFFSgOULzPTWQASSy29XUskMloEjmnYY` | run 2: drive.file publish, before the fix |
| `119aI7G5a6x0FlrLzifGM0ZKphCnEusTVYvz_KO8iyG0` | run 2c: drive.file publish, after the fix |
| `12nyQ6l4EStviSOrHEbCyC4wbXBJsPaO3ani8_WMitYE` | run 3b source: template rebuilt with copyTo, `Tickets!G5` changed to `Severity` |
| `1zWShfUwd3qMX3ItNTr4-LtJI-d-HLRX97CpcbttpHKQ` | run 3b destination: Drive copy of the edited source, left with no writes |

## Outcomes

| # | Check | Result |
|---|---|---|
| 1 | Full `drive` scope publish | **Not run.** No full-drive token. Command below. |
| 2 | `drive.file` + `spreadsheets`: `files.copy` refused → `copyTo` fallback | **Defect found and fixed** (dropdowns lost); everything else passed |
| 2c | Same, after the fix | **Pass** |
| 2d | `drive.file` only | Fails as expected, since the token cannot read the template at all. Before the fix this was a raw `HttpError` traceback with exit 1 (**second defect, fixed**). It now prints a clear error and exits 2. Nothing is created. |
| 3a | Mismatched contract (Priority and Ticket Classification swapped) | **Pass.** `TemplateContractError`, exit 2, "nothing was copied or written"; no file created (folder listing and a name search both empty) |
| 3b | Copy of an edited header (`Severity` in G5) | **Pass.** `TemplateHeaderError` naming the copy and the header found at B5, exit 2. The copy has no writes: 1 revision (creation only), `modifiedTime` = `createdTime`, tabs `Tickets, Config` only (no evidence tabs added), `Tickets!A1:J40` identical to its source, `B6:I` empty |
| 4 | `--check-template` against the real template | **Pass, exit 0.** Header at B5; Ticket Classification (F6) ← `'Config'!B2:B` = Error, Issue, Warning, Improvement; Priority (G6) ← `'Config'!A2:A` = High, Medium, Low; both match the contract |
| 4b | `--check-template` with the `drive.file`-only token | Before the fix: `HttpError` traceback, exit 1. After: clear error, exit 2 |

### Run 2 / 2c detail (`drive.file` + `spreadsheets`)

Command (2c; run 2 was identical apart from the title):

```sh
GOOGLE_DOCS_OAUTH_TOKEN_FILE=~/.config/google/google-drive-oauth-token.json PYTHONPATH=src \
  python -m crawler_cli technical-audit-questions \
  --audit rainbet-audit-merged.json --observations rainbet-obs-tls.json --out answers.json \
  --google-sheets-template 1T9BRLgaFDZ99Lx3q53Av75eZZM32BIJc0nahVPQpGmU \
  --google-sheets-folder 15Gp7M6Nm-6GA7uuKzZDDyY65EL2vr_4d \
  --google-sheets-title "SCRATCH t420 run2c drive.file copyTo fallback after fix (delete me)"
```

- `files.copy` was refused. The token's own `files.get` on the template returns 404 under
  `drive.file`, so the copyTo fallback ran. It took about 80 s for the full Rainbet publish.
- **Rows at `B6:I`:** 9 ticket rows at `Tickets!B6:I14` (Q11, Q15, Q41, Q58, Q94, Q22,
  Q72, Q91, Q63). The prefilled row numbers in column A (`1.`, `2.`…) were kept.
- **B3:** the formula is still `=CONCATENATE("Count of tickets: ",COUNTA(B6:B))` and it shows
  **"Count of tickets: 9"**.
- **B5 header:** intact. `Tickets!A1:J5` is identical to the template, and 5 rows are still frozen.
- **Config untouched:** `Config!A1:Z200` (formulas) is identical to the template.
- **Tab order:** Tickets, Questions, Q13, Q11, Q15, Q41, Q51, Q54, Q58, Q94, Q81, Q22, Q72,
  Q91, Q63, **Config** last. The evidence tabs sit between Tickets and Config as ticket 424 intends.
- **Folder:** `parents` = the scratch folder only. The move under `drive.file` worked.
- **Receipt:** printed, with "15 ranges verified by read-back". These are `'Tickets'!B6:I14` (9 rows),
  `'Questions'!A1:M105` (105), and 13 evidence tabs from 2 to 22,322 rows. No
  `PublishReceiptError`.
- **Dropdowns (run 2, before the fix): lost.** The template has 42 validated cells
  (`F6:G26`, `ONE_OF_RANGE` `=Config!$B$2:$B` / `=Config!$A$2:$A`), but the rebuilt workbook
  had **0**. `sheets.copyTo` drops validation that refers to another tab, so the dropdowns
  were missing rather than unresolved after the `Copy of X` → `X` rename.
- **Dropdowns (run 2c, after the fix): 42 of 42 restored**. They are the same rules, pointing at `Config`.
  `--check-template --google-sheets-template 119aI7G5…` on the published workbook passed for
  both columns, which shows the sources resolve to the Config values after the rename.

## Defects found and fixed (commit `b6d8812`)

1. **The copyTo fallback dropped the Priority / Ticket Classification dropdowns.**
   `_copy_template_tabs` now reads every source tab's `dataValidation` along with its
   properties in one `spreadsheets.get`. It then adds `setDataValidation` requests, one per
   vertical run of identical rules in a column (2 requests for the real template), to the same
   batch, after the placeholder delete and the renames, so `=Config!…` resolves.
   Test: `test_fallback_restores_cross_tab_dropdowns_that_copy_to_drops`.
2. **Google API errors escaped as tracebacks (exit 1).** A token that cannot read the
   template hit this on both publish and `--check-template`. The fallback now raises a `RuntimeError`
   that explains the scope requirement when the Sheets read of the template returns 403 or 404.
   Both CLI paths turn any other `HttpError` (matched by shape) into a one-line error with exit 2.
   Non-API exceptions still propagate. Tests:
   `test_fallback_explains_a_template_the_token_cannot_read`,
   `test_cli_reports_google_api_errors_instead_of_a_traceback`.

Full suite after the fix: `pytest -q -m "not playwright_smoke"` → 2047 passed, 54 skipped,
7 deselected. `ruff check` and `ruff format --check` (0.16.6) are clean.

## Observations (not code defects)

- **The template only validates rows 6–26.** That is 21 rows: `--check-template` notes "79 of 100 rows
  checked have no validation (first: row 27)". A publish with more than 21 tickets puts
  rows 27+ under no dropdown. Rainbet has 9 tickets, so this run was not affected. Extend the
  template's validation to the whole column, or have the publisher extend it, if large
  audits are expected. Not changed here because the template must not be touched.
- **The Drive revision history is coarse but usable.** `revisions.list` works on Sheets files under
  `drive.file` for app-created files. The run 3b copy shows exactly one revision.
- **The run 3b destination was made by the primary `files.copy` path** (the source was app-created, so
  `drive.file` may copy it). That live-checks the primary copy path, the folder `parents` and the
  header check on a Drive copy, but not with a full `drive` token on a template the app did
  not create.

## What the user must run (step 1, full `drive` scope)

1. Create a full-drive token with an interactive browser consent. This writes a new file
   and leaves the existing token alone:

   ```sh
   uv run --with google-auth-oauthlib python \
     ~/resources/skills/google-docs-service-account/scripts/oauth_login.py \
     --client-file ~/.config/google/google-drive-oauth-client.json \
     --token-file ~/.config/google/google-drive-oauth-token.full-drive.json \
     --scopes https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/spreadsheets
   ```

   If the OAuth consent screen does not list the restricted `drive` scope, add it in the
   Cloud console first.

2. Create a scratch folder in Drive and publish into it from the worktree:

   ```sh
   cd ~/worktrees/crawler_cli-t420
   R=/tmp/claude-1000/-home-user256-GitRepos-crawler-cli/ca4a10eb-b3eb-47a4-a694-11cc849028a7/scratchpad
   GOOGLE_DOCS_OAUTH_TOKEN_FILE=~/.config/google/google-drive-oauth-token.full-drive.json PYTHONPATH=src \
     ~/GitRepos/crawler_cli/.venv/bin/python -m crawler_cli technical-audit-questions \
     --audit $R/rainbet-audit-merged.json --observations $R/rainbet-obs-tls.json \
     --out /tmp/t420-full-drive-answers.json \
     --google-sheets-template 1T9BRLgaFDZ99Lx3q53Av75eZZM32BIJc0nahVPQpGmU \
     --google-sheets-folder <SCRATCH_FOLDER_ID> \
     --google-sheets-title "SCRATCH t420 full drive (delete me)"
   ```

   Expect the receipt with `'Tickets'!B6:I14: 9 rows`, then check B3 reads "Count of tickets: 9",
   the B5 header, Config, the tab order and that `--check-template --google-sheets-template <new id>`
   passes. A `files.copy` copy should keep the dropdowns natively. Trash the workbook and folder afterwards.
   If the `/tmp` replay inputs have been cleaned, any saved Rainbet `technical-audit` JSON
   works as `--audit`. The inputs used here are listed in [saved-run-replay.json](./saved-run-replay.json).
