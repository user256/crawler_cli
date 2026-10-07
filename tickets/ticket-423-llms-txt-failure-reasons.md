# Ticket 423: Record why an /llms.txt fetch failed in AI-governance observations

## Problem

Ticket 410 made unread `robots.txt` fetches explicit (`fetch_outcome: unknown`
plus `unknown_reason`), but `collect_ai_governance` still reports the
`/llms.txt` probe as a bare status/absent flag. A timeout, denied destination
or challenge on `/llms.txt` is indistinguishable from "the file does not
exist", so the "llms.txt present" signal on the `robots-txt` record can read
as a confirmed absence when nothing was actually read.

## Tasks and acceptance criteria

- [ ] Route the `/llms.txt` fetch through the same `on_skip` reporting as the
      robots fetch and carry `llms_txt_outcome` (`fetched` / `unknown`) and
      `llms_txt_unknown_reason` on the record; keep `llms_txt_status`.
- [ ] Validation accepts both shapes; saved bundles without the new fields
      still load.
- [ ] Any answerer or report that uses llms.txt presence treats `unknown` as
      untested, never as absent.
- [ ] Command-level tests for timeout, denied destination and 404 on
      `/llms.txt` with a readable robots.txt.

## Status

proposed (Priority: **P3**). Filed 2026-10-07. Related: 370, 410, 411.
