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
   surviving review recommendation and scope record. Line numbers below refer
   to this file at md5 `31f7ff54b457dc12d90e3605e01c2600`, 25214 bytes, mtime
   2026-08-21 12:05.

   **It is not a record of approval.** Its disposition section is headed
   "Final review disposition **proposed**" (line 592), it *requests* approval
   ("Approve now: 144, corrected 147, 148, 149, and 153 ... subject to the
   explicit reviewer decisions above", 594–595), and the reviewer decision
   checkboxes above it are **unchecked** (585–590, including
   "- [ ] Approve implementation order 144 → 148+153 → 149+147"). So it records
   what a reviewer recommended, not what was signed off. Both reconstructed
   tickets stay `proposed` for that reason.

   **This file was itself untracked and had never been committed.** It is added
   to git in this change, because it is the only surviving record of the
   surviving scope record for both tickets and the register already links to it.

2. **`tickets/ticket-queue.md`** — the register one-liners: line 539 for 145,
   line 541 for 147.

### Authoritative versus non-authoritative

Those two are the **authoritative scope sources**: everything normative in the
reconstructed tickets traces to them, and nothing was invented to fill a gap in
either.

They are not the only material in the files. Two other kinds appear, both
labelled inline and both **non-authoritative**:

- **Implementation guidance derived from the current codebase** — the
  `scope_manifest_denied:` / `destination_denied:` typed-skip precedents in
  `engine.py`, and the existing
  `--ignore-robots` / `--confirm-ignore-robots` / manifest triple gate named in
  147's robots section. These describe what the code does today. They are
  offered as the obvious way to satisfy a sourced requirement, not as scope.
- **Reviewer-authored proposals** — listed per ticket below. Not derived from
  any source, explicitly marked "Proposal (not approved)" in the ticket files.

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
- The **"evidence of mutating semantics" requirement** — that a rule needs an
  exact known endpoint, an explicit action parameter, or an operator-supplied
  rule, and that a suggestive path noun is never sufficient. The brief requires
  path/query boundary awareness; this sharper requirement is mine, added after
  review found that a noun-based rule set is itself the hazard.
- The **candidate rule set**, now recorded as a *warning* rather than a
  starting point. An earlier draft of this file listed sign-out, cart,
  checkout, subscribe and preference paths as segments to match. That was
  wrong and is corrected: `/cart`, `/checkout` and `/subscribe` routinely serve
  safe, valuable GET pages, so matching those segments would suppress exactly
  the ecommerce pages this crawler exists to measure. Marked "Proposal (not
  approved)" and requires review before it becomes scope.

### Implementation guidance, from the codebase rather than a source

- Rejections following the existing `scope_manifest_denied:` and
  `destination_denied:` typed-skip precedents in `engine.py`. The brief
  requires "typed skip counts/provenance"; naming those two is my choice.
- The existing `--ignore-robots` / `--confirm-ignore-robots` / manifest triple
  gate named in the robots section. The brief requires "explicit robots
  confirmation"; the specific flags are what the code already implements.

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
  Both facts are sourced; connecting them is mine. Offered as implementation
  guidance, not as scope.

## How to QA this

- `sed -n '189,205p'` and `sed -n '225,240p'` on the brief cover the two ticket
  sections in full; they are short enough to read whole.
- The "written by me" and "implementation guidance" lists above are where to
  concentrate. Everything else is a restatement of a cited line.
- In the ticket files, anything inside a "Proposal (not approved)" block is
  mine and is not scope. Everything outside those blocks traces to a citation
  in the tables above.
- Both ticket files keep `proposed` status and carry a banner saying they are
  reconstructions and that the brief wins on any conflict.
