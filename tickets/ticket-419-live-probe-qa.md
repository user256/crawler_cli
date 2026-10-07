# Ticket 419: Live public-site QA of the reattached probes

## Problem

Tickets 410–413 fixed the `--ai-governance` and `--probe-accept-language`
probes with deterministic fixtures, loopback engines and saved bundles. No
fresh run against a public site has exercised the fixed paths end to end
(`technical-audit-observations` → bundle → `technical-audit-questions`), so
Q25 and Q96 are not yet certified on live evidence.

## Tasks and acceptance criteria

- [ ] Run `technical-audit-observations --ai-governance --probe-accept-language`
      (plus `--tls-probe`) against one site with several locales and at
      least two eligible hosts, once uncapped and once with a cap below the
      host count.
- [ ] Confirm in the bundle: every eligible host is present, unread hosts carry
      `fetch_outcome: unknown` with a reason, the capped run records
      `coverage_state: partial` with the omitted hosts, and other collections
      survive a failed robots fetch.
- [ ] Confirm Accept-Language records: a timed-out or refused variant is
      `fetch_failed` / `not_admitted` and untested; `primary_content_differs`
      is set only from the `<main>`/`<body>` hash with a matching repeat.
- [ ] Run `technical-audit-questions --observations` on the bundle; Q25 and
      Q96 must be Needs validation or Pending wherever evidence is incomplete,
      and any Issue must be reproducible by hand (curl with/without header).
- [ ] Record the commands, site, counts and verdicts under
      `tickets/qa-new-audit-2026-10-06/live-probe-run.md`; redact nothing
      that is needed to replay, but copy no large client artifacts in.

## Status

proposed (Priority: **P1**). Filed 2026-10-07 from the post-merge QA
follow-up; the fixes themselves are in PR #119. Related: 344, 362, 370, 409,
410–413.
