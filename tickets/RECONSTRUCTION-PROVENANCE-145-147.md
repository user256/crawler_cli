# Provenance: reconstructed tickets 145 and 147 (2026-09-07)

This file exists so the reconstruction can be QA'd claim by claim rather than
taken on trust. Every substantive line in the two rebuilt ticket files is
mapped to its source below.

## Why a reconstruction was needed

`tickets/ticket-145-client-split-measurement.md` and
`tickets/ticket-147-crawler-self-safety.md` were both 1 byte. They were created
on 2026-08-26 and never written:

```
$ git log --all --oneline -- tickets/ticket-147-crawler-self-safety.md
(no output — no content in history)
```

`tickets/` is gitignored, so a ticket file only enters the repository when
someone runs `git add -f`. These two reached `master` empty.

## Sources used

1. **`tickets/adversarial-crawler-ticket-review-brief-2026-08-21.md`** — the
   reviewed and approved scope. Line numbers below refer to this file at
   md5 `31f7ff54b457dc12d90e3605e01c2600`, 25214 bytes, mtime 2026-08-21 12:05.

   **This file was itself untracked and had never been committed.** It is added
   to git in this change, because it is the only surviving record of the
   approved scope and the register already links to it.

2. **`tickets/ticket-queue.md`** — the register one-liners: line 539 for 145,
   line 541 for 147.

No other source was used. Nothing was inferred from the codebase, and nothing
was invented to fill a gap.

## Ticket 147 — claim-by-claim

| Reconstructed claim | Source |
| --- | --- |
| P1 scope, "approve corrected" | brief 227 |
| `extract_links()` already HTTP(S)-only; no form submission; this ticket *regression-locks* rather than adds them | brief 229, and brief 59–63 which states the correction explicitly |
| New work = boundary-aware session-mutating URL policy across every URL source and redirect, explicit robots confirmation, narrow overrides, typed skip counts/provenance, correct budget treatment | brief 231–233 |
| Broad substring rules cause damaging false positives; rules must understand path/query boundaries; ship benign editorial fixtures | brief 235–236 |
| Share a generic URL-admission interface with ticket 134 but do not merge policies or dependencies | brief 238–239 |
| Admission ordering, with this policy at step 3 of 7 | brief 400–410 |
| Wave-2 exit gate: all URL sources use a shared admission sequence | brief 139–145 |
| Rejected URLs must not silently exhaust the useful-page budget; coordinate with 132 | brief 456–458 |
| Depends on 144; strict-mode integration uses 148 | register 541 |

### Written by me, not from a source

- The **worked example** distinguishing `/logout` as a path segment from
  `/blog/how-we-built-logout-flows`. The brief states the boundary rule and the
  false-positive risk; the illustration is mine.
- The **candidate rule list** (sign-out, cart/checkout, subscribe/unsubscribe,
  destructive account actions). The brief says "session-mutating" without
  enumerating. Treat this list as a proposal to review, not as approved scope.
- The wording that rejections follow the existing `scope_manifest_denied:` and
  `destination_denied:` precedents in `engine.py`. The brief requires "typed
  skip counts/provenance"; naming those two precedents is my choice, based on
  what now exists in the code.

## Ticket 145 — claim-by-claim

| Reconstructed claim | Source |
| --- | --- |
| Approve with the controlled-measurement contract | brief 191–192 |
| Hold constant: same URL, egress, cookies/auth, headers, limits, time window; only the declared client dimension changes | brief 194–195 |
| No challenge escalation or proxy rotation inside the matrix | brief 195–196 |
| Spoofed bot output always carries the non-proof field | brief 196–197 |
| Normal backend retry blurs the exact request count; require an attempt ledger; prohibit identity/egress changes on retry | brief 199–200 |
| Size M; one command, pure classifier, JSON contract, fixture-server tests; no PostgreSQL persistence in the first PR unless the contract is stable | brief 202–204 |
| Plain vs impersonate vs spoofed-bot UA matrix; no retry-on-403; spoofed Googlebot is not Googlebot | register 539 |
| Depends on 144, 148, 149, 153 | register 539 |

### Known unrecoverable gap

Brief line 191 says the contract is *"now in the ticket"* — meaning the ticket
once held detail the brief did not repeat. That detail is gone. The
reconstruction records the properties the brief lists and says so explicitly
rather than inventing the missing specifics.

### Written by me, not from a source

- Framing "no retry-on-403" as an instance of the ticket-144 evasion boundary.
  Both facts are sourced; connecting them is mine.

## How to QA this

- `sed -n '189,205p'` and `sed -n '225,240p'` on the brief cover the two ticket
  sections in full; they are short enough to read whole.
- The "written by me" lists above are where to concentrate. Everything else is
  a restatement of a cited line.
- Both ticket files keep `proposed` status and carry a banner saying they are
  reconstructions and that the brief wins on any conflict.
