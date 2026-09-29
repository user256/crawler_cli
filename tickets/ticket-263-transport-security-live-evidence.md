# Ticket 263: Complete transport-security live evidence

**Status:** Open — remediation from concluded ticket 259.
**State:** Open
**Priority:** P2
**Module:** technical-audit

Implement an optional, destination-guarded TLS inspector that can request and verify stapled OCSP responses without reporting absence as failure. Add an authoritative, reproducible HSTS preload-list membership source. Keep unknown/unavailable evidence distinct from `not_stapled`, with local TLS fixtures and no default third-party calls.

## Acceptance criteria

- [ ] Stapled, non-stapled, unsupported, and unavailable TLS fixtures remain distinct.
- [ ] Preload membership names its pinned source/version and observation time.
- [ ] The existing HSTS-only report remains compatible.
