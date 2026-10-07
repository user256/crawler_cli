# Technical audit observation bundles

Some audit questions need evidence that a stored crawl does not hold: a rendered
or mobile page, an active probe, or a record from a third-party tool. That
evidence reaches the question runner as an **observation bundle**. The runner
never makes the request itself.

```sh
crawler-cli technical-audit --crawl-run-id RUN --out audit.json
crawler-cli technical-audit-observations --crawl-run-id RUN --out observed.json \
  --html-signals \
  --render-comparison renders.json \
  --exposure-inventory exposure.json \
  --robots-txt example.com=robots.txt
crawler-cli technical-audit-questions --audit audit.json --site-profile profile.json \
  --observations observed.json --observations supplied-gsc.json --out answers.json
```

- `--html-signals` scans the run's stored raw HTML
  (`crawler_cli.audit_html_signals`). It needs the run's database.
- `--render-comparison` takes the JSON written by
  `compare-renders --crawl-run-id RUN --output`. A comparison sampled from
  another run, or from explicit URLs, is refused. It answers Q85 only:
  compare-renders does not extract footer links, so Q46 stays Pending until a
  `render-parity` collection with `footer` fields is written by hand or by a
  future collector.
- `--exposure-inventory` takes an `exposure-inventory` artifact. Hosts the
  inventory did not request remain untested.
- `--robots-txt HOST=FILE` takes a robots.txt body saved by the operator.
- `--ai-governance` fetches each seed origin's robots.txt and /llms.txt through
  the guarded engine and writes `robots-txt` records (status, body,
  llms_txt_status). A robots.txt that was not read (timeout, denied
  destination, challenge, truncated body, no response) is kept as a record with
  `fetch_outcome: "unknown"`, a null status and an `unknown_reason`, and makes
  the collection partial. `--ai-governance-max-origins` caps the probed seed
  origins; the collection's `population` records the eligible, selected and
  omitted origins, and a cap below the eligible count makes coverage partial,
  so Q96 cannot reach Healthy from a sample.
- `--probe-accept-language` probes the seed and locale roots with a fixed
  Accept-Language set (ticket 260), persists the session (ticket 264) and
  writes `locale-probe` records.
- `--tls-probe` reads Strict-Transport-Security headers from the run's stored
  HTTPS responses and writes `tls-probe` records. The preload list is not
  queried and OCSP stapling is not observed, so `preload_status` and
  `ocsp_stapled` stay null and Q63 cannot reach Healthy from this source.

Other kinds, such as render traces, mobile renders, locale probes and supplied
Google records, are written directly in the format below by the tool or analyst
that collected them.

## Format

```json
{
  "schema_version": "crawler-cli/audit-observations/1",
  "crawl_run_id": "RUN",
  "collections": [
    {
      "kind": "render-trace",
      "source": "Playwright 1.47 mobile trace, Moto G4 profile",
      "collected_at": "2026-10-06T09:00:00Z",
      "scope": "3 URLs per key template from run RUN",
      "coverage_state": "partial",
      "records": [{"url": "https://example.com/reviews/x", "template": "review", "lcp_ms": 3100}]
    }
  ]
}
```

- `crawl_run_id` must equal the audit's run. The runner refuses a bundle from
  another run, so observations stay keyed to the same run and URL identity as
  the crawl evidence.
- `source`, `collected_at` (ISO 8601) and `scope` are required. Every answer row
  copies them as `observation_source`, `observed_at` and `coverage`.
- `coverage_state` is `complete` only when the collection covers the whole
  population the question asks about. Use `partial` for a sample. A partial
  collection can produce Yes, but it never produces Healthy.
- Each record must carry its kind's identity fields. A record without a field
  that a rule needs is counted as untested, which keeps the answer below
  Healthy, unless a field it does carry already proves the defect (a 404 link
  is a finding even when its `rel` was not recorded). If no record of a kind
  is tested, the question stays Pending.

## Kinds

