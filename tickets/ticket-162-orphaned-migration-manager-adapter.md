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
3. **Part of it duplicates open work — but less of it than first appeared.**
   A detailed comparison against `master` (2026-09-07) narrowed the harvestable
   surface considerably:

   - `master` already has the *mechanism*. `AiohttpBackend.fetch_for_purpose`
     (`backends.py`) is a per-hop redirect loop that calls
     `validate_pinned_connection()` and fetches through a one-shot pinned
     connector, and `master`'s `_PinnedResolver` is strictly better than the
     branch's (it checks the port and defaults to `AF_UNSPEC`). Porting the
     branch's `SafeHttpClient` would add a second, worse fetch path.
   - What `master` lacks is the *decision*: `portal_policy.py` is only the seam,
     delegating the choice to Portal. The branch's address-class policy and its
     `_system_resolve` helper are the genuinely reusable parts.
   - The branch's capability manifest is **dishonest by ticket 149's standard**.
     Its `CAPABILITIES` dict claims `browser_navigation: True` and
     `browser_subresource: True` for a build with no browser runtime at all.
     `master`'s `policy_capabilities()` is the honest version. This is a reason
     not to revive the manifest, not merely to update it.

   So the overlap with ticket **149** (`default-network-ssrf-safety`, P1, still
   `proposed`) is the address-class table, the per-hop re-resolution discipline,
   and above all the branch's *tests*.

## Behavior contract

This ticket produces a decision and a record, not a merge. The adapter must not
be merged to `master` as-authored, because doing so would publish a worker entry
point that instructs an integrator to pin an excluded release and that asserts a
frozen `schema_version: 1` capability manifest never reviewed against the
144–161 contracts.

The recommended disposition is to **harvest, then retire**:

- treat `portal_adapter.py` as reviewed prior art for ticket **149**, not as a
  module to land. Carry forward its address-class table, its `_system_resolve`
  helper, its per-hop re-resolution discipline, and its "reject the complete
  answer set if any address is denied" rule. Do **not** carry its
  `SafeHttpClient`, its `_PinnedResolver`, or its `_origin` helper — `master`
  already has better versions of all three;
- carry across `tests/test_portal_adapter.py`'s rebinding cases specifically.
  `test_every_connection_reresolves_and_pins_the_validated_answer` and
  `test_redirect_to_private_is_rejected_before_second_connection` assert that
  the second socket is never opened against a rebound answer, and
  `test_mixed_dns_answer_set_fails_closed` asserts a mixed answer set is denied
  as a unit rather than narrowed to its public member. These are the highest-
  value artifacts on the branch;
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
