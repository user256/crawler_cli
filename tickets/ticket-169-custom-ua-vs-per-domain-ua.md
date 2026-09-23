# Ticket 169: `--ua DOMAIN=…` must win over `--custom-ua`

## Goal
Restore the documented per-domain User-Agent override when `--custom-ua` is
also set.

## Background (2026-07-22 wiring audit)

Ticket **080** added `user_agent_for(url)`. CLI help still says `--ua` falls
back to `--custom-ua`. But `_build_config` also copies `--custom-ua` into
`request_headers["User-Agent"]` (`__main__.py`). `_request_headers` builds:

```text
{"User-Agent": user_agent_for(url), **request_headers}
```

so the header map wins and every host sees the custom UA. Portfolio crawls
with `--ua` + `--custom-ua` therefore ignore the map.

## Tasks
- Keep the global default only in `config.user_agent`; do not put `User-Agent`
  into `request_headers` from `--custom-ua`.
- Confirm Playwright’s per-page extra headers still call `user_agent_for`.
- CLI hygiene test: matching host gets mapped UA; unmatched host gets
  `--custom-ua` / default.
- Update help text if wording drifts.

## Definition of Done
- `--ua` overrides default/`--custom-ua` for matching hosts.
- Unmatched hosts still use `--custom-ua` (or the built-in default).
- Automated CLI/config test covers the precedence.

## Status
proposed (Priority: **P2**) — CLI wiring; found in 2026-07-22 audit.
