# Ticket 419: Live public-site QA of the reattached probes

## Problem

Tickets 410–413 fixed the `--ai-governance` and `--probe-accept-language`
probes with deterministic fixtures, loopback engines and saved bundles. No
fresh run against a public site has exercised the fixed paths end to end
(`technical-audit-observations` → bundle → `technical-audit-questions`), so
Q25 and Q96 are not yet certified on live evidence.

## Tasks and acceptance criteria

- [x] Run `technical-audit-observations --ai-governance --probe-accept-language`
      (plus `--tls-probe`) against one site with several locales and at
      least two eligible hosts, once uncapped and once with a cap below the
      host count.
- [x] Confirm in the bundle: every eligible host is present, unread hosts carry
      `fetch_outcome: unknown` with a reason, the capped run records
      `coverage_state: partial` with the omitted hosts, and other collections
      survive a failed robots fetch.
- [ ] Confirm Accept-Language records: a timed-out or refused variant is
      `fetch_failed` / `not_admitted` and untested; `primary_content_differs`
      is set only from the `<main>`/`<body>` hash with a matching repeat.
- [x] Run `technical-audit-questions --observations` on the bundle; Q25 and
      Q96 must be Needs validation or Pending wherever evidence is incomplete,
      and any Issue must be reproducible by hand (curl with/without header).
- [x] Record the commands, site, counts and verdicts under
      `tickets/qa-new-audit-2026-10-06/live-probe-run.md`; redact nothing
      that is needed to replay, but copy no large client artifacts in.

## Status

partial (Priority: **P1**). Filed 2026-10-07 from the post-merge QA
follow-up; the fixes themselves are in PR #119. Related: 344, 362, 370, 409,
410–413.

QA run on 2026-10-07 against rainbet.com (hosts `rainbet.com` and
`www.rainbet.com`, 9 locales) at `c6073c3`; record in
[live-probe-run.md](./qa-new-audit-2026-10-06/live-probe-run.md). The 410 and
411 paths held live (unread host kept as `unknown` with a reason, capped run
`partial` with the omitted host, other collections written, Q96 Needs
validation in both runs). Q25 stayed Needs validation and its one finding
(www host 308->307 to `/es` etc. on Accept-Language) reproduces with curl.

Left open (the Accept-Language box stays unticked):

- **D1 (P1):** a Cloudflare challenge (HTTP 429, hop `skip_reason:
  bot_challenge`) is recorded as a resolved status, so a challenged variant
  against an answered baseline yields `status 200->429` as a Q25 finding
  (reproduced offline from the live evidence).
- **D2 (P2):** the locale-probe collection claims `complete` while 21 of 28
  comparisons were never answered.
- **D3 (P2):** the probe engine has no UA/backend/impersonation/delay options,
  so it was challenged before reading any 200 page on the apex; the
  primary-content (413) path and the `fetch_failed` label have no live
  evidence yet.

Re-run this QA after D1 and D3 are fixed.
