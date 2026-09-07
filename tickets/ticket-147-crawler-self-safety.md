# Ticket 147: Crawler self-safety — session-mutating URLs and robots confirmation

> **Reconstructed 2026-09-07.** This file was created empty on 2026-08-26 and
> never written; it has no content in git history. It is rebuilt from the only
> surviving record of this ticket's scope — the *Adversarial crawler ticket
> review brief 2026-08-21* (`### 147 — Crawler self-safety`, the wave-2 exit
> gate, the shared admission sequence, and the 132/134 interaction notes) plus
> the register entry for 147.
>
> That brief is a **review recommendation, not an approval**: its disposition
> section is headed "Final review disposition proposed" and its reviewer
> decision checkboxes are unchecked. Treat it as the surviving scope record,
> not as sign-off.
>
> This file mixes two kinds of content, labelled throughout:
>
> - **Reconstructed scope** — restatement of the brief or the register, cited
>   in `RECONSTRUCTION-PROVENANCE-145-147.md`. Normative once approved.
> - **Proposal (not approved)** — written during reconstruction to make the
>   scope actionable. **Not** derived from any source, and not normative.
>   Marked inline.
>
> The brief wins on any conflict. Re-approve before implementing.

## Goal

Stop the crawler from acting on the site it is measuring. An authorised
evidence crawl must not log itself out, empty a cart, trigger a subscribe or
unsubscribe, or otherwise mutate session or account state by following an
ordinary link — and it must not quietly ignore robots without the operator
saying so.

This protects the crawled site and the operator's own session. It is not a
scanner, and it is not an evasion feature.

## Background

The review corrected an earlier assumption: `extract_links()` already accepts
only HTTP(S) anchors, and the crawler does not submit forms. Those are existing
properties. This ticket **regression-locks** them rather than presenting them as
new work.

The genuinely new work is a boundary-aware session-mutating URL policy applied
across every URL source and every redirect, an explicit robots confirmation,
narrow overrides, typed skip counts with provenance, and correct budget
treatment for rejected URLs.

## Behavior contract

### Session-mutating URL policy

- Apply the policy to every URL source: seeds, discovered links, sitemap
  entries, speculative/JS/CSS discovery, probes, and every redirect hop. A URL
  admitted at one source must not bypass the policy at another.
- **Rules must understand path and query boundaries.** The review names broad
  substring matching as the principal risk: it creates damaging false
  positives on benign editorial URLs. `/logout` as a path segment is a
  signout; `/blog/how-we-built-logout-flows` is an article. Ship benign
  editorial fixtures that must not be rejected.
- **A rule needs evidence of mutating semantics, not a suggestive noun.** A
  path segment naming a feature is not evidence that requesting it mutates
  anything. Admissible evidence is an exact known endpoint, or an explicit
  action parameter (for example `?action=delete`, `?logout=1`), or a
  site-specific rule the operator supplies. A bare noun is never sufficient.
- Provide narrow overrides so an operator crawling their own staging system can
  permit a specific pattern, in the spirit of ticket 149's exception: explicit,
  recorded, and never a blanket "ignore this policy" switch.

> **Proposal (not approved) — candidate rule set.** The brief says
> "session-mutating" without enumerating, so no rule list is sourced. The
> obvious nouns are actively dangerous as path-segment rules and are recorded
> here as a warning rather than a starting point:
>
> `/cart`, `/checkout`, `/subscribe` and preference paths **routinely serve
> safe, valuable GET pages**. A cart page, a checkout landing page and a
> subscription plans page are ordinary indexable content, and this is an
> ecommerce SEO crawler. Matching those segments would suppress exactly the
> pages the product exists to measure — a worse outcome than the risk it
> avoids.
>
> Sign-out is the one case where the segment itself is strong evidence, because
> `/logout` is conventionally an action rather than a page. Even there, prefer a
> known endpoint or an action parameter.
>
> Recommended default: ship **no** noun-based rules. Start from operator-supplied
> endpoints plus explicit action parameters, and add a built-in rule only with a
> fixture proving it does not suppress a benign page. Requires review before it
> becomes scope.