| Kind | Identity fields | Fields the answerers read | Questions |
|---|---|---|---|
| `html-signals` | url | is_https, mixed_content, insecure_internal_links, forms, tracking_preloads, font_faces_without_swap, font_preloads, head_blocking_stylesheets, head_sync_scripts, spam_matches, hidden_links, hreflang_alternates, linked_alternates, followed_external_links | Q5, Q33, Q43, Q45, Q65, Q67, Q86, Q92 |
| `render-parity` | url, state | findings[] (compare-renders codes, for Q85); footer.raw_links, footer.rendered_links (for Q46; not written by compare-renders, so they need a hand-written or future collection) | Q85, Q46 |
| `render-trace` | url | template, api_request_count, uncacheable_api_urls, lcp_ms, cls, inp_ms, images_total, images_missing_dimensions, critical_origins, preconnect_origins, lcp_element {type, src, loading, fetchpriority, width, height, is_background} | Q29, Q35, Q64, Q68, Q69 |
| `mobile-render` | url | template, overlay_viewport_share (0–1), overlay_kind, raw_primary_words, rendered_primary_words | Q95 |
| `listing-controls` | url, control | template, element, changes_listing, crawlable_href | Q38 |
| `image-resources` | image_url, content_type | page_url, in_content | Q66 |
| `locale-probe` | url, variant | baseline_status, variant_status, baseline_location, variant_location (null when there is no Location header), primary_content_differs (visible text of `<main>` or `<body>`, scripts and attributes ignored, null unless a repeated header-less control matched; raw_body_differs is review-only); a probe is clean only when all five are recorded. A status of 0 or null means the request was never answered (fetch error, timeout, robots or scope rejection; see baseline_failure/variant_failure), so that variant is untested, never a status change | Q25 |
| `host-probe` | host | status, content_type (unknown when null, so a 200 is a candidate for review, not an Issue), auth_required, noindex, canonical_to_main_host, robots_blocked, discovered_via | Q27, Q77 |
| `utility-path-probe` | url | path_class (`protected` or `public-utility`, from the approved policy), status, auth_required, exposes_content, noindex, robots_blocked (a public-utility path needs both noindex and robots_blocked recorded) | Q102 |
| `external-link-recheck` | source_url, target_url | status, rel (required for an affiliate link; null when the anchor has none), affiliate | Q28 |
| `tls-probe` | host | hsts_header (null when absent), preload_status, ocsp_stapled | Q63 |
| `robots-txt` | host; plus an integer status, or `fetch_outcome: "unknown"` with an `unknown_reason` and no status | body (required with a 2xx status; a 404 or 410 means no file and allows everything; a redirect, any other 4xx or a 5xx is unread), llms_txt_status | Q96 |
| `google-render-inspection` | url, template, tool | primary_content_present, blocked_resources, render_error | Q18 |
| `verified-google-fetch` | url | content_differs, links_differ, directives_differ (all three must be recorded for a matching fetch), google_fetch_method | Q31 |
| `competitor-topic-gap` | topic, site_covers, competitors_covering | query, method | Q50 |
| `search-host-review` | review_type, reviewed_at, permitted_hosts | date_range, unapproved_hosts, queries | Q104 (recorded only) |

Q104 is a manual review. A `search-host-review` record documents it, but the
runner always leaves Q104 Pending and never drafts a ticket for it.

## Status rules

- Heuristic questions (Q29, Q33, Q35, Q38, Q68, Q69, Q95) answer at most Needs
  validation and never draft a ticket.
- Template-unit questions count templates. Pages are grouped by the record's
  `template`, then by the first matching site-profile template, then by their
  first non-locale path segment (so /ar/casino/ and /casino/ group together); the answer notes when grouping fell back to the path.
- Supplied-input questions (Q18, Q30, Q31, Q50) classify the supplied records
  only. They do not claim that crawler_cli queried Google or observed all
  search results.
- A failed Q26 run gate downgrades every observed Yes answer to Needs validation.
