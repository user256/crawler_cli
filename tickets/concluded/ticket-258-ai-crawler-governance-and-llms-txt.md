# Ticket 258: AI search crawler governance and /llms.txt audit check

**Status:** Concluded — merged to `master` after review on 2026-09-29.
**State:** Needs closing
**Priority:** P2
**Module:** technical-audit

## Delivered

- Evaluates declared `robots.txt` posture for the nine specified AI crawler families.
- Boundedly checks `/.well-known/llms.txt`, `/llms.txt`, and `/llms-full.txt`, including HTML soft-404 detection and Markdown/title evidence.
- Publishes qualified AI-governance observations and candidates in the technical-audit JSON and report views.

## Review evidence

- `tests/test_ai_governance.py` and report CLI coverage passed.
- Full integrated suite: 1,615 passed, 60 skipped (2026-09-29).
