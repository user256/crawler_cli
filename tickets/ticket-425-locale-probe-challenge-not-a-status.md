# Ticket 425: Treat a bot challenge as unanswered in the Accept-Language probe

## Problem

The live QA run for ticket 419 (D1 in
[live-probe-run.md](./qa-new-audit-2026-10-06/live-probe-run.md)) found that a
Cloudflare challenge is recorded as a real, answered HTTP status. Every
`rainbet.com/` variant was challenged: the persisted hop has `status: 429,
skip_reason: "bot_challenge"`, but `accept_language_audit._probe` only treated
`status == 0` as unanswered, so the probe's outcome was `resolved`. The adapter
then carried `variant_status: 429`, `variant_outcome: resolved` and
`variant_failure: null`.

On the live run both sides were challenged, so nothing was compared by luck.
When the baseline is answered (200) and a later variant is challenged, Q25
reports `status 200->429` as a language-driven change with a ticket. This is
the ticket 412 defect class again, through a non-zero status.

## Evidence

- Session `22eb6b2f-…` in `t419_rainbet_qa_crawler`, table
  `language_probe_records`.
- Offline repro from the live evidence:
  `/home/user256/worktrees/crawler_cli-t419/runs/t419-live/d1/repro_d1.py`
  sets only the header-less probes to an answered 200 and runs the real
  adapter and answerer. Result: `es-ES: baseline_status 200, variant_status
  429, variant_outcome resolved, variant_failure None`; Q25 **Yes,
  ticket=true** with `status 200->429` findings. It is Needs validation there
  only because the run's Q26/Q81 gates fail; with passing gates it is Issue.

## Tasks and acceptance criteria

- [ ] A hop that is a challenge (engine `skip_reason: bot_challenge`, a
      `cf-mitigated: challenge` header, or a challenge page on 403/429/503
      when engine detection is off), whatever its status code, gets its own
      unanswered outcome (`challenged` / `redirect_target_challenged`). It is
      neither `resolved` nor a bot trap.
- [ ] The adapter gives such a side a null status and a `*_failure` naming the
      outcome and reason; Q25 counts the comparison as untested and names the
      reason in its note.
- [ ] Decide plain 429/503 without challenge markers.
- [ ] Saved bundles from before the fix (challenged hop labelled `resolved`,
      or an adapted record with `variant_status: 429`) are read the same way.
- [ ] Regression test from the live evidence shape; a real language redirect
      whose target was challenged keeps its first-hop finding.

## Status

proposed (Priority: **P1**). Filed 2026-10-07 from the ticket 419 live QA (D1).
Related: 412, 413, 419, 426, 427.
