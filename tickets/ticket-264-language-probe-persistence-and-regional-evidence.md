# Ticket 264: Persist language probes and add regional comparison evidence

**Status:** Open — remediation from concluded ticket 260.
**State:** Open
**Priority:** P1
**Module:** technical-audit

Persist every explicit Accept-Language probe under its originating crawl run without mutating the crawl frontier, including denied, timeout, redirect, and successful evidence. Add an opt-in configured regional-proxy comparison with an explicit authorisation/scope contract. Never infer geo behaviour from a header-only result.

## Acceptance criteria

- [ ] Two crawl runs cannot read each other's language-probe rows.
- [ ] Stored evidence exactly preserves request variant, response chain, coverage, and qualification.
- [ ] Regional evidence is clearly separate from Accept-Language-only observations and is never collected without explicit configuration.
