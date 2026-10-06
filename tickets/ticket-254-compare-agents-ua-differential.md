# Ticket 254: Compare responses across crawler and browser User-Agents

## Status and priority

Proposed — P1. Owner: unassigned. Depends on 224 (coherent fetch profile and
shared per-host rate limit). Uses the interpretation rules in 249. Reuses the
output, sampling and report machinery from 160 (`compare-renders`).

## Goal

Fetch the same URL set as several named agents (Googlebot, Screaming Frog, a
real browser) and report where the server sends different responses. The
output supports a manual review of possible cloaking or unusual UA-dependent
behaviour. It does not decide that cloaking occurred.

## Background

The technical audit already probes the server configuration with custom checks:
www/non-www, HTTPS/HTTP and made-up URLs for soft-404s (193, 236). It has no way
to compare what one URL returns to different User-Agents. On rainbet.com the
UA mattered even for ordinary access: a Chrome fingerprint was blocked, and
Firefox only got through with a matching UA (224). Ticket 249 set out how to
interpret bot/user differences, but no tool collects that evidence.

Ticket 152 (session-diff) compares authenticated identities. This ticket
compares crawler and browser identities over anonymous requests. Keep them
separate, but share the differential and report code where it fits.

## Command contract

```text
crawler-cli compare-agents \
  --csv-file urls.csv | --url-source semrush-pages:export.csv | --crawl-run-id N | URL... \
  --agents googlebot-smartphone,screaming-frog,browser-firefox \
  [--baseline browser-firefox] [--repeat-baseline 2] [--render] \
  [--max-pages N] [--sample-strata] \
  --out agent-comparison.json [--csv out.csv] [--html out.html] \
  [--fail-on seo-significant]
```

## Tasks

### Agent profiles

- Add a registry of named fetch profiles. Each profile sets the UA,
  Accept/Accept-Language headers, device class (viewport for `--render`) and,
  for browsers, the matching `--impersonate` target from 224. Ship at least
  these profiles:
  - `googlebot-smartphone` and `googlebot-desktop`, using Google's documented
    UA strings, with an evergreen Chrome version the user can configure.
  - `bingbot`.
  - `screaming-frog`, the default `Screaming Frog SEO Spider/<ver>` UA.
  - `browser-chrome` and `browser-firefox`, with a coherent fingerprint and UA
    from 224.
  - A user-supplied profile file (JSON), for example a client's own monitoring
    UA.
- Every profile in one run uses the same egress (pin the proxy/IP for the
  whole run), the same Accept-Language, and an isolated cookie jar. Different
  IPs or cookies must not show up as UA differences.

### Noise control

- Fetch the baseline agent at least twice per URL (A/A) and interleave agent
  order across URLs. Treat a field that differs between the two baseline
  fetches as volatile for that URL: A/B tests, rotating promos, timestamps and
  CSRF tokens. Record it as noise, not as a UA difference.
- Normalise known volatile markup before diffing: nonces, cache-busting query
  strings and build hashes in asset URLs. Keep the normalisation rules
  versioned in the output.

### Comparison

For each URL and each non-baseline agent, compare:

- **Transport:** status, redirect chain and final URL, content type, body size,
  and the `Vary`, `Cache-Control`, `X-Robots-Tag` and `Link` headers.
  Record `Set-Cookie` cookie names only, never values.
- **Access state:** ok / challenged (reuse 074/215 detection) / rate-limited
  (181) / blocked (403/451) / geo or age interstitial.
- **Indexing signals:** canonical, meta robots, title, meta description, H1,
  hreflang set, JSON-LD `@type`s (159 parser), and pagination links.
- **Content:** visible-text length, main-content hash and simhash distance,
  plus added and removed text blocks, each capped in size.
- **Links:** internal link set, and the anchors present only for the bot or
  only for the browser (with counts and a capped sample).
- With `--render`, repeat the comparison on the Playwright DOM using each
  profile's UA and viewport. This catches client-side
  `navigator.userAgent` branching. Reuse the 157/160 settle and completeness
  code.

### Classification

Classify each agent pair on each URL as one of:

- `identical`
- `volatile-only`: every difference is within the A/A noise.
- `access-difference`: one agent was challenged, blocked or rate-limited.
  Spoofed-Googlebot blocking goes here, with a note. It is **not** cloaking
  evidence.
- `seo-significant`: indexing signals, status or redirect target differ.
- `bot-only-content` or `user-only-content`: material text or links appear for
  only one side.

Store the class together with the per-field evidence. Never emit the word
"cloaking" as a verdict; use "UA-dependent difference — review".

### Output and limitations

- Write versioned `crawler-cli/agent-comparison/1` JSON, a CSV with one row per
  URL×agent, and a self-contained HTML report with filters and side-by-side
  field diffs, matching the 160 report style.
- Every report must state that spoofed crawler UAs come from a non-Google/Bing
  IP. A site that verifies bots by reverse DNS may correctly treat them as
  fakes. The true Googlebot view is available only from Google itself.
- Add an optional `--observed-google PATH` import that loads the HTML from a
  URL Inspection / Rich Results Test "view crawled page" export as a read-only
  `google-observed` agent. Compare it the same way, with its own capture date.
- Use the shared per-host budget from 224, with a conservative default rate.
  Each extra agent multiplies the request count, so print the planned request
  total before starting and stop at `--max-requests`.

## Acceptance criteria

- [ ] A fixture server that returns different titles, canonicals, links and
  noindex by UA produces `seo-significant` and `bot-only-content` rows with
  the exact differing fields.
- [ ] A fixture page with a random token and a rotating promo block produces
  `volatile-only`, not a difference.
- [ ] A fixture that returns 403 only to Googlebot UAs produces
  `access-difference` with the spoofed-bot note, and no cloaking wording.
- [ ] A fixture that swaps content client-side on `navigator.userAgent` is
  detected with `--render` and missed (reported identical) without it.
- [ ] All agents in one run share one egress and one per-host rate budget
  (timing test), and cookie jars do not leak between agents.
- [ ] `--fail-on seo-significant` sets a non-zero exit code only when such a
  row exists.