### Robots confirmation

- Ignoring robots must be an explicit, confirmed decision, consistent with the
  existing `--ignore-robots` / `--confirm-ignore-robots` / manifest triple gate
  already implemented for ticket 148.
- This ticket regression-locks that gate and extends it where robots handling
  is bypassed by any other path.

### Evidence

- A rejected URL is a **typed skip with provenance**, not a fetch error and not
  a silent drop: which rule matched, which URL source it came from, and which
  hop. It records zero HTTP status because no request is made.

  *Implementation guidance, not sourced scope:* `engine.py` already has two
  precedents for exactly this shape — `scope_manifest_denied:<reason>` and
  `destination_denied:<reason>`, both typed skips with status 0 that
  deliberately do not feed the circuit breaker. Follow them.
- Report typed counts per rule so an operator can see what the policy cost them.

### Budgets

- Correct budget treatment: a URL rejected by policy must not consume the
  useful-page budget. The review is explicit — *"do not let rejected URLs
  exhaust the useful-page budget silently"* — and flags ticket 132's final
  successful-content/page budget semantics as the thing to coordinate with.

## Architecture

- Use the **shared ordered admission sequence** the brief specifies, at step 3:
  parse/normalize (1), ticket-148 scope (2), **this policy (3)**, ticket-149
  destination policy at connection time (4), robots/crawl-delay (5), budgets
  and breakers (6), fetch and repeat per redirect (7).
- Share a generic URL-admission interface with the Magento facet guard
  (ticket 134), but **do not merge the policies or their dependencies** — same
  interface, different rules and different product purpose.
- Reject any implementation that sprinkles checks through individual commands
  instead of the shared boundary, matching the architecture requirement the
  brief sets for 148.

## Test matrix

- Every URL source and every redirect hop is subject to the policy; a URL
  admitted at one source cannot bypass it at another.
- Benign editorial fixtures containing mutating words inside slugs are **not**
  rejected. This is the review's named risk and needs explicit coverage.
- **Benign commerce fixtures are not rejected**: a `/cart` page, a `/checkout`
  landing page and a `/subscribe` plans page must all still be crawled. Any
  proposed built-in rule must ship a fixture proving it does not suppress them.
- Rejection requires evidence of mutating semantics — a known endpoint, an
  explicit action parameter, or an operator-supplied rule. A bare substring or
  a suggestive path noun is not sufficient grounds.
- Rejections are typed skips with rule and source provenance and zero status,
  distinct from fetch errors, scope denials and destination denials.
- Rejected URLs do not consume the useful-page budget.
- Narrow overrides permit exactly what they name and nothing more.
- Regression locks: `extract_links()` still accepts only HTTP(S) anchors; the
  crawler still submits no forms; the robots confirmation gate still holds.

## Out of scope

- Form submission or any state-changing request. The crawler stays GET-only
  over HTTP(S).
- Evasion of bot management, or ignoring robots as a happy path.
- Merging with ticket 134's facet rules.
- Target-side vulnerability testing.

## Definition of Done

- One shared, boundary-aware session-mutation policy runs at the documented
  admission step for every URL source and redirect.
- Benign editorial URLs are demonstrably not rejected.
- Robots confirmation is explicit and regression-locked.
- Rejections are typed, counted, attributable to a rule and source, and do not
  consume the useful-page budget.
- The GET-only/no-forms properties are locked by tests rather than assumed.

## Status

proposed (Priority: **P1/safety**, depends on completed **144**; strict-mode
integration uses **148**. Reconstructed 2026-09-07 from the 2026-08-21 review
brief — re-approve the scope before implementing. Coordinate budget semantics
with **132**; share the admission interface with **134** without merging it.)
