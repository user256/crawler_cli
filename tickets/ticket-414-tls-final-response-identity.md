# Ticket 414: Attribute stored TLS headers to the final response host

## Goal

Restore the evidence and coverage contract for Q63 after PR #118.

## Problem

The stored TLS producer can attribute the destination host's HSTS header to the originally requested host after a cross-host redirect. It can also exclude an HTTP seed that finishes on HTTPS, or treat an HTTPS-to-HTTP result as HTTPS evidence.

## Cause and evidence

`CrawlReports.https_response_headers` selects u.url, final_status_code and headers_json from the requested URL join and filters u.url by https. It omits the final_url_id join. `transport_security_report` supports final_url but falls back to u.url, although the saved headers are final-response headers.

Redirect fixture: https://old.example/ -> https://new.example/, final HSTS max-age=300. Production column projection produces host old.example; supplying the retained final response URL correctly produces new.example. The snapshot schema retains final_url_id.

Reproduced on merged master `72629af137e0803aface1f4ce94a9a18ba7f0eb1`.
Run `PYTHONPATH=src python tickets/qa-new-audit-2026-10-06/reproduce.py` from the repository root. See result key `414` in [captured results](./qa-new-audit-2026-10-06/results.json).

## Tasks and acceptance criteria

- [x] Join the run snapshot's final_url_id to urls and pass final_url to the transport report.
- [x] Select/classify by the observed response scheme; retain requested URL separately as provenance.
- [x] Cover cross-host redirects, HTTP-to-HTTPS, HTTPS-to-HTTP and multiple requested aliases of one final host; never infer the source host's policy from the destination.

## Status

done (Priority: **P1**). Fixed on branch `fix/postmerge-qa-tls`, 2026-10-07.

Fix: `CrawlReports.https_response_headers` now joins `page_run_snapshots.final_url_id` to `urls` and returns `requested_url` and `final_url`; it filters on the final response's scheme (`lower(fu.url) LIKE 'https://%'`), so an HTTP seed that ends on HTTPS is included and an HTTPS seed that ends on HTTP is not. `transport_security_report` takes scheme and host only from `final_url`, keeps the requested URLs as `requested_urls` provenance on each host row, and adds `response_identity_unknown_rows` and `hsts_attribution` to the coverage row.

Decision (conservative): a row with no retained final URL is counted as `response_identity_unknown_rows` and not attributed. It no longer falls back to the requested URL. The same applies to a snapshot whose `final_url_id` is NULL, because the inner join leaves it out. A redirecting source host gets no HSTS row unless it has a final response of its own.

Tests: `tests/test_transport_security.py` covers the cross-host redirect, a source host that is not inferred from its destination, HTTP-to-HTTPS, HTTPS-to-HTTP, several aliases ending on one final host, and the old projection with no final URL. `tests/test_tls_final_response_identity.py` covers the SQL contract and a PostgreSQL round-trip. The round-trip test is skipped without `CRAWLER_CLI_TEST_DSN` and was not run locally. In `reproduce.py`, key 414 `production_projection` is now `[]`, and `with_response_identity` gives `new.example`.
