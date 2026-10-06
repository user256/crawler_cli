# Ticket 168: Fix Playwright/Obscura `per-host` proxy selection

## Goal
Make `--proxy-rotation per-host` work for browser backends, or reject it
explicitly instead of silently selecting with an empty host key.

## Background (2026-07-22 wiring audit)

Ticket **073** routed the proxy pool through Playwright/Obscura. List-mode
selection still calls `self._proxy_pool.select("")` in
`_playwright_proxy_setting` and the managed-Obscura path (`backends.py`).
`ProxyPool._select_per_host` keys on hostname (`proxy_pool.py`), so an empty
host sticks all traffic to one proxy entry. The proxy is also bound at context
create time, not per navigation.

ObscuraFetch’s one-shot path already calls `select(url)` — Playwright/managed
Obscura do not.

## Tasks
- Select by target URL for Playwright/managed Obscura **or** raise a clear
  unsupported error when `proxy_rotation == "per-host"` with those backends.
- If selecting per URL, recycle/rebuild context when the selected proxy changes
  (or document that per-host requires one context per host).
- Tests with two hosts under `per-host`.
- Docs: gateway vs list vs browser-context granularity.

## Definition of Done
- `per-host` either works for browser backends or fails loudly at startup.
- Automated coverage for two-host selection.
- No silent `select("")` sticky behaviour.

## Status
proposed (Priority: **P1**) — proxy wiring; found in 2026-07-22 audit.
