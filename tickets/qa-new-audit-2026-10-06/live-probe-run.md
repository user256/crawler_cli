# Ticket 419: live public-site QA of the reattached probes

**Result: partial.** The fixed AI-governance paths (410, 411) behaved correctly on a live Cloudflare-fronted site, both
uncapped and capped, and Q96 never went above Needs validation. The Accept-Language failure path (412) labelled
refused requests `not_admitted` and kept them untested, and Q25's only finding reproduces by hand. One new defect
was found (**D1**, P1): a bot-challenge response (HTTP 429, `cf-mitigated: challenge`) is treated as a resolved,
observed HTTP status in the locale probe. That is the 412 defect class again by a different route. The
primary-content path (413) and the timeout label (`fetch_failed`) could not be exercised live, because the probe
engine was challenged before it read any 200 page on the apex host (**D3**).

- Date: 2026-10-07, 10:30–10:35 BST
- Code: worktree `fix/ticket-419` at `c6073c3` (PR #119 tip, with the fixes for 410–413), run from source with
  `PYTHONPATH=src` and the main checkout's `.venv`
- Site: **rainbet.com** (audit client, Cloudflare). It has 9 hreflang locales (ar, en, es, fr, ja, pt, ru, tr, zh,
  plus x-default) on path prefixes. It has two eligible hosts: `rainbet.com` and `www.rainbet.com`. The www host
  answers 308 to the apex, or 307 to a locale path when an Accept-Language header is sent.
- Database: throwaway `t419_rainbet_qa_crawler` on local PG16. Drop it with
  `dropdb t419_rainbet_qa_crawler` when it is no longer needed for replay.
- Scratch outputs (gitignored, not copied here): `runs/t419-live/` in the worktree, holding the crawl log, both
  bundles, both question outputs, curl transcripts and the D1 repro script and output.

## Commands

```sh
DSN=postgresql://sql_crawler:...@localhost:5432/t419_rainbet_qa_crawler
PY="env PYTHONPATH=src /home/user256/GitRepos/crawler_cli/.venv/bin/python -m crawler_cli"

# 1. Small crawl to give the run two seed hosts and some locale roots (8-page cap, no sitemaps, one request at a time)
$PY crawl https://rainbet.com/ --seed-url https://www.rainbet.com/ \
  --seed-url https://rainbet.com/es --seed-url https://rainbet.com/fr \
  --seed-url https://rainbet.com/ja --seed-url https://rainbet.com/pt \
  --crawl-run-id t419-rainbet --max-pages 8 --skip-sitemaps \
  --concurrency 2 --per-host-concurrency 1 --no-challenge-detection --postgres-dsn "$DSN"
$PY technical-audit --crawl-run-id t419-rainbet --out runs/t419-live/audit.json --postgres-dsn "$DSN"

# 2. Uncapped (default --ai-governance-max-origins 10, which is above 2 eligible hosts)
$PY technical-audit-observations --crawl-run-id t419-rainbet --out runs/t419-live/uncapped.json \
  --ai-governance --probe-accept-language --tls-probe --postgres-dsn "$DSN"
$PY technical-audit-questions --audit runs/t419-live/audit.json \
  --observations runs/t419-live/uncapped.json --out runs/t419-live/uncapped-questions.json

# 3. Capped below the host count (cap 1 of 2), run after the rate limit cleared
$PY technical-audit-observations --crawl-run-id t419-rainbet --out runs/t419-live/capped.json \
  --ai-governance --ai-governance-max-origins 1 --probe-accept-language --tls-probe --postgres-dsn "$DSN"
$PY technical-audit-questions --audit runs/t419-live/audit.json \
  --observations runs/t419-live/capped.json --out runs/t419-live/capped-questions.json
```

The crawl used the default aiohttp backend and UA (`canonicalbot/0.1`), because a curl check showed that UA got 200s
at first. It crawled 8 URLs with 3 transient retries. `/ja`, `/pt` and `/?modal=search` came back 429. The 200
locale roots `/es` and `/fr` became Accept-Language targets.

Live load: about 11 crawl requests. Each observations run sent 49 locale-probe requests, as recorded in the coverage
row, many of which the circuit breaker refused before sending. Each run also made the robots/llms fetches (about 10).
About 15 curl requests were made by hand, plus 2 polls during the cooldown. Every request ran one at a time per host.

## Counts and verdicts

| | Uncapped | Capped (cap 1) |
|---|---|---|
| Exit code / bundle written | 0 / yes | 0 / yes |
| robots-txt | 2 records, **partial** | 1 record, **partial** |
| population | eligible 2, selected 2, omitted 0, unread `www.rainbet.com` | eligible 2, selected 1, omitted `www.rainbet.com`, unread none |
| robots record outcomes | `rainbet.com` fetched 200; `www.rainbet.com` `fetch_outcome: unknown`, `unknown_reason: challenge:cloudflare` | `rainbet.com` fetched 200 |
| locale-probe | 28 records (4 of 4 roots × 7 variants), coverage **complete** (see D2) | same |
| locale outcomes | `rainbet.com/` 7× 429/429 "resolved"; `/es`, `/fr` 14× `not_admitted` (`circuit_breaker_open`); `www.rainbet.com/` 3× 308/308, 4× 308→307 (ja, pt variants `redirect_target_not_admitted` at hop 2) | same pattern |
| tls-probe | 1 host, partial | 1 host, partial |
| Q25 | **Needs validation** / Yes, ticket, 1 of 1 URL; 24 probes untested; "circuit_breaker_open 28" never answered | same |
| Q96 | **Needs validation** / No (partial), no ticket; "robots.txt unavailable or unread for: www.rainbet.com (challenge:cloudflare)" | **Needs validation** / No (partial), no ticket; "Eligible hosts never probed (capped): www.rainbet.com", even though all 7 agents are allowed on the selected host |
| Q63 | Needs validation / Yes: no HSTS on `rainbet.com` (confirmed by curl headers) | same |
| Totals | Issue 2, Needs validation 23, Healthy 0, Pending 79 | same |

The two Issues are Q26 (run completeness gate: 1 of 8 HTML responses not parsed) and Q81 (3 crawl responses were
429/503). Both come from the crawl's run context, not from the probes. Q81 is real: the crawl itself was rate
limited. Because these run gates fail, every observation-backed answer on this run is capped at Needs validation
anyway, so the live Q25/Q96 verdicts are over-determined. The capped Q96 verdict was checked against the note: it
names the omitted host, which is the ticket 411 guard, not only the run gate.

## Acceptance criteria

1. **Run uncapped and capped below host count.** Met.
2. **Bundle contract.** Met:
   - Every eligible host is present in `population.eligible` in both runs.
   - The unread host keeps a record with `fetch_outcome: unknown`, null status and body, and a reason.
     `challenge:cloudflare` is accurate: www's robots.txt 308s to the apex, and a curl of the apex at that point got
     `429` with `cf-mitigated: challenge` and a "Just a moment..." page.
   - The capped run is `partial` with `omitted: [www.rainbet.com]`.
   - The failed robots fetch did not abort the command (410). locale-probe and tls-probe were both written.
3. **Accept-Language records.** Partly met:
   - Refused variants are `not_admitted` with `skip_reason: circuit_breaker_open`. They have null statuses, are
     untested, and are named in Q25's note.
   - A refused redirect target keeps the real first-hop finding (`redirect_target_not_admitted` at hop 2, with
     308→307 kept).
   - No timeout happened live, so the `fetch_failed` label was not observed. It is covered only by
     `tests/test_accept_language_audit.py`.
   - `primary_content_differs` and `raw_body_differs` are null on every record, so nothing was promoted from raw
     bytes. But the positive path (an answered 200 baseline, a matching repeat and a hash compare) never ran live,
     because no 200 page was read on the apex (D3).
   - **D1 breaks this criterion's intent:** a challenged response counts as an answered status.
4. **Questions.**
   - Q25 and Q96 are Needs validation in both runs. Neither is Issue or Healthy.
   - Q25's finding (a ticket-flagged row) was reproduced by hand, below.
   - No Issue verdict came from the probes.
5. **Record.** This file.

## Hand reproduction of the Q25 finding (`www.rainbet.com/`: status 308->307, Location /es, /fr, /ja, /pt)

Done with `curl -sS -o /dev/null -D - -A "canonicalbot/0.1" [-H "Accept-Language: ..."] https://www.rainbet.com/`,
4 seconds apart, at 10:34 BST:

| Accept-Language | Status | Location |
|---|---|---|
| (none) | 308 | `https://rainbet.com` |
| `es-ES,es;q=0.9` | 307 | `/es` |
| `de-DE,de;q=0.9` | 308 | `https://rainbet.com` |
| `ja-JP,ja;q=0.9` | 307 | `/ja` |
| `es-ES` with a Firefox UA | 307 | `/es` |

- **Confirmed.** The www host varies its redirect on Accept-Language, with no `Vary` header. The collector's
  `missing_vary_header` and `language_redirect_detected` candidates are right.
- The tool records Location resolved to an absolute URL (`https://www.rainbet.com/es`). The raw header is `/es`.
- There is a site-side follow-on: `https://www.rainbet.com/es` with `es-ES` 308s to `https://rainbet.com` (the apex
  root). The language redirect therefore lands users on the English root and drops the locale.
- This is a real site observation for the audit, not a crawler defect.

## Defects found (not fixed on this branch)

### D1 (P1): a bot-challenge response is treated as an answered HTTP status in the locale probe

**What happens live.**
- Every `rainbet.com/` variant was a Cloudflare challenge. The engine logged "Bot challenge (cloudflare) … recorded
  as blocked".
- The persisted hop has `status: 429, skip_reason: "bot_challenge"`. Session `22eb6b2f-…`, table
  `language_probe_records`.
- `accept_language_audit._probe` only treats `status == 0` as unanswered. So the hop gets `outcome: "resolved"`.
- The adapter then records `baseline_status`/`variant_status` 429 with `variant_outcome: resolved` and
  `variant_failure: null`.
- On this run the comparison stayed untested only by luck: both sides were 429 and neither had a content hash.
- The same responses also raise `bot_trap` candidates (`error_status`) on the site.

**Why it matters.**
- Cloudflare challenged the probe after about 2 requests on the apex in both runs. A target whose baseline is
  answered 200 and whose later variants are challenged will report `status 200->429` as a language-driven change.
- Q25 gets a ticket-flagged row for a rate limit or challenge. This is the ticket 412 defect, reached through a
  non-zero status.

**Repro (offline, from the live evidence).** `runs/t419-live/d1/repro_d1.py`:
- It loads the uncapped session's persisted `rainbet.com/` evidence.
- It sets only the header-less `none`/`none-repeat` probes to an answered 200 with a primary-content hash.
- It runs the real `locale_probe_records` and then `technical-audit-questions`.
- Result: `es-ES: baseline_status 200, variant_status 429, variant_outcome resolved, variant_failure None`. Q25 is
  **Yes, ticket=true**, with findings `de-DE: status 200->429; … wildcard: status 200->429`.
- It is Needs validation here only because this run's run gates (Q26 and Q81) fail. Reading
  `technical_audit_questions._answer` shows a run with a passing gate and a complete collection would give
  **Issue**.

```sh
PYTHONPATH=src .venv/bin/python runs/t419-live/d1/repro_d1.py runs/t419-live/d1/d1-bundle.json
PYTHONPATH=src .venv/bin/python -m crawler_cli technical-audit-questions --audit runs/t419-live/audit.json \
  --observations runs/t419-live/d1/d1-bundle.json --out runs/t419-live/d1/d1-questions.json
```

**Expected.**
- A hop carrying a challenge skip reason (`bot_challenge`, or a `cf-mitigated: challenge` header) gets its own
  unanswered outcome, for example `challenged`, that is neither `resolved` nor a trap by status alone.
- The adapter carries that outcome as `*_failure` with a null status.
- Q25 counts the comparison as untested and names the reason.
- Decide whether plain 429/503 without challenge markers should be untested too. They are rate limits, not language
  behaviour.

### D2 (P2): the locale-probe collection claims `complete` when most comparisons were never answered

- Both bundles mark `locale-probe` `coverage_state: complete`, and the persisted coverage row says
  `"complete": true`, while 21 of 28 records have no answered status. 14 are `not_admitted` and 7 are challenged.
- Coverage is computed from `len(targets) >= population` in `__main__._run_technical_audit_observations` and in the
  collector's coverage row. It ignores unanswered variants.
- Q25 still compensates (24 untested, Needs validation), but every Q25 row carries `"coverage": "complete"`.
- Any other consumer of the bundle sees a complete collection. That contradicts 412's "retain successful variants
  without claiming complete coverage".
- **Expected:** `partial` whenever any baseline, repeat or variant is unanswered, and say so in the scope.

### D3 (P2, operational): the probe engine cannot be configured for a protected site

The `--ai-governance` and `--probe-accept-language` engine is hard-coded:
- aiohttp backend
- default UA `canonicalbot/0.1`
- `per_host_concurrency=1` with no delay
- challenge detection always on
- no `--custom-ua`, `--http-backend curl_cffi`, `--impersonate` or politeness delay

On rainbet it sent ~60 requests in ~17 s, tripped the Cloudflare challenge within 2–3 requests of the apex, and the
circuit breaker then refused the rest. Even after a 3-minute cooldown, the probes could not read one 200 page on the
apex host. So:
- 413's primary-content path cannot be certified live on a Cloudflare site.
- `--ai-governance` reads only what the challenge allows.

**Expected:** pass the crawl's transport and UA options (or the same flags) through to the probe engine, and add a
per-request delay. Then re-run this QA with the cloudflare recipe (`--http-backend curl_cffi --impersonate firefox`
plus a matching Firefox `--custom-ua`).

### Observations, not defects

- Q25 counts a redirect-only comparison as untested: same 308, same Location, no content hash. Examples are the
  `www.rainbet.com/` de-DE, en-US and wildcard variants. So a root that only redirects can never reach Healthy.
  This is conservative and consistent with 413, but it means hosts that only redirect always stay Needs validation.
- tls-probe lists only `rainbet.com`. The `www.rainbet.com` 308 responses are not a separate host row. This is
  ticket 414's territory and was not assessed further here.
- The Q25 "never answered" note counts each side (baseline and variant) of a fully refused record. So
  "circuit_breaker_open 28" covers 14 records.

## Follow-up

File D1 (P1) and D2/D3 (P2) as tickets. When D3 is resolved, re-run this QA so that 413's primary-content path and
the `fetch_failed` label get live evidence. Rainbet with the cloudflare recipe is a good choice. A non-Cloudflare
multi-locale site would also exercise the success path.

## Re-check after tickets 425–427 (2026-10-07, 11:49–11:56 BST)

**Result: pass.** With the probe engine on the Cloudflare recipe, the Accept-Language probe read answered 200 pages on
the `rainbet.com` apex. The 413 primary-content path ran live for the first time. When Cloudflare challenged one
request, the probe recorded it as `challenged` and did not compare it (the D1 fix, seen live). The collection said
`partial` (the D2 fix). No Issue or Healthy came from the probe.

- Code: branch `fix/ticket-425-427` (fixes at `1ec7e99`, plus the Q25 control-note follow-up at `6972128`), run from
  source with the main checkout's `.venv`.
- Database: the 419 throwaway `t419_rainbet_qa_crawler`, read-only. The DSN set `default_transaction_read_only=on`,
  and a wrapper replaced `AsyncpgStore.persist_language_probe_evidence` with a write to a JSON file, so no session
  was stored. Everything else was the real `technical-audit-observations` path. Scratch outputs (gitignored):
  `runs/t425-live/` in the 425 worktree, holding the wrapper `run_probe.py`, the evidence JSON, both bundles, both
  question outputs and logs.
- Scope: one target only (`--accept-language-max-targets 1`, the apex root), no `--ai-governance`. Each run made 9
  probe requests plus the engine's robots.txt fetch. **Total live load: about 20 requests in two runs, 6 minutes
  apart.**

```sh
FF_UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"
DSN='postgresql://sql_crawler:...@localhost:5432/t419_rainbet_qa_crawler?options=-c%20default_transaction_read_only%3Don'
PYTHONPATH=src .venv/bin/python runs/t425-live/run_probe.py runs/t425-live/evidence-apex.json \
  technical-audit-observations --crawl-run-id t419-rainbet --out runs/t425-live/apex.json \
  --probe-accept-language --accept-language-max-targets 1 \
  --http-backend curl_cffi --impersonate firefox --custom-ua "$FF_UA" --no-challenge-detection \
  --probe-delay 3 --postgres-dsn "$DSN"
# second run after a 5-minute cooldown: same command with --probe-delay 8 and apex2/evidence-apex2 outputs
$PY technical-audit-questions --audit ../crawler_cli-t419/runs/t419-live/audit.json \
  --observations runs/t425-live/apex2.json --out runs/t425-live/apex2-questions.json
```

| | Run 1 (`--probe-delay 3`) | Run 2 (`--probe-delay 8`, after 5 min) |
|---|---|---|
| Answered | 8 of 9: `none`, wildcard and all 6 locales returned 200 | 9 of 9 returned 200 |
| Challenged | the 9th request, the `none-repeat` control: 429 with `cf-mitigated: challenge`, recorded as `challenged` (`challenge: cloudflare`) with engine detection **off** | none |
| Primary content | the same `<main>` text hash on all 8 answered responses (`main_visible_text`); raw bodies all differ | the same `<main>` text hash on all 9; raw bodies all differ |
| Records | `primary_content_differs: None` on all 7 records, because the repeat control was not answered | `primary_content_differs: False`, `raw_body_differs: True` on all 7 records; statuses 200/200, no Location |
| Coverage row / bundle | `complete: false`, `unanswered_probe_outcomes: {challenged: 1}` / `partial`, scope "1 of 4 eligible roots; 7 header variants; 1 probe requests unanswered (challenged 1)" | `complete: false` (1 of 4 roots) / `partial` |
| Candidates | none (no bot trap from the 429) | none; `neutral_access` `clean`, content stable across the repeat |
| Q25 | **Pending**, no ticket: "7 probes lack a … content comparison" | **Needs validation / No (partial)**, no ticket, denominator 1: "7 probes differ only outside the primary content …; review-only evidence, not counted" |

- The run-1 bundle was written before the control-note follow-up, so its Q25 note does not name the repeat control.
  With `6972128`, Q25 adds "Repeated header-less control never answered, so content not compared (URLs):
  challenge:cloudflare 1" for that evidence, and a unit test copies this case.
- The apex serves the same English `<main>` whatever the Accept-Language. The www host's language redirect from the
  419 run is a separate finding and was not probed again.
- Pace, not identity, triggered the challenge: the recipe passed for 8 requests at 3 s, then got a 429. After a
  5-minute pause it passed for 9 requests at 8 s. No retries and no escalation. Use `--probe-delay 8` or more on
  this zone for anything bigger.
- Still without live evidence: the `fetch_failed` (timeout) label. It is covered by
  `tests/test_accept_language_audit.py` and `tests/test_locale_probe_verdicts.py`. No live timeout happened, and none
  was forced.

The ticket 419 Accept-Language box is now met. Refused variants were `not_admitted` and untested live (419 run).
Challenged ones are now `challenged` and untested live. `primary_content_differs` was set live only from the
`<main>` hash with a matching repeat (False, run 2), and stayed unknown live when the repeat was not answered
(None, run 1).
