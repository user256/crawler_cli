# Ticket 162: Orphaned Migration Manager adapter branch (3350) — triage and disposition

## Goal

Decide, and record, what happens to the unmerged Portal Migration Manager
adapter on `feature/3350-portal-url-policy-v1`. It is the only branch in the
repository holding substantial work that is genuinely absent from `master`, it
is pinned to a release that was permanently excluded, and its strongest
component duplicates work that ticket 149 still has open. Leaving it
undocumented on a branch is the risk this ticket closes.

## Background

A status sweep on 2026-09-07 compared every local and remote branch against
`master` by patch identity. Every other branch is either fully merged or holds
only squash-merge noise. One is not:

- `feature/3350-portal-url-policy-v1`, single commit `8fcdb54`
  "feat(portal): add guarded migration crawler adapter", authored 2026-07-28,
  branched from `master` at 2026-07-21, never opened as a pull request.

It adds, and `master` does not contain:

- `src/crawler_cli/portal_adapter.py` (855 lines) — a `migration-manager-crawler`
  worker entry point with `--capabilities` and `--config-fd N`, a
  `migration-manager/crawl-dispatch/1` request envelope, a
  `migration-manager/run-result/1` result envelope, and a fail-closed
  resolve-validate-pin connection loop applied before every page, robots,
  sitemap, and redirect-hop socket;
- `tests/test_portal_adapter.py` (406 lines);
- `docs/portal-migration-manager-adapter.md` (74 lines).

Three facts make it unmergeable as it stands:

1. **It targets a dead release.** The module hard-codes `CRAWLER_VERSION =
   "0.2.1"` and `CRAWLER_RELEASE = "crawler-cli@v0.2.1"`, and its documentation
   instructs Portal to pin `crawler-cli==0.2.1`. Per ticket 130 and the
   register, the remote `v0.2.1` tag points at closed, unmerged PR #50, is not
   an ancestor of `master`, and is permanently excluded. Shipped releases are
   `v0.2.0`, `v0.2.2`, and `v0.3.0`.
2. **Its contract baseline is superseded.** The branch predates the entire
   144–161 lane. Its merge-base is 2026-07-21, before ticket 144 (product
   scope), 148 (authorisation and scope manifest), 153 (security evidence and
   redaction), 155–158 (URL discovery), 159, and 160/161. A three-dot diff is
   therefore misleadingly large: most of it is `master` moving on, not the
   branch changing anything.
3. **Its best part is a duplicate of open work.** The adapter's address-class
   policy — globally routable only for SaaS, RFC1918 and IPv6 ULA only under an
   explicit `allow_private_network`, and loopback, link-local and metadata,
   reserved, multicast, and unspecified always forbidden — plus its
   re-resolve-and-pin-per-hop rebinding defence, is substantially the behaviour
   ticket **149** (`default-network-ssrf-safety`, P1, still `proposed`)
   specifies. `master`'s `portal_policy.py` (146 lines) is only the seam: it
   defines `PinnedConnection` and delegates the decision to Portal. It contains
   no address-class policy of its own.

## Behavior contract

This ticket produces a decision and a record, not a merge. The adapter must not
be merged to `master` as-authored, because doing so would publish a worker entry
point that instructs an integrator to pin an excluded release and that asserts a
frozen `schema_version: 1` capability manifest never reviewed against the
144–161 contracts.

The recommended disposition is to **harvest, then retire**:

- treat `portal_adapter.py` as reviewed prior art for ticket **149**, not as a
  module to land. Its address-class table, its per-hop re-resolution, and its
  "reject the complete answer set if any address is denied" rule are the parts
  worth carrying forward, and its tests are worth reading as a specification of
  the rebinding cases to cover;
- keep the branch and this ticket as the durable pointer to it, so the work is
  findable without being on `master`;
- do not revive the `migration-manager-crawler` entry point, the dispatch
  envelope, or the capability manifest without a fresh contract ticket, a
  supported release to pin, and a Portal-side consumer that actually wants them.

If, instead, Portal does still want the worker entry point, this ticket becomes
the parent of that work and the following must all be true before any merge:
the pinned release is a shipped one, the capability manifest is re-derived from
the current authorisation and scope manifest rather than restated, the result
envelope is checked against the ticket 153 redaction contract, and the
connection guard is the one ticket 149 lands rather than a second private copy.

## Implementation tasks

1. Record the branch, its commit, and this disposition in the register so the
   next status sweep does not have to rediscover it.
2. When ticket 149 is implemented, read `portal_adapter.py` and
   `tests/test_portal_adapter.py` first and carry the address-class policy and
   the per-hop re-resolution across, with attribution to `8fcdb54`.
3. Once 149 has landed the guard, confirm nothing else on the branch is wanted
   and close this ticket, leaving the branch as history.

## Test matrix

- No production code changes, so no new tests. The claim that the branch is the
  only genuinely unmerged work is reproducible with
  `git cherry master <branch>` across every branch, and the claim that
  `portal_adapter.py` is absent from `master` with
  `git show master:src/crawler_cli/portal_adapter.py`.

## Out of scope

- Merging `feature/3350-portal-url-policy-v1`.
- Implementing ticket 149. This ticket only records that 149 has prior art.
- Reviving, re-tagging, or otherwise rehabilitating `v0.2.1`.
- Any change to the frozen portal integration contract.

## Definition of Done

- The orphaned adapter is registered, with its commit, its release-pin defect,
  and its relationship to tickets 130 and 149 written down.
- Ticket 149 records that reviewed prior art exists and where.
- No branch holding substantial unmerged work is undocumented.

## Status

proposed (2026-09-07, Priority: **P2**; relates to completed 130 and to
proposed 149)
