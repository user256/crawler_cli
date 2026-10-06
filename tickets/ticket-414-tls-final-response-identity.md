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

- [ ] Join the run snapshot's final_url_id to urls and pass final_url to the transport report.
- [ ] Select/classify by the observed response scheme; retain requested URL separately as provenance.
- [ ] Cover cross-host redirects, HTTP-to-HTTPS, HTTPS-to-HTTP and multiple requested aliases of one final host; never infer the source host's policy from the destination.

## Status

proposed (Priority: **P1**). Filed by post-merge QA, 2026-10-06.
Related existing tickets: 362, 409. This records a fix request; no product fix has been applied.
