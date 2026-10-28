# Ticket 427: Let the live probes use the crawl's transport, identity and pace options

## Problem

D3 in the ticket 419 live QA
([live-probe-run.md](./qa-new-audit-2026-10-06/live-probe-run.md)): the
`--ai-governance` and `--probe-accept-language` engine in
`technical-audit-observations` is hard-coded to the aiohttp backend, the
default `canonicalbot/0.1` User-Agent, `per_host_concurrency=1` with no
delay (the engine's 5 requests/second default), and challenge detection on.
There is no `--custom-ua`, `--http-backend curl_cffi`, `--impersonate` or
politeness delay.

On rainbet.com it sent about 60 requests in about 17 s, tripped the
Cloudflare challenge within 2–3 requests of the apex, and the circuit breaker
refused the rest. Even after a 3-minute cooldown the probes could not read a
single 200 page on the apex, so ticket 413's primary-content path could not be
certified live, and `--ai-governance` reads only what the challenge allows.

The working crawl recipe for this site is `--http-backend curl_cffi
--impersonate firefox` with a matching Firefox `--custom-ua` and
`--no-challenge-detection` (Turnstile widgets false-positive the body
detector). A 429 means slow down, not escalate.

## Tasks and acceptance criteria

- [x] `technical-audit-observations` accepts `--http-backend`, `--impersonate`,
      `--custom-ua` and `--no-challenge-detection` with the same meaning as
      `crawl`, and a `--probe-delay` (minimum gap between probe requests, polite
      by default).
- [x] With detection off, a real challenge (`cf-mitigated: challenge`, or a
      challenge page on 403/429/503) is still recorded as challenged (ticket
      425), while a real 200 page that embeds Turnstile is compared normally.
- [x] The guarded engine keeps robots, scope, circuit breaker and a destination
      guard on every backend.
- [x] Unit tests for the engine configuration the flags produce.
- [x] Re-run a small live check against rainbet.com with the Cloudflare
      recipe and record it in live-probe-run.md.

## Status

done (Priority: **P2**). Filed 2026-10-07 from the ticket 419 live QA (D3);
fixed on branch `fix/ticket-425-427`, 2026-10-07. Related: 410, 413, 419, 425.

Fix: `technical-audit-observations` has a "Live probe transport" group with
`--http-backend`, `--impersonate` (implies curl_cffi; rejected with an explicit
aiohttp backend), `--custom-ua`/`--user-agent`, `--no-challenge-detection` and
`--probe-delay SECONDS` (default **1.0**, the minimum gap between probe requests;
0 turns the limiter off; before this the engine allowed 5 requests per second).
`__main__._probe_engine_config` builds the engine for both `--ai-governance` and
`--probe-accept-language`, using the same UA rule as `crawl`: an impersonated
profile keeps its own UA unless `--custom-ua` is given. Robots, scope, the circuit
breaker, one request per host and no browser escalation are unchanged. The
address-pinned destination guard can only reach aiohttp sockets, so a curl_cffi
probe uses the resolver guard, which is the crawl's default. With detection off,
real challenges are still caught by ticket 425's hop check. Tests in
`tests/test_audit_observation_adapters.py`. The live rainbet re-check with the
Cloudflare recipe read 200 pages on the apex, see
[live-probe-run.md](./qa-new-audit-2026-10-06/live-probe-run.md).
