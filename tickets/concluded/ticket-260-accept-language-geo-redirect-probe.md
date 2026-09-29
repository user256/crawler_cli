# Ticket 260: Accept-Language variation and language-redirect probe

**Status:** Concluded with remediations 264 — merged to `master` after review on 2026-09-29.
**State:** Needs closing
**Priority:** P2
**Module:** technical-audit

## Delivered

- Bounded, guarded probes for no header, wildcard, and six locale headers over deterministic homepage and locale-root targets.
- Records response status, redirect hops, final URL, `Vary`, cookies, and content-difference evidence in the audit export.
- Emits qualified `language_redirect_detected`, `missing_vary_header`, and `bot_trap` candidates.

## Deferred

Run-scoped persistence and a configured regional-proxy comparison are deliberately not claimed by this implementation; ticket 264 owns both gaps.

## Review evidence

`tests/test_accept_language_audit.py` passed; full integrated suite: 1,615 passed, 60 skipped.
