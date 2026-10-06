# Ticket 240: Make the Audit Controls and Manual Review tabs publish and resume correctly

## Goal

`GoogleSheetsTicketRegisterPublisher` must write, verify and resume the two
audit-owned tabs against the real Google Sheets API, not only against the test
fake.

## Background

Review of commit 6496fba (`feat(audit): surface manual review controls`)
found three defects in `_write_audit_register_tabs` and the resume path in
`src/crawler_cli/google_sheets.py`:

1. Readback uses range `'<Tab>'!A1`. For `values.get` that range is one
   cell, so the real API returns `[["Control"]]` and the comparison always
   fails. The fake in `tests/test_technical_audit_tickets.py` returns the whole
   written block for the range key and hides the bug.
2. Written values include `None` (`tested_count`, `denominator` for
   unavailable controls). Sheets skips nulls on write and reads blanks back as
   `""` or omits trailing empty cells, so equality fails even with a correct
   range. Rows ending in an empty Qualification also lose that trailing cell.
3. Resume: after a failure inside the tab step the receipt stays `writing`.
   On `resume=True` the ticket-row check matches, the receipt is marked
   `verified` and the audit tabs are never written or verified. The tabs are
   also never cleared, so a shorter rerun leaves stale rows.

## Tasks

- Write and read back an explicit bounded range (`A1:<lastcol><n>`).
- Normalise cells before writing (`None` -> `""`) and normalise readback
  (pad rows to header width, treat missing trailing cells as `""`) before
  comparing.
- Clear each audit tab's data range before writing.
- On resume from `writing`, do not mark `verified` until both audit tabs have
  been (re)written and verified; the ticket-row short-circuit must not skip
  them.
- Make the test fake behave like the API: `values.get` returns only the
  requested range, trims trailing empty cells, and returns blanks for nulls.

## Definition of Done

- A test with the realistic fake fails on the old code and passes on the new.
- A test covers resume from `writing` after a tab failure and asserts both
  tabs are written and verified before the receipt reaches `verified`.
- A test covers a rerun with fewer rows leaving no stale rows.
- Scope: `src/crawler_cli/google_sheets.py`, `tests/test_technical_audit_tickets.py`,
  `tests/test_google_sheets.py` only.
