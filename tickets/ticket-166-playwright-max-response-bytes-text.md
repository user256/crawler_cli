# Ticket 166: Playwright must cap `text`, not only `body`

## Goal
Make `--max-response-bytes` / `max_response_bytes` actually bound what the
engine extracts and persists when using the Playwright backend.

## Background (2026-07-22 wiring audit)

Ticket **054** capped streaming reads for aiohttp/curl_cffi. Playwright still
does:

```text
body = html.encode(...)[:cap]
text = html   # full DOM
```

(`backends.py` `PlaywrightBackend.fetch`). The engine extraction, hashing, and
persist paths consume `response.text`, not `body`. The extracted/persisted
representation therefore bypasses the cap and hashes disagree with HTTP
backends for the same URL.

This bounds the value retained and parsed by the engine; it is **not** a hard
browser/network memory cap because `page.content()` has already materialised
the full DOM. ObscuraFetch likewise buffers subprocess stdout before applying
its cap and currently truncates rendered HTML by characters, so it is not the
byte-parity reference for this fix.

## Tasks
- Use the capped UTF-8 byte representation already placed in `body`, then
  decode it safely for `text`, matching the HTTP backends' byte-cap contract.
  Define behaviour when the byte boundary splits a multibyte character.
- Set `body_truncated=True` only when the encoded DOM exceeded the cap (an exact
  cap-sized document is not evidence of truncation).
- Unit tests cover oversized ASCII, multibyte UTF-8 boundaries, exact-cap input,
  parsed `text`, and the flag.
- Document that the cap bounds engine extraction/persistence, not Chromium's
  in-page DOM or the temporary string returned by `page.content()`.

## Definition of Done
- Playwright respects `max_response_bytes` for the string the engine parses.
- `body_truncated` is set when truncation occurs.
- `body` and `text` represent the same capped bytes without invalid decoding.
- Automated regression exists; HTTP backend behaviour unchanged.

## Status
proposed (Priority: **P1**) — backend correctness; found in 2026-07-22 audit.
