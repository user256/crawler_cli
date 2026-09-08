# Ticket 145: Client-split measurement

> **Reconstructed 2026-09-07.** This file was created empty on 2026-08-26 and
> never written; it has no content in git history. It is rebuilt from the only
> surviving record of this ticket's scope — the *Adversarial crawler ticket
> review brief 2026-08-21* (`### 145 — Client-split measurement`) plus the
> register entry for 145.
>
> That brief is a **review recommendation, not an approval**: its disposition
> is headed "Final review disposition proposed" and its reviewer decision
> checkboxes are unchecked.
>
> Everything below restates the brief or the register, cited in
> `RECONSTRUCTION-PROVENANCE-145-147.md`. The brief notes a
> "controlled-measurement contract now in the ticket" that is not recoverable,
> so this is a faithful summary of what survives rather than the original.
> Approve before implementing.

## Goal

Measure whether a site serves different content to different clients, under
controlled conditions strict enough that a difference is attributable to the
client dimension and nothing else.

This is evidence about the site's behaviour. It is **not** an evasion tool and
not a way to find a client that gets through.

## Behavior contract

### The controlled-measurement contract

Every cell of the matrix holds these constant, and only the declared client
dimension varies:

- the same URL;
- the same egress;
- the same cookies and authentication;
- the same headers apart from the dimension under test;
- the same limits;
- the same time window.

Consequences the review states explicitly:

- **No challenge escalation inside the matrix.** Escalating one cell to a
  browser changes more than the declared dimension.
- **No proxy rotation inside the matrix.** Egress is a controlled variable.
- **No retry-on-403.** The register requires this explicitly: a 403 is a result,
  not a problem to route around.

### The dimension

Plain client versus impersonating client versus spoofed bot user-agent, as the
register describes. Spoofed bot output **always** carries the non-proof field:
sending a Googlebot user-agent does not make the observation evidence of
Googlebot treatment, and the output must say so in the payload rather than only
in documentation.

### Attempt ledger

The review's named concern is that ordinary backend retry behaviour blurs the
exact request count, which would make a "same conditions" claim untrue.

- Keep an attempt ledger recording every request actually made per cell.
- **Prohibit identity and egress changes on retry.** A retry that changes the
  client dimension silently invalidates the comparison.

## Implementation notes

- One command, a pure classifier, and a versioned JSON contract.
- Fixture-server tests.
- **Do not add PostgreSQL persistence in the first PR** unless the contract is
  stable — the review is explicit about this sequencing.

## Test matrix

- Each cell holds URL, egress, cookies/auth, headers, limits and time window
  constant; only the declared dimension differs.
- Challenge escalation and proxy rotation are unavailable inside the matrix.
- A 403 is recorded as a result; no retry changes identity or egress.
- The attempt ledger reconciles exactly with the requests made.
- Spoofed-bot cells always carry the non-proof field.

## Out of scope

- Retrying identities until one succeeds, rotating to defeat bot management, or
  any definition-(1) evasion loop (ticket 144).
- Claiming an observation proves how a named crawler is treated.
- PostgreSQL persistence in the first delivery.

## Definition of Done

- A bounded client matrix runs under the controlled-measurement contract.
- The attempt ledger proves the conditions actually held.
- Spoofed-bot output cannot be read as proof of that bot's treatment.

## Status

proposed (Priority: **P2**, depends on **144**, **148**, **149** and **153**;
149 is now done. Reconstructed 2026-09-07 from the 2026-08-21 review brief —
re-approve the scope before implementing. Suggested size M.)
