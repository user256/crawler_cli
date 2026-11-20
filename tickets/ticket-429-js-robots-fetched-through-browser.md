# Ticket 429: --js crawls report every URL as blocked by robots

## Problem

Repro (2026-11-20, uisgebeatha.co.uk, whose robots.txt is only `User-agent: *`
and a `Sitemap:` line):

    crawler-cli -v crawl --csv-file one.csv --csv-column url --js --web-vitals --max-workers 1 --save-to one.json
    Crawl complete: 0 crawled, 1 blocked by robots

The aiohttp crawl of the same site had no robots blocks.

Cause: with the destination guard on (the default `resolver` tier), the engine
routes robots.txt through `_fetch_for_purpose`, which for `--js` ends in
`PlaywrightBackend.fetch`. Two failures follow from that:

1. If the browser cannot start (here Playwright 1.60 wanted
   `chromium_headless_shell-1223`, which was not installed), the exception is
   swallowed in `RobotsPolicyCache._fetch_robots_txt` as status 0. RFC 9309
   treats that as unreachable, so the host is fully disallowed. Nothing was
   logged, so the run reported "blocked by robots" with no cause.
2. With a working browser the result was still wrong: `PlaywrightBackend.fetch`
   returns `page.content()`, the rendered DOM. Chromium wraps plain text in
   `<html>…<pre>`, so the first `User-agent` line and any HTML-special
   characters in rules are lost. Sitemaps (`purpose="sitemap"`) had the same
   problem, because XML is replaced with Chromium's tree viewer.

The empty-rule `User-agent: *` group is parsed correctly (allow-all). It was
not the cause.

## Fix

- On a Playwright run, robots.txt and sitemap documents are fetched by an
  auxiliary `AiohttpBackend`, after the same scope check and with the aiohttp
  destination guard. This guard is stronger than the browser's URL interception.
  This applies with the guard `off` too, rather than using the legacy robots
  session. Page fetches still use the browser.
- With a managed Obscura CDP browser, the document backend uses `obscura_proxy`
  (its pool and `proxy_auth` cleared), as the browser does. Otherwise it uses
  the general proxy settings.
- `ObscuraFetchBackend` (`--obscura-fetch`) is unchanged. It already dumps
  `.txt`/`.xml` raw through its own proxy.
- A robots.txt fetch that raises now logs a warning naming the exception
  (`event=robots_fetch_failed`) before the host is treated as unreachable.

## Acceptance

- [x] Regression tests (`tests/test_js_robots_documents.py`, 12): rule-less
      `User-agent: *` group with the JS backend (guard `resolver` and `off`);
      a Chromium `<pre>` wrapper would hide `Disallow` and `Sitemap`; sitemaps
      are fetched over HTTP, not the browser; the document backend is closed
      with the engine; Obscura proxy precedence; the Obscura subprocess backend
      is untouched; a failing robots fetch is logged. Without the engine change,
      8 tests fail.
- [x] Related suites (robots, sitemap, playwright, destination, engine,
      challenge, obscura, security, portal, proxy): 395 passed, 3 skipped. ruff
      check and format clean.
- [x] Live `--js --web-vitals` run against uisgebeatha.co.uk on 2026-11-20:
      "1 crawled, 0 blocked by robots", status 200, `allowed_by_robots` true,
      LCP 364 ms, CLS 0. Playwright 1.60 cannot install its own Chromium on
      Ubuntu 26.04 ("does not support chromium on ubuntu26.04-x64"), so the run
      used the snap Chromium 156 via `--playwright-executable-path /snap/bin/chromium`.

## Review

Builder: Claude (Opus 5.5). Independent QA: Codex `gpt-5.6-terra`, medium
effort, 2026-11-20.

- Round 1: FAIL. `obscura_proxy` was dropped for documents; no wrapper test; no
  Obscura or lifecycle tests. All three fixed. 74,510 tokens. (An earlier attempt
  hung on stdin and returned no review.)
- Round 2: FAIL. The general proxy beat `obscura_proxy`, unlike the managed
  Obscura browser. Fixed. 56,357 tokens.
- Round 3: PASS WITH NOTES, no findings. 44,950 tokens. The reviewer's
  sandbox could not bind 127.0.0.1, so it ran only the non-network tests. The
  builder ran all of them.
