## Ticket queue
A list of tickets, their status and the md file which summarises action taken for subsequent review.

**Authoritative register** for status, acceptance notes, and delivery order.
Ticket files remain the source of truth for scope and DoD.

### Current position (2026-10-02, template question runner)

- The 96 Questions-tab questions of the audit template are now a registry
  (`templates/technical-audit-questions.json`, review copy
  `docs/technical-audit-questions.md`). Every question reads Yes = problem
  with a deterministic `issue_if` rule and a why-it-matters summary.
- Ticket **263** (`technical-audit-questions`) answers 11 of them today from
  a saved audit JSON; the rest are Pending with the reason. Detector batches
  **264** (stored HTML), **265** (site profile) and **266** (render, probes,
  external) move the remainder. Numbers 258–262 are skipped because they are
  in git history. Tickets 267–370 are the question-level queue; 371–399 are the Stream B,
  Stream C and integration QA fixes; next unreserved ticket number is **400**.
- The question-level queue is assigned to three agents by implementation seam:
  [Stream A: crawl and HTTP](./technical-audit-stream-a-crawl-http-2026-10-06.md),
  [Stream B: page indexability](./technical-audit-stream-b-page-indexability-2026-10-06.md)
  and [Stream C: render, probes and supplied evidence](./technical-audit-stream-c-render-probe-evidence-2026-10-06.md).

### Current position (2026-09-28, Rainbet audit delivery)

- **Immediate priority: finish the Rainbet audit ASAP.** Tickets **240–246**
  cover direct evidence/content corrections, outstanding checks, sheet layout
  and final QA. They have **no dependency on process or crawler fixes**.
- Tickets **247–253** are the separate QA/process follow-up, to start after
  audit delivery. Extend existing implementations and ticket owners rather
  than building another audit framework.
- **Client output rule:** do not populate the sheet where the answer is that
  nothing is wrong. Keep healthy/no-action checks internally; client rows
  contain actionable findings/material warnings, with material evidence gaps
  stated briefly in scope. Ticket **247** makes this a shared process rule.
- All fourteen tickets are **proposed**. Filing them does not claim the audit
  has been corrected or the process changes implemented.
- Full ticket links, execution order and finding coverage:
  [Rainbet immediate delivery and process follow-up](./rainbet-audit-qa-two-track-2026-09-28.md).
- Existing tickets **238** (external outlink inventory) and **239** (security
  findings GUI) are preserved. Ticket **257** records the missing run-scoped
  custom-probe persistence contract exposed by the Rainbet GUI. Next
  unreserved ticket number is **258**.

### Current position (2026-09-28, deterministic-check QA)

- The shared technical-seo-audit skill now states a 44-row deterministic
  contract. Ticket **226** is implemented locally: `technical-audit` schema v2
  emits the identical ordered `checks[]` set, with `pass`, `finding`,
  `partial`, `unavailable`, or `not_applicable` plus provenance. Static
  registry entries and section headings do not count as a run result.
- Tickets **227–231** own the reviewed saved-run defects: per-action gates and
  recipient output; qualified graph inventories; reproduced content/metadata
  metrics; transient status/image units; and legacy canonical/hreflang
  coverage. They reuse 164, 178, 181, 186, 187, 190, 191, 197, 206, 210, 218,
  220, 221 and 222 rather than duplicating their collector work.
- Tickets **232–237** own the structured-data/render and live-probe QA:
  feature-rule units; render/mobile/base-URL evidence; robots/sitemap fetch
  semantics; conditional request headers; URL variant/soft-404 verdicts; and
  qualified live rechecks. They reuse 193–196, 205, 208, 213–215 and 224.
- Tickets **227–237** remain proposed QA tickets. No collector, classifier, or
  live probe is claimed implemented by filing them. Next unreserved ticket
  number is **240**.
- Tickets **238–239** record the Rainbet GUI review: retain external-link
  inventory independently of crawl scope, and project actual run-scoped
  security findings rather than HTTP status failures. The GUI correction for
  external-link rows and HTTP transport screening is implemented locally;
  ticket 239's security-findings projection remains open.

### Current position (2026-09-25, QA follow-up)

- Sitemap-source QA is implemented in [PR #106](https://github.com/user256/crawler_cli/pull/106): admitted current sitemap URLs join the selected run graph, source labels persist into recipient JSON/Sheets, out-of-scope URLs stay excluded, and the full suite plus both CI workflows pass (1,503 passed, 58 skipped). Ticket 186's sitemap/source-union DoD is now covered in review; ticket 204 remains open pending merge and broader acceptance.
- Additional skill comparison gap filed as ticket **206**: join sitemap-declared hreflang with the existing HTML/HTTP check after crawler-side sitemap evidence is retained (ticket 164). Ticket **203** remains the per-requirement traceability follow-up; the section-level map is not yet exhaustive at requirement level.
- Ticket **207** hardens ticket 185: repeated or mixed inconclusive rechecks now remain `incomplete` instead of being mislabeled intermittent; regression is submitted in [PR #107](https://github.com/user256/crawler_cli/pull/107), with full suite, Ruff, format, and mypy passing.
- Ticket **208** extends ticket 194's rendered evidence with separate pre-scroll and bounded-scroll link observations in [PR #110](https://github.com/user256/crawler_cli/pull/110); scroll-only capture never activates controls and reports partial bounds explicitly. Interactive reveals and ticket 205's robots-purpose analysis remain open.
- Ticket **210** adds bounded rendered image/CSS-background measurements in stacked [PR #112](https://github.com/user256/crawler_cli/pull/112). Full local suite, real-Chromium smoke, and CI pass. It records measurement evidence only, not layout-impact findings.
- Ticket **211** submits bounded external-link rechecks in [PR #113](https://github.com/user256/crawler_cli/pull/113), stacked on PR #112. The feature requires rendered comparison and an explicit scope manifest; redacted results flow into JSON and a separate evidence-only Sheets tab. Full local suite passes (1,507 passed, 58 skipped), Ruff/mypy pass, and all 26 CI checks pass.
- Ticket **212** adds isolated loopback HTTP-fixture proof of ticket 211's real guarded-engine path in stacked [PR #114](https://github.com/user256/crawler_cli/pull/114). Robots denial, a scoped redirect, response truncation, redaction, and default loopback denial are tested. Focused tests (31 passed), full suite (1,510 passed / 58 skipped), Ruff, mypy, and all 26 CI checks pass.
- Coverage-map QA caught an in-progress ticket 200 test failure: 23 check IDs
  were absent from the section mapping. The mapping has been connected and its
  focused tests now pass.
- Further review caught a duplicate registry ID hidden by set-based coverage
  comparison. A uniqueness guard and duplicate removal are in [PR #109](https://github.com/user256/crawler_cli/pull/109),
  which contains only the five intended files; all 26 CI checks pass. The
  previous oversized draft #108 was closed as superseded.
- A separate DoD gap remains: ticket 200 maps a list of controls to one
  section-level check/evidence/owner row, while its acceptance criteria require
  per-requirement mapping. Ticket **203** owns that follow-up and depends on
  ticket 200; do not describe the map as requirement-level complete
  until 203 lands.
- Ticket **202** already owns non-production-host/HTTPS hygiene. The full test
  suite passes in the ticket-200 worktree: **1,501 passed, 58 skipped**.
- Ticket **204**'s sitemap/source-inventory implementation is submitted in PR
  #106; the Search Console/analytics CSV path is in PR #91. Ticket **205** owns
  rendered-link robots-rule/purpose classification and remains open.
- Ticket **209** records/fixes a Google Sheets auth-error handling defect in PR
  #94. The correction is submitted as stacked [PR #111](https://github.com/user256/crawler_cli/pull/111);
  all 26 checks pass, with focused CLI/Sheets tests, Ruff, format, and mypy
  green. Live Google publication remains outside this test evidence.
- Next unreserved ticket number is **226**. (213 is reserved by the `feature/technical-audit-213` render-guard branch.)

### Current position (2026-09-24)

- **Technical audit automation review:** tickets **183–199** are proposed,
  covering evidence correctness, complete check coverage, template publication
  and captured end-to-end proof. Reuse existing **178** for orphan detection
  and **179** for Playwright redirect evidence; do not duplicate those fixes.
- Delivery order and acceptance mapping are in the
  [technical audit delivery brief](./technical-audit-review-2026-09-24.md).
- The next unreserved number is **200**. This is a local ticket backlog;
  `tickets/` is ignored by the repository and no implementation is claimed.

### Current position (2026-09-23)

- **Register reconciliation.** The 2026-07-22 wiring audit was filed on disk
  as tickets 130–143, colliding with the already-assigned release and Magento
  lane. The audit lane is now **163–176**: 163 list-run isolation; 164 sitemap
  hreflang retention; 165 skip-budget semantics; 166 Playwright byte cap; 167
  Obscura auth/status parity; 168 browser per-host proxy selection; 169 UA
  precedence; 170 fresh challenge proxy; 171 rate-limit CLI/GUI wiring; 172
  GUI DSN hygiene; 173 GUI run-scoped graph; 174 refresh-days documentation;
  175 concurrency/skip-sitemaps drift; and 176 List max-pages semantics.
  The Magento tickets retain 131–134 and release ticket 130 remains closed.
- **Stale status closed:** ticket **146** shipped in PRs #80–#87; its
  `exposure-inventory` command and dedicated tests are present. Ticket **162**
  is complete: ticket 149 landed the relevant guard and the unmerged adapter
  remains documented prior art, not merge material.
- **New Shopify findings:** 177 raw HTTP sitemaps under `--js`; 178
  run-scoped inlink orphans; 179 Playwright redirect-status evidence; 180
  changed-seed resume intent; 181 429 versus challenge accounting; 182 system
  Chromium discovery. The next unreserved number is **183**.
- Cached `origin/master` is one commit ahead (`e652f99`, reconstructed tickets
  145 and 147). It has not been merged into this dirty working tree.

### Current position (2026-07-17)

- Ticket **122** (PR **#47**) is reviewed and **merged**: compare `--replace`
  host remapping, simhash tolerance, and the `compare-urls` redirect-mapping
  command. Two review bugs (root-URL redirect matching; source-side pair
  resolution by `final_url`) were fixed on the branch pre-merge; the
  store-loader blocker was cleared with a real-Postgres run of the DSN-gated
  integration test. The remaining compare review work is now recorded as
  implemented ticket **123**; ticket **127** adds separate DSN credential
  hygiene and remains in review.
- The 2026-07-16 batch is fully landed: 114–117 (PRs #36/#37/#38/#39),
  118/119 (GUI, PRs #42/#45), and 095+120 (run-aware snapshots, PR #44).
- Tickets **101–108** form the completed intent-overlap reporting baseline.
- Tickets **125** (GUI all-crawls DB access, `ee7ae6e`) and **124** (GUI crawl
  management, `13911e1`) are **done** (2026-07-17), landed in that order. The
  `crawler_gui/server.py` bridge is now tracked, paginates every run, tells the
  truth on legacy schemas, and can start crawls locally. A GUI Chrome-profile
  picker remains the planned follow-up recorded in 124 — the engine side already
  ships (`--playwright-user-data-dir` / `--playwright-channel chrome`).
- Ticket **110** remains unused/rejected; **127**, **128**, and **129** are implemented; next unreserved number is **130**.
- Leftover review worktrees (`/tmp/crawler_cli_pr33`, `/tmp/crawler_cli_pr44`)
  removed 2026-07-17.

### Current position (2026-07-20)

- Portal ticket **3344** (Migration Manager release/contract spike) landed the
  0.2.0 release-prep branch `agent/3344-release-contract`: golden contract
  suite (`tests/contract/`) freezing the `compare` / `compare-urls` / crawl
  artifact schemas (now stamped with explicit `schema_version` identifiers),
  security proofs for argv/log credential hygiene and redirect credential
  scoping, `--auth-token-env`/`--auth-token-file`, and the distinct
  `EXIT_FINDINGS` (3) `--fail-on` exit code. That closes two ticket **123**
  sub-items (CSV redirect-hops output; distinct `--fail-on` exit code) — the
  rest of 123 stays open.
- Ticket **129** filed: the Playwright backend applies auth as context-wide
  headers/`http_credentials` without origin scoping — excluded from the
  contract's security guarantees until fixed.

### Current position (2026-07-29)

- Ticket **130** is the release-safety lane for crawler-cli **0.2.2**. It
  prepares the reviewed HTTP-only `portal-url-policy/1` hook from PR #51 for a
  future immutable release: version/changelog, contract boundary, and artifact
  evidence checks only. It must not tag, publish, alter Portal, or enable a
  Migration Manager worker.
- The pre-existing remote **v0.2.1** annotated tag points to closed, unmerged
  PR #50 and is not an ancestor of `master`; it has no GitHub Release or
  artifacts. It is permanently excluded from the release sequence. The next
  safe release candidate is v0.2.2.

### Current position (2026-08-21)

- **Adversarial-crawler scope and authorised-evidence pass 144–154** filed
  after the sapiens.com audit. Detailed review brief:
  `adversarial-crawler-ticket-review-brief-2026-08-21.md`.

  `crawler_cli` is an evidence crawler (do not trust the CMS). It is
  **not** an evasion bot (rotate identities / bypass bot management / ignore
  robots as the happy path) and **not** a pentest scanner (injection, IDOR,
  forced browsing). Foundation order: **144 → 148 + 153 → 149**; ticket 147's
  ordinary-crawler safety can proceed after 144 but integrates 148 for strict
  modes. Evidence features **145–146 / 150–152 / 154** land only after their
  recorded foundations. Do not implement definition-(1) evasion loops; ticket
  137 stays “alternate proxy for an authorised fetch”, not “try identities
  until 200”.
- Magento hygiene **131–134** remains proposed (Timber Living). Disk already
  holds later wiring tickets **135–143** that this register had not yet
  listed; do not reuse those numbers.
- Ticket **155** is done: bounded static JavaScript URL candidate
  inventory plus explicit page-only following. It is a technical-SEO feature,
  not exact Googlebot emulation, and narrows the generic script-route slice of
  proposed ticket 151.
- Tickets **156–158** extend the URL-discovery lane. Ticket **159** specifies
  Google's single-pass JSON-LD entity compatibility. Ticket **160** turns the
  raw-versus-rendered primitives into a first-class parity audit; next
  unreserved ticket number is **161**. Do not reuse **110**.
  *(superseded 2026-08-25: 161 is filed; next is **162**.)*

### Current position (2026-08-12)

- Magento hygiene pass **131–134** filed from the Timber Living Yoma audit
  (`runs/yoma-20260810/timber-living-tech-audit.md`). Ticket 102 currently
  folds indexable-but-canonicalised filter URLs out of pairing — that hid the
  118k layered-nav finding. Order: 131 → 132 → 133; 134 after 131+132.
- Next unreserved ticket number is **135**. *(superseded 2026-08-21: 135–159
  were taken on disk; next is 160.)*

### Current position (2026-08-25)

- Register reconciled against `master` after a status-drift audit. Five entries
  were stale: **130** (released as `v0.2.2` on 2026-07-29, not `in review`);
  **144** (PR #64), **148** (PR #65) and **153** (PR #66) had all landed while
  still recorded as `proposed`; and **160** (PR #68) was recorded as
  `in progress` after merging. Ticket **159** was already recorded correctly.
- Ticket **160** is now `done` (2026-09-07): PR #68 shipped the exact-URL and CSV
  same-navigation comparison, reports, and exit contract, and ticket **161**
  delivered the remainders — run-backed `--crawl-run-id` selection, template and
  path-strata coverage, and the opt-in run-scoped persistence session.
- Shipped releases: `v0.2.0`, `v0.2.2`, `v0.3.0`. `v0.2.1` stays permanently
  excluded (closed, unmerged PR #50, not an ancestor of `master`).
- Foundation chain **144 -> 148 + 153** is complete, so the security-evidence
  lane is unblocked. Next by dependency order: **149** (P1/security, SSRF and
  rebinding safety, depends on 148), then **147** (P1 crawler self-safety,
  depends on 144). Evidence features **145/146/150/151/152/154** are unblocked
  on 144+148+153 but several still also require 149 or 129.
- Still `proposed` and untouched: Magento hygiene **131 -> 132 -> 133**, then
  **134**; and **158** (P3 adaptive speculative feedback, depends on completed
  156).
- No open pull requests and no open issues at the time of this audit. Ticket
  **161** was filed on 2026-08-25 for the ticket 160 remainders and landed on
  2026-09-07, and ticket **162** was filed the same day, so the next unreserved
  ticket number is **163**; do not reuse **110**.

### Current position (2026-09-07)

- Ticket **161** landed (PR **#69**, merged 2026-09-07), closing ticket **160**:
  `compare-renders` gains run-backed `--crawl-run-id` selection with
  deterministic host/locale/path/depth strata and honest source-run
  completeness, operator template labels via the optional CSV `template`
  column, per-URL `stratum`/`stratum_source` and stratum coverage in JSON, CSV,
  and the HTML report (with a stratum filter), and an opt-in `--persist`
  render-comparison session holding redacted bounded evidence and no HTML
  document.
- **Branch sweep.** Every branch was compared against `master` by patch
  identity. All are merged or hold only squash-merge noise, with one exception:
  `feature/3350-portal-url-policy-v1` (`8fcdb54`, 2026-07-28, never opened as a
  PR) adds `src/crawler_cli/portal_adapter.py`, `tests/test_portal_adapter.py`,
  and `docs/portal-migration-manager-adapter.md`, none of which exist on
  `master`. It is **not mergeable as authored**: it hard-codes the permanently
  excluded `v0.2.1` release, its contract baseline predates the whole 144–161
  lane, and its capability manifest claims browser coverage it does not have.
  Its address-class policy and its DNS-rebinding tests are reviewed prior art
  for ticket **149** (`master` already has the better fetch mechanism). Filed as
  ticket **162**.
- Ticket **149** gained a verified appendix of address-classification traps that
  the prior art does not handle — IPv4-mapped IPv6, NAT64 `64:ff9b::/96` (which
  `ipaddress` reports as **globally routable** while wrapping `127.0.0.1`), 6to4,
  IPv6 and Alibaba metadata addresses, and octal/decimal/hex IP literals. Each
  was executed and confirmed before being recorded. Read it before implementing.
- **Stash sweep.** Both entries in `git stash` are superseded and hold nothing
  worth recovering: `stash@{0}` (on `docs/144-adversarial-crawler-scope`) is the
  working copy of ticket 159, which landed as PR **#67** — it proposes
  `crawler-cli/crawl-artifact/3` while `master` is already at `/7`; `stash@{1}`
  is a `ticket-queue.md` WIP superseded by the 2026-08-25 register
  reconciliation. They are left in place rather than dropped.
- A leftover review worktree remains at
  `/home/user256/GitRepos/crawler_cli_worktrees/wt-csv-open-seeds`
  (`fix/csv-open-seeds`); that branch's content is fully in `master`, so the
  worktree can be removed.
- `tests/test_detection_analytics_perf.py::test_p99_under_5ms` was a
  load-sensitive flake: it failed under a loaded full-suite run and passed in
  isolation, on an unmodified tree as well. Fixed in PR **#70** (merged
  2026-09-07) by budgeting against CPU time rather than wall clock; the 5ms
  budget itself is unchanged.
- Ticket **149** is **done** (2026-09-07). Landed across PRs #72/#74/#75/#76 and the browser/archive follow-up:
  the address-class decision (`destination_policy.py`), its config surface, and
  the aiohttp `_GuardedResolver` tier plus the literal-IP pre-request check that
  covers the URLs a resolver is never asked about.

  **The deny-by-default posture landed in the follow-up (2026-09-07).**
  `destination_guard` now defaults to `resolver`. It shipped opt-in first
  because turning it on denies loopback for every caller, which stops an
  ordinary `crawler-cli http://localhost:3000/` and broke this repository's own
  tests in three waves — unit, the security-proof contracts, then the Postgres
  integration suite — since every one of them drives a loopback fixture server.
  Those fixtures now pass `destination_guard="off"` explicitly, one site at a
  time; the guard has its own suite.

  The follow-up also resolved the spec gap that made the switch awkward: an
  exact `--allow-network-cidr` may now name loopback, so an owned local service
  is crawlable under explicit authorisation instead of being unreachable at any
  setting other than `off`. The allowlist reopens the private and loopback tiers
  only — metadata, link-local, multicast, reserved and unspecified addresses
  stay denied however the run is configured, and link-local or multicast CIDRs
  are refused at construction. Supplying exact CIDRs disables the blanket
  RFC1918/ULA allowance, so they genuinely narrow rather than widen. Verified
  by direct execution, not just by the test suite.

  Two findings from building it, both verified rather than assumed:

  - `ipaddress` reports `is_private` as **True** for reserved `240.0.0.0/4`, the
    documentation ranges and benchmarking `198.18.0.0/15`. Defining
    `--allow-private-network` against `is_private` would have granted reach into
    all of them, so the private tier is an explicit RFC1918 plus ULA list.
  - `::ffff:127.0.0.1` reports `is_loopback` **False** on CPython 3.12.3 and
    **True** on later patch releases. CI caught this where local runs could not.
    Address-policy tests here must assert this project's contract, never the
    interpreter's own classification.

  Everything in scope landed. Three findings are worth carrying forward:

  - **robots.txt was fetched unguarded** through the robots cache's own bare
    session, following redirects, as the crawl's first request at the host the
    guard protects against. Any future auxiliary fetch path must be checked for
    the same pattern.
  - **Pre-connection denials fed the circuit breaker**, so a guarded run could
    open the breaker against a host that never refused anything. Denials are now
    typed skips with status 0.
  - **Two limitations are declared, not fixed**: a proxy defeats the guard for
    hostname targets (aiohttp resolves the proxy, not the target), and browser
    URL interception is not rebinding safety (Chromium resolves DNS itself).
    Both are reported in the capability object; strict mode rejects the proxy
    combination outright.

  This unblocks the evidence lane: **145**, **146**, **150** and **152** all
  listed 149 as a dependency.


- **Two ticket files were empty.** `ticket-145-client-split-measurement.md` and
  `ticket-147-crawler-self-safety.md` were created on 2026-08-26 at 1 byte and
  never written — neither has any content in git history, so the scope of a P1
  safety ticket (147) and a P2 evidence ticket (145) existed only as register
  one-liners. Both were reconstructed on 2026-09-07 from the
  2026-08-21 review brief, which is the surviving scope record for each. That
  brief is a **recommendation, not an approval**: its disposition is headed
  "Final review disposition proposed" and its reviewer decision checkboxes are
  unchecked. Both files carry a banner saying so, and separate reconstructed
  scope from reviewer-authored proposals, which are marked "Proposal (not
  approved)". **Approve both before implementing**, and prefer the brief if
  anything conflicts. Provenance is mapped claim by claim in
  `RECONSTRUCTION-PROVENANCE-145-147.md`.

  `tickets/` is gitignored, so a ticket file only exists in the repository once
  someone runs `git add -f`. That is how two files reached `master` empty; it is
  worth checking after filing any new ticket.

### Ordering rules

- Correctness and evidence hardening precede presentation work that consumes
  the affected fields.
- External/manual evidence is recorded as a blocker; it is never inferred from
  unit tests.
- New remediation work uses the next unreserved number (**183**); do not reuse **110**.

- `001` `done` [ticket-001-crawler-modularisation.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-001-crawler-modularisation.md)
- `002` `done` [ticket-002-bounded-crawler-behaviour.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-002-bounded-crawler-behaviour.md)
- `003` `done` [ticket-003-resumable-frontier.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-003-resumable-frontier.md)
- `004` `done` [ticket-004-content-hashing.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-004-content-hashing.md)
- `005` `done` [ticket-005-circuit-breaker.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-005-circuit-breaker.md)
- `006` `done` [ticket-006-crawl-comparison.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-006-crawl-comparison.md)
- `007` `done` [ticket-007-historical-discovery.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-007-historical-discovery.md)
- `008` `done` [ticket-008-reporting-views.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-008-reporting-views.md)
- `009` `done` [ticket-009-frontier-priority.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-009-frontier-priority.md)
- `010` `done` [ticket-010-cms-detection.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-010-cms-detection.md) — CMS detection module; debt closed: `--cms-detection` CLI flag now wired in `__main__.py` (alongside ticket-038)

### Mini SEO audit expansion (driven by `/home/user256/Canonicals/TechAuditRedux`)

- `011` `done` [ticket-011-cli-entry-point.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-011-cli-entry-point.md) — `__main__.py` + argparse + pyproject.toml entry point
- `012` `done` [ticket-012-archive-org-audit-report.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-012-archive-org-audit-report.md) — `audit_archive_urls()` with CSV output
- `013` `done` [ticket-013-url-provenance.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-013-url-provenance.md) — `url_sources` table + `record_source` helpers
- `014` `done` [ticket-014-sitemap-auto-discovery.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-014-sitemap-auto-discovery.md) — engine fetches robots.txt + well-known sitemaps
- `015` `done` [ticket-015-archive-url-hygiene.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-015-archive-url-hygiene.md) — `_normalize_url` + `_clean_url` with configurable filters
- `016` `done` [ticket-016-soft-404-utilities.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-016-soft-404-utilities.md) — `soft_404_fingerprint` + `simhash_neighbours`
- `017` `done` [ticket-017-url-variant-probes.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-017-url-variant-probes.md) — `generate_variants` + `probe_variant`
- `018` `done` [ticket-018-robots-rule-introspection.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-018-robots-rule-introspection.md) — `_RobotsRules` + `RobotsDecision` + `check()`
- `019` `done` [ticket-019-render-comparison.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-019-render-comparison.md) — `compare_renders` + `compare_renders_sampled`

### Expanded Scope (Ported from WIP)

- `020` `done` [ticket-020-schema-extraction.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-020-schema-extraction.md) — Schema.org extraction (JSON-LD, Microdata, RDFa)
- `021` `done` [ticket-021-advanced-link-analysis.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-021-advanced-link-analysis.md) — Advanced Link Graph (Anchor Text & XPath)
- `022` `done` [ticket-022-path-restrictions.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-022-path-restrictions.md) — `--path-restriction` and `--path-exclude`
- `023` `done` [ticket-023-vector-embeddings.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-023-vector-embeddings.md) — Vector Embeddings Generation
- `024` `done` [ticket-024-cli-csv-auth.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-024-cli-csv-auth.md) — CLI CSV Ingestion & HTTP Authentication
- `025` `done` [ticket-025-deep-crawl-comparison.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-025-deep-crawl-comparison.md) — Deep Crawl Comparison Engine
- `032` `done` [ticket-032-persistence-performance-fixes.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-032-persistence-performance-fixes.md) — Persistence Layer Performance & Race Conditions Fixes
- `033` `done` [ticket-033-session-crawl-logic.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-033-session-crawl-logic.md) — Session Crawl Logic & Limits Fixes

### Crawler feature enhancements (ported from WIP backlog)

These were tracked as standalone `ticket-026`..`ticket-031` files but never listed in the
queue. Closed in the 2026-06-07 batch pass — see
[DECISIONS-2026-06-07.md](/home/user256/GitRepos/crawler_cli/tickets/DECISIONS-2026-06-07.md).

- `026` `done` [ticket-026-custom-extraction.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-026-custom-extraction.md) — Custom data extraction (CSS/XPath/regex) → `content.custom_data` JSONB
- `027` `done` [ticket-027-proxy-support.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-027-proxy-support.md) — `--proxy`/`--proxy-auth` across aiohttp/curl_cffi/playwright (rotation deferred)
- `028` `done` [ticket-028-session-cookies.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-028-session-cookies.md) — `--cookie`/`--cookies-file` (JSON + Netscape) injected as Cookie header
- `029` `done` [ticket-029-performance-metrics.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-029-performance-metrics.md) — TTFB + total duration → `page_metadata`; `slowest_pages` report (CWV deferred)
- `030` `done` [ticket-030-sitemap-generation.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-030-sitemap-generation.md) — `generate-sitemap` subcommand with >50k index splitting
- `031` `done` [ticket-031-js-wait-conditions.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-031-js-wait-conditions.md) — `--wait-for-selector` + `--wait-for-network-idle` for SPAs

### Future Enhancements (Low Priority)

- `034` `done` [ticket-034-playwright-memory-bounds.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-034-playwright-memory-bounds.md) — Playwright Context Recycling & Memory Bounds
- `035` `proposed (deferred)` [ticket-035-redis-frontier-queue.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-035-redis-frontier-queue.md) — Redis-Backed Frontier Queue. **Deferred from 2026-06-07 batch**: architectural refactor needing a Redis dependency + infra and touching the hot crawl loop; warrants a dedicated reviewed PR. See DECISIONS-2026-06-07.md.

### GuardGeese Integration

- `036` `done` [ticket-036-guardgeese-fetch-extract-bridge.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-036-guardgeese-fetch-extract-bridge.md) — Standalone fetch/extract bridge for `guardgeese-worker`
- `037` `done` [ticket-037-guardgeese-monitoring-boundary.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-037-guardgeese-monitoring-boundary.md) — README boundary docs complete (ticket header marks it Done). Only the external GuardGueeseRedux `blockers.md`/WORKER-003 metadata is out of this repo's scope.

### Audit Coverage

- `038` `done` [ticket-038-analytics-tag-manager-detection.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-038-analytics-tag-manager-detection.md) — Analytics/tag-manager/pixel/A-B detection (detector, CLI flags, persistence, four reports, tests). Status corrected to `done` on 2026-06-07 — was already fully implemented but mismarked.

### Storage & lifecycle

- `039` `done` [ticket-039-expose-circuit-breaker-tuning.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-039-expose-circuit-breaker-tuning.md) — Circuit-breaker thresholds on CLI + env vars; 429 trigger + OPEN-transition logging
- `040` `done` [ticket-040-html-compression.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-040-html-compression.md) — **P0:** gzip HTML on write; fix misleading `html_compressed` column; backfill command
- `041` `done` [ticket-041-crawl-delete-command.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-041-crawl-delete-command.md) — **P1:** `delete-crawl` subcommand (truncate or drop database) with `--confirm`
- `042` `done` [ticket-042-compact-crawl-drop-html-keep-fingerprints.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-042-compact-crawl-drop-html-keep-fingerprints.md) — **P1:** `compact-crawl` — purge stored HTML, retain content hashes + audit metadata; wire `--content-hashing`

### JS backend enhancements

- `043` `done` [ticket-043-obscura-managed-backend-default-stealth.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-043-obscura-managed-backend-default-stealth.md) — First-class Obscura backend with managed lifecycle and stealth on by default

### Cross-repo

- `044` `done` [ticket-044-port-obscura-to-postgresqlcrawlerwip.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-044-port-obscura-to-postgresqlcrawlerwip.md) — Port Obscura managed backend + default stealth back into PostgreSQLCrawlerWIP. Done 2026-06-13 in that repo (git-init'd first; commit abaed4b): BrowserRuntime + PlaywrightBackend with managed-Obscura lifecycle in fetch.py, obscura_cli.py for testable CLI validation, config/CLI/runtime-logging wired, 19 new tests (29 total pass). Known follow-up: that repo's BFS loop still fetches over HTTP regardless of use_js (pre-existing; JS backend reachable via fetch_js/fetch_many) — wiring JS into the loop is out of this ticket's "extend, don't replace" scope.

> **HTTP API note:** the `crawler_api` FastAPI service lives in its **own repo**
> (`/home/user256/GitRepos/crawler_api`, which depends on `crawler_cli`), with its own
> ticket system (sprints 1–4: 201–204, 301–305, 401–403). API work — durable job
> persistence (204), auth hardening (304), concurrency limits (301), report/compare
> endpoints (201/202) — is tracked there, **not** here. A stray `src/crawler_api/` copy was
> briefly committed to this repo on 2026-06-07 and removed on 2026-06-08.

### Deferred stretch goals (split out of completed tickets, 2026-06-08)

- `045` `done` [ticket-045-proxy-rotation.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-045-proxy-rotation.md) — Proxy rotation / pool (stretch of ticket-027); round-robin + per-host strategies, failure eviction
- `046` `done` [ticket-046-core-web-vitals.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-046-core-web-vitals.md) — Core Web Vitals (LCP/CLS/INP) via Playwright PerformanceObserver (stretch of ticket-029)
- `047` `done` [ticket-047-curl-cffi-ttfb.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-047-curl-cffi-ttfb.md) — TTFB for the curl_cffi backend via streaming first-chunk timing (gap from ticket-029)
- `048` `done` [ticket-048-cookie-scoping.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-048-cookie-scoping.md) — Per-domain/path cookie scoping (limitation from ticket-028)

### 2026-06-11 audit findings

Full-codebase audit (engine, backends, robots, CLI, persistence, project tooling).

- `049` `done` [ticket-049-unlimited-crawl-link-enqueue.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-049-unlimited-crawl-link-enqueue.md) — **P0:** `--max-pages 0` (the default) never enqueues discovered links — frontier budget `max(0, 0 - total)` is always 0
- `050` `done` [ticket-050-robots-rfc9309-compliance.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-050-robots-rfc9309-compliance.md) — **P1:** robots.txt fixes: hardcoded https scheme (http sites get allow-all), last-match-wins precedence, exact-string UA matching, 5xx → permanent allow-all
- `051` `done` [ticket-051-cli-arg-and-dsn-hygiene.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-051-cli-arg-and-dsn-hygiene.md) — **P1:** `--concurrency` silently ignored (max-workers default always wins); DSN credentials not URL-escaped; bare-domain argv confusion
- `052` `done` [ticket-052-persistent-http-sessions.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-052-persistent-http-sessions.md) — **P1:** aiohttp/curl_cffi create a new session per request — no keep-alive, TLS handshake every fetch
- `053` `done` [ticket-053-curl-cffi-impersonation.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-053-curl-cffi-impersonation.md) — **P2:** curl_cffi backend never passes `impersonate=` — advertised TLS fingerprinting is not wired
- `054` `done` [ticket-054-streaming-body-cap-content-type-gate.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-054-streaming-body-cap-content-type-gate.md) — **P2:** `max_response_bytes` applied after full read (OOM risk); binaries fully downloaded though never parsed
- `055` `done` [ticket-055-logging-and-persist-error-visibility.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-055-logging-and-persist-error-visibility.md) — **P2:** 51 `print()`s → logging with `--verbose`/`--quiet`; persist failures (`persist_error`) currently invisible in CLI output
- `056` `done` [ticket-056-ci-lint-typecheck.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-056-ci-lint-typecheck.md) — **P2:** no CI, no lint, no typecheck — add GH Actions + ruff + gradual mypy
- `057` `done` [ticket-057-crawl-loop-throughput.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-057-crawl-loop-throughput.md) — **P3:** lock-step batch `gather` head-of-line blocking; N+1 `record_source_by_url` writes during sitemap ingestion

### 2026-06-12 follow-up audit

Re-evaluation after the 049–057 batch (engine scope/memory/CPU hot paths, retry hygiene, ops, CI debt).

- `058` `done` [ticket-058-allowed-hosts-link-discovery.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-058-allowed-hosts-link-discovery.md) — **P1:** `allowed_hosts` is dead config — `extract_links` drops cross-host links before the engine's `is_host_allowed` check can run
- `059` `done` [ticket-059-open-crawl-memory-retention.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-059-open-crawl-memory-retention.md) — **P1:** open crawls hold every page's `raw_html` in RAM for the whole job; `save_to` buffers one giant JSON — drop HTML after persist, stream JSONL
- `060` `done` [ticket-060-single-parse-lxml.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-060-single-parse-lxml.md) — **P2:** each page parsed 2–3× with `html.parser` despite lxml dependency; parse once, use lxml, offload big pages off the event loop
- `061` `done` [ticket-061-crawl-many-continuous-pool.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-061-crawl-many-continuous-pool.md) — **P2:** `crawl_many` (list/CSV mode) still lock-step batches — port the ticket-057 continuous pool
- `062` `done` [ticket-062-retry-results-budget-hygiene.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-062-retry-results-budget-hygiene.md) — **P2:** transient-error retries consume `--max-pages` budget and leave failed attempts in saved results
- `063` `done` [ticket-063-per-host-politeness.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-063-per-host-politeness.md) — **P3:** no per-host concurrency cap — full worker pool can burst a single origin
- `064` `done` [ticket-064-graceful-shutdown.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-064-graceful-shutdown.md) — **P3:** SIGINT/SIGTERM drain: finish in-flight, write partial output, summary + `interrupted` marker instead of a traceback
- `065` `done` [ticket-065-sitemap-ingestion-throughput.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-065-sitemap-ingestion-throughput.md) — **P3:** sitemap shards fetched serially; `_persist_sitemap_hreflang` still N+1 and pokes private store methods
- `066` `done` [ticket-066-ci-hardening.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-066-ci-hardening.md) — **P3:** enforce mypy (currently can't fail), add coverage floor, integration-test `persistence.py` against real Postgres in CI

### 2026-06-12 review of the 058–066 batch

Post-implementation review found two regressions and two completeness gaps.

- `067` `done` [ticket-067-ci-coverage-regression.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-067-ci-coverage-regression.md) — **P0:** coverage floor in `addopts` breaks single-file pytest runs and makes the new integration CI job permanently red
- `068` `done` [ticket-068-jsonl-skipped-results.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-068-jsonl-skipped-results.md) — **P1:** robots-blocked/fetch-error results never written to the JSONL `save_to` file; counts disagree with contents
- `069` `done` [ticket-069-finish-batch-dod-gaps.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-069-finish-batch-dod-gaps.md) — **P2:** unbuilt DoD items: to_thread parse offload (060), `keep_html_in_results` (059), stop-flag drain in `crawl_many` (064); + per-host cap visibility log
- `070` `done` [ticket-070-mypy-persistence.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-070-mypy-persistence.md) — **P2:** remove `persistence.py` from the mypy `ignore_errors` blanket; fix its errors for real

### Cross-repo follow-up

- `071` `done` [ticket-071-wip-js-loop-wiring.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-071-wip-js-loop-wiring.md) — **(PostgreSQLCrawlerWIP repo):** wire the JS/Obscura backend into that repo's BFS crawl loop so `--js`/`--obscura` actually render pages (follow-up to ticket-044). Done 2026-06-14 (commit 01a78ad): use_js threaded through fetch_many_with_delay/fetch_with_delay, JS branch adapts 5-tuple→6-tuple, shared backend torn down once at crawl end. Also fixed a latent `import json` shadowing bug in fetch_with_delay's except block. 3 new routing tests; 32 total pass.

### Hard-site crawling (proxies + anti-bot), 2026-06-15

Driven by the casino.org/Cloudflare investigation: make crawler_cli a real
proxied hard-site crawler. User uses a residential rotating gateway (primary).

- `072` `done` [ticket-072-gateway-proxy-mode.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-072-gateway-proxy-mode.md) — rotating-gateway proxy mode (single endpoint, IP rotates server-side per request, never evicted, retried on failure); `--proxy-mode gateway|list` (commit 3918431)
- `073` `done` [ticket-073-proxy-browser-backend.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-073-proxy-browser-backend.md) — route the proxy pool (gateway/list) through the Playwright/Obscura backend; managed Obscura `--proxy` falls back to the gateway (commit 3918431)
- `074` `done` [ticket-074-challenge-detect-escalate.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-074-challenge-detect-escalate.md) — bot-challenge detection (Cloudflare/Datadome/PerimeterX/Akamai/Imperva) + escalate HTTP→browser through a fresh IP; blocked pages recorded, not stored as content (commit 1153328)
- `075` `proposed` [ticket-075-casino-guru-review-ingestion.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-075-casino-guru-review-ingestion.md) — ingest Casino Guru reviews from `en-sitemap.xml` into the shared casino dataset, solve access/fetch path first, then cluster and merge into factfiles

### Intent_Overlap integration, 2026-07-04

Bake `/home/user256/GitRepos/Intent_Overlap` (URL intent-overlap / de-canonicalisation
risk finder: sitemap crawl → trafilatura signatures → sentence-transformer embeddings →
hreflang-aware similarity analysis → CSV reports) into crawler_cli, replacing its
standalone SQLite crawler with this engine + Postgres store. Upstream remediation
Sprints 2 AND 3 (IO tickets 108–117) were completed and merged on 2026-07-04 (PRs
#8–#10), so these tickets port the fixed implementations and their tests verbatim —
nothing is "fix during port" anymore (tickets updated accordingly same day).
Order: 076 → 077, 078 in parallel, then 079; 080 independent; 081 last.

**STATUS 2026-07-04: ALL DONE.** Tickets 076–081 implemented, tested, and each
shipped as a stacked PR (#1→#6, base master via `io-integration-base`). User
overrides applied: NO Screaming Frog CSV import (078) and NO `--gsc` join (079)
— 100% crawler-powered. Parity signed off: the port matches upstream v2.1.0
byte-for-byte on casino_org (1221 pairs) and whiskipedia (198 pairs), Jaccard
1.0000. Standalone Intent_Overlap repo marked superseded. Batch reviewed
2026-07-05; three follow-ups filed as 082–084 (see next section). Tickets later
continued through the 2026-07-15 intent-overlap review batch; 110 remains
unused (ticket 110 explicitly out of scope / rejected). Next free number: **117**.
**LANDED ON MASTER 2026-07-05 (ticket 082):** the whole stack is now on `master`
base-first — `io-integration-base` roll-up as PR #7, then 076–081 as PRs #8/#2–#6
in order, 24 base commits kept linear (no history rewrite). Suite green on master
(367 passed / 13 skipped); all `io-integration-base` and 076–081 feature branches
deleted.
**Start here:** [briefs.md](/home/user256/GitRepos/crawler_cli/tickets/briefs.md) — the
handoff brief with cross-instance context, upstream state, anchors, and constraints.

- `076` `done` [ticket-076-intent-signature-extraction.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-076-intent-signature-extraction.md) — **P1:** trafilatura main text + per-site boilerplate stripping + intent signature via upstream's unified `signature_text()`/`signature_hash()` (IO 109/114, fixed upstream)
- `077` `done` [ticket-077-local-embedding-provider.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-077-local-embedding-provider.md) — **P1:** embedding-provider seam: local sentence-transformers (multilingual MiniLM default, normalized float32) alongside OpenAI; hash-gated re-embed skip
- `078` `done` [ticket-078-hreflang-groups-url-identity.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-078-hreflang-groups-url-identity.md) — **P1:** union-find hreflang groups over the three existing hreflang tables + Screaming Frog CSV import, reciprocity issues, URL-variant folding with tracking-param denylist (ports upstream IO-108 fix)
- `079` `done` [ticket-079-intent-overlap-analyse.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-079-intent-overlap-analyse.md) — **P1:** `intent-overlap` subcommand: language-partitioned block-wise cosine pairing, hreflang suppression, clustering + cohesion QC, risk + suggested canonical, GSC join, threshold calibration, six-CSV report set (ports upstream IO-110/111/115/117 fixes)
- `080` `done` [ticket-080-crawl-parity-refresh-ua-map.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-080-crawl-parity-refresh-ua-map.md) — **P2:** crawl parity gaps: `--refresh-days` staleness refetch + `--ua DOMAIN=UA` per-domain user-agent map for portfolio crawls
- `081` `done` [ticket-081-intent-overlap-scale-eval-parity.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-081-intent-overlap-scale-eval-parity.md) — **P2:** ANN scale path (hnswlib, recall-checked), block-wise calibration, ported eval fixture + goldens, parity sign-off vs regenerated casino_org/whiskipedia goldens, retire the standalone repo (ports upstream IO-112/113/116)

### 2026-07-05 review of the 076–081 batch (Intent_Overlap follow-ups)

Review of the shipped Intent_Overlap stack (six stacked PRs #1–#6, all green,
parity signed off). Three items the implementer flagged in the handoff become
follow-up tickets. The per-domain-UA netloc-vs-hostname bug they caught is NOT
ticketed — it was fixed in the stack itself (tickets 080/081).

- `082` `done` (2026-07-05) [ticket-082-io-stack-merge-to-master.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-082-io-stack-merge-to-master.md) — **P1:** landed the stack to `master` base-first — `io-integration-base` (24 commits) merged as its own roll-up PR #7, then 076 (PR #8, retargeted-by-reopen), 077 (#2), 078 (#3), 079 (#4), 080 (#5), 081 (#6) merged in order, each per-ticket diff clean; 24 base commits linear on master, no rebase/history-rewrite. Verified against DoD: suite green on master (367 passed / 13 skipped), all io/076–081 branches deleted. 083-dependency moot (083 done, on master)
- `083` `done` (2026-07-05) [ticket-083-any-widening-typecheck-debt.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-083-any-widening-typecheck-debt.md) — **P2:** retired the `object→Any` typecheck stopgaps (42 `# type: ignore[arg-type]` in `__main__.py` deserializers + `Any`-typed `persistence.py` query rows). Added TypedDicts for the saved-crawl JSON + the seven query-row helpers, retyped three concrete-store consumers, kept `persistence.py` out of the mypy blanket (ticket-070 invariant). `__main__.py` now has zero `type: ignore`; mypy/ruff clean. F821 was `CrawlJobResult` (fixed via TYPE_CHECKING import), covered by existing + two new `_load_saved_crawl` tests. Split out ticket 085 (intent_overlap `store: Any`)
- `084` `done` (2026-07-05) [ticket-084-cli-hygiene-test-env-isolation.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-084-cli-hygiene-test-env-isolation.md) — **P1 (test-only):** `test_cli_hygiene.py` DSN/config tests failed when the shell exports `CRAWLER_CLI_POSTGRES_*` / `PostgreSQLCrawler_*` (as the maintainer's does). Added an autouse `_clear_postgres_env` fixture in `tests/conftest.py` clearing the full DSN family across both prefixes incl. `*_POSTGRES_DSN`; scoped to the DSN family only so `CRAWLER_CLI_TEST_DSN` is untouched. No runtime change. Verified with the vars exported: module 27 passed (was 8 failed), full suite 367 passed / 13 skipped
- `085` `done` (2026-07-05) [ticket-085-intent-overlap-store-typing.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-085-intent-overlap-store-typing.md) — **P3:** finished the ticket-083 consumer typing: `run_intent_overlap` now takes `store: AsyncpgStore` and the analysis pipeline type-checks against the row TypedDicts. Added `AnalysedRow(AnalysisRow, total=False)` (one computed key `excluded`; `total=False` not `NotRequired` because the latter isn't honoured at runtime under `from __future__ import annotations`) + `VariantReportRow`; retyped `compute_exclusion`/`_count_reasons`/`_variant_rows_from_store`/`write_reports` off `dict[str, Any]`; widened `_write_csv` to `Mapping`. No computed keys leak into the DB-column `AnalysisRow`, no new `type: ignore`/`cast`. mypy + ruff clean, suite 367 passed / 13 skipped

### 2026-07-15 full-tool audit follow-ups

Read-only audit of crawl correctness, scope/politeness, persistence semantics,
security, CLI behavior, CI, packaging, and documentation. Implementation order:
086 first; 087–090 next; 091–094 independently; 095 after 086; 096–098 can
proceed independently except where their DoD references earlier behavior.

- `086` `done` (2026-07-15, PR #13) [ticket-086-crawl-run-isolation.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-086-crawl-run-isolation.md) — **P0:** isolate frontier/metadata by crawl run; explicit new-vs-resume semantics so old rows cannot suppress unrelated seeds. Reviewed MERGE+REMEDIATE: P0 fix sound, suite green (393 passed / 19 skipped on merged master), ruff+mypy clean; pg integration tests run separately (need `CRAWLER_CLI_TEST_DSN`). Minor follow-ups filed as ticket 099; run-aware reporting owned by 095
- `087` `done` (2026-07-15, PR #26; leftovers → 114) [ticket-087-sitemap-scope-budget-politeness.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-087-sitemap-scope-budget-politeness.md) — **P0:** enforce host scope and run-global budget on sitemap URLs; route sitemap fetches through bounded politeness controls. Reviewed MERGE+REMEDIATE: DoD met; CI green
- `088` `done` (2026-07-15, PR #22) [ticket-088-robots-rfc9309-follow-up.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-088-robots-rfc9309-follow-up.md) — **P0:** fix robots fail-open contradiction, query matching, consecutive UA groups, per-domain UA selection, and proxy routing. Reviewed MERGE: DoD met; format fix landed before merge
- `089` `done` (2026-07-15, PR #24) [ticket-089-challenge-hard-stop-persistence.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-089-challenge-hard-stop-persistence.md) — **P0:** unresolved challenges must not be extracted, persisted as content, linked, or counted as crawled. Reviewed MERGE: DoD met; integration fixture `h2` fixed before merge
- `090` `done` (2026-07-15, PR #12) [ticket-090-safe-default-crawl-bound.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-090-safe-default-crawl-bound.md) — **P1:** restore a finite default open-crawl bound and align config/CLI/docs. Reviewed MERGE: default open crawl now bounded at 200, `--max-pages 0` still explicitly unlimited, fixed-list/CSV uncapped; all DoD met (370 passed). Minor dead-`config.max_pages`-field note → ticket 112 (via 099)
- `091` `done` (2026-07-15, PR #9) [ticket-091-real-digest-auth.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-091-real-digest-auth.md) — **P1:** implement real Digest authentication across supported backends or remove the misleading option. Reviewed MERGE: chose the ticket-permitted removal path — `digest` gone from CLI/type surface, legacy programmatic use fails clearly, no silent Basic downgrade; added `--auth-password-env/-file`. 30 passed
- `092` `done` (2026-07-15, PR #25; leftovers → 115) [ticket-092-persist-failure-exit-policy.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-092-persist-failure-exit-policy.md) — **P1:** terminal persistence failures produce a non-zero automation result and durable/partial output metadata. Reviewed MERGE+REMEDIATE: DoD met; CI green
- `093` `done` [ticket-093-cli-config-numeric-validation.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-093-cli-config-numeric-validation.md) — **P2:** validate numeric and cross-field config at CLI/library boundaries; no raw tracebacks
- `094` `done` (2026-07-15, PR #11) [ticket-094-obscura-installer-verification.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-094-obscura-installer-verification.md) — **P1 security:** checksum/signature verification, safe staged archive extraction, and atomic install. Reviewed MERGE: adversarial security review found no exploitable holes — real-path containment (not string prefix), pre-extraction symlink/hardlink/device rejection, fail-closed digest verify, atomic replace with rollback; 42 passed. Test-coverage hardening + digest cross-check filed as ticket 100
- `095` `done` (2026-07-16, PR #44) [ticket-095-run-aware-snapshots-reporting.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-095-run-aware-snapshots-reporting.md) — **P2, depends on 086:** immutable snapshots and deterministic run selection; Ticket 120 AMP regression remediation was folded into the rework
- `096` `done` (2026-07-15) [ticket-096-persistence-coverage-gate.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-096-persistence-coverage-gate.md) — **P2:** combine/gate PostgreSQL integration coverage and exercise migrations/concurrency/failure paths
- `097` `done` (2026-07-15, PR #10) [ticket-097-real-playwright-ci-smoke.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-097-real-playwright-ci-smoke.md) — **P2:** install and launch real Chromium in a required CI smoke job. Reviewed MERGE: dedicated `playwright-smoke` job installs `.[test,playwright]` + pinned/cached Chromium with `continue-on-error` removed (hard-fails on broken browser); real JS-rendered end-to-end crawl through `CrawlEngine`, cleanup-on-success/failure asserted; heavy tests marker-gated so local unit runs stay fast. Real browser ran in review (2 passed)
- `098` `done` (2026-07-15) [ticket-098-packaging-docs-release-hygiene.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-098-packaging-docs-release-hygiene.md) — **P3:** fix nonexistent `[api]` extra docs; add license/project metadata/install-matrix/release checks — MIT LICENSE + pyproject metadata; README install matrix; CHANGELOG/RELEASING; CI packaging + extras jobs

### 2026-07-15 PR-review remediation follow-ups

Batch review + merge of the five 2026-07-15 audit PRs (#9–#13, tickets
091/097/094/090/086). All five merged to master (suite green: 393 passed / 19
skipped, ruff + mypy clean). Larger follow-ups already had homes (095 run-aware
reporting, 096 pg coverage gating); these capture the remaining small items.
An unrelated uncommitted bulk-insert deadlock fix found in the working tree was
committed separately (not a ticket).

- `099` `done` (2026-07-15, PR #20; leftovers → 112) [ticket-099-crawl-run-isolation-followups.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-099-crawl-run-isolation-followups.md) — **P2:** drop no-op `--new-run`, `CrawlRunSelectionError` (no broad RuntimeError swallow), remove dead legacy-run backfill SQL, resume mismatch/not-found tests
- `100` `done` (2026-07-15, PR #32) [ticket-100-obscura-installer-test-hardening.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-100-obscura-installer-test-hardening.md) — **P3 security:** ticket-094 test hardening — direct rejection tests for tar symlink/absolute/device/FIFO + zip-symlink members; one-time cross-check confirmed all 5 pinned `v0.1.8` SHA-256 digests match published GitHub release assets (fail-closed verify unchanged)
- `112` `done` (2026-07-15) [ticket-112-run-isolation-hygiene-leftovers.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-112-run-isolation-hygiene-leftovers.md) — **P3:** 099 leftovers — removed dead `CrawlConfig.max_pages`; auth-password guard names supplied source flag; `--resume` plain arg (mutex collapsed)

### Intent-overlap case handling (from thompsons-scotland.co.uk run review, 2026-07-15)

First real single-locale production run (3942 pages) surfaced four classes of
finding the analysis mislabels or handles only incidentally. Evidence and
counts in each ticket; run outputs in `runs/thompsons-scotland-20260715/`.
Merged in dependency order: 101 first, then 102/103/104, then 105. All remain
constrained to crawler-owned evidence.

- `101` `done` (2026-07-15, PR #16) [ticket-101-overlap-pair-relationship-classification.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-101-overlap-pair-relationship-classification.md) — **P1:** pair URL relationships, parent-child risk guidance, cluster relation/canonical policy, and relation counts
- `102` `done` (2026-07-15, PR #15) [ticket-102-parameterised-url-classification.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-102-parameterised-url-classification.md) — **P1:** parameterised URL class, signature-confirmed base folding, missing-canonical action, and default-document normalisation
- `103` `done` (2026-07-15, PR #18; remediation 108) [ticket-103-amp-variant-awareness.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-103-amp-variant-awareness.md) — **P1:** explicit AMP extraction/classification/exclusion, canonical-hygiene report, and optional crawl-budget skip
- `104` `done` (2026-07-15, PR #17; remediation 109→113) [ticket-104-thin-content-vs-duplicate.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-104-thin-content-vs-duplicate.md) — **P1:** signature-thinness classification, reporting, and duplicate-gate policy
- `105` `done` (2026-07-15, PR #14) [ticket-105-time-sequenced-section-policy.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-105-time-sequenced-section-policy.md) — **P2:** opt-in time-sequenced sections with cross-section and thin-content precedence preserved

### Interactive HTML report (2026-07-15)

Webpage rendering of the intent-overlap results: hoverable cluster map with
match-type toggles + the core report data as filterable tables, from a JSON
data export. Land after 101–105 (+108 AMP evidence) so tag fields are stable.

- `106` `done` (2026-07-15, PR #28) [ticket-106-report-data-json-export.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-106-report-data-json-export.md) — **P2:** `--json-report` → `report_data.json` (pages/pairs/clusters + 2D UMAP/PCA coords via `[viz]` extra, crawler-native cluster labels, centroid-similarity metric); the data layer for 107. Unblocked by 108 ✓; schema polish notes in 113
- `107` `done` (2026-07-15) [ticket-107-interactive-html-cluster-report.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-107-interactive-html-cluster-report.md) — **P2, depends on 106:** `render-report` subcommand → single self-contained offline HTML — canvas cluster map (hover/zoom/pin), match-type filter toggles (parent-child, time-sequenced, thin, parameterised, amp...), sortable pages/pairs/clusters tables, URL search

### 2026-07-15 review remediations for tickets 103–104 + CI

- `108` `done` (2026-07-15, PR #23; production recount → 116) [ticket-108-amp-classification-evidence-hardening.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-108-amp-classification-evidence-hardening.md) — **P1, depends on 103:** remove base-exists-only AMP confirmation, use intent-signature evidence, and recompute stale variant labels. Reviewed MERGE: DoD met; CI green
- `109` `done` (2026-07-15, PR #21; leftovers → 113) [ticket-109-thin-content-diagnostic-completeness.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-109-thin-content-diagnostic-completeness.md) — **P2:** `main_text_*` / `signature_chars` diagnostics in `pages.csv`; missing-vs-zero evidence; thin policy unchanged
- `111` `done` (2026-07-15, PR #19) [ticket-111-ci-artifact-action-runtime-hygiene.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-111-ci-artifact-action-runtime-hygiene.md) — **P3:** non-empty coverage artifacts + GitHub actions off deprecated Node 20 runtimes
- `113` `done` (2026-07-15) [ticket-113-thin-diagnostic-schema-calibration.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-113-thin-diagnostic-schema-calibration.md) — **P3:** 109 leftovers — 106 `pages[]` diagnostic length contract + `/videos` calibration (`word_count` 820–1042 vs `main_text_words=52` / `signature_words=77`)

### 2026-07-15 batch review remediations (PRs #22–#26)

Review + merge of tickets **087 / 088 / 089 / 092 / 108** (PRs #26 / #22 / #24 /
#25 / #23). All merged MERGE or MERGE+REMEDIATE; none rejected.

- `114` `done` (2026-07-16, PR #36) [ticket-114-sitemap-budget-dedupe-cdn-docs.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-114-sitemap-budget-dedupe-cdn-docs.md) — **P2:** 087 leftovers — dedupe sitemap locs against frontier budget + document cross-host `Sitemap:` allowlisting
- `115` `done` (2026-07-16, PR #37) [ticket-115-persist-frontier-incompleteness-signaling.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-115-persist-frontier-incompleteness-signaling.md) — **P2:** 092 leftovers — signal mark-done failure to automation; align crawl-run status with persist incompleteness
- `116` `done` (2026-07-16, production-store reclassification) [ticket-116-amp-evidence-production-recount.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-116-amp-evidence-production-recount.md) — **P3:** 108 follow-up — 479 evidence-backed AMP variants (477 canonical, 2 signature-hash, 0 amphtml edges); 0 missing canonical
- `117` `done` (2026-07-16, PR #39) [ticket-117-config-validation-merge-regression.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-117-config-validation-merge-regression.md) — **P1:** removed stale `max_pages` validation; `default_open_crawl_limit=0` remains the direct-library unlimited sentinel
- `118` `done` (2026-07-16, PR #42) [ticket-118-crawler-gui-fixture-regeneration.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-118-crawler-gui-fixture-regeneration.md) — **P3:** keep the generated crawler_gui fixture aligned with scheduled-crawl UI fields. Reviewed MERGE: byte-exact generator↔fixture parity, `generate_sample_data.py --check` + `tests/test_crawler_gui_fixture.py` guard drift; schedule nav enabled + all 9 config fields. Landed the `crawler_gui/` baseline on master
- `119` `done` (2026-07-16, PR #45) [ticket-119-crawler-gui-intent-overlap-viewer.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-119-crawler-gui-intent-overlap-viewer.md) — **P2:** replicate Ticket 107's intent-overlap viewer in crawler_gui while retaining the standalone offline export. Reviewed MERGE: reuses 106 `report_data` via one adapter (no browser recomputation), dependency-free, 107 `render-report` export unchanged, light/dark themes, map↔table selection sync; node 3/3 + python parity green. #42 generator conflict resolved and both fixtures regenerated. (Stacked PR #43 mis-merged into `agent/118`; same commit re-targeted to master as PR #45.) Shell hygiene → 121
- `120` `done` (2026-07-16, PR #44) [ticket-120-run-snapshot-amp-exclusion-regression.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-120-run-snapshot-amp-exclusion-regression.md) — **P1:** restored run-scoped AMP `variant_kind`, full-flow coverage, and deterministic multi-run report selection
- `121` `done` (2026-07-16) [ticket-121-crawler-gui-shell-hygiene.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-121-crawler-gui-shell-hygiene.md) — **P3:** offline shell, no competitor capture/screenshots, and documented grid HTTP requirement
- `122` `done` (2026-07-17, PR #47; remediations → 123) [ticket-122-compare-remap-and-url-pair-mapping.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-122-compare-remap-and-url-pair-mapping.md) — **P2:** site-to-site compare: `--replace` host remapping + simhash hamming tolerance on `compare`, and the `compare-urls` CSV pair/redirect-mapping command (redirect-chain capture, store-backed page loading, `--fail-on` CI gating). Reviewed MERGE+REMEDIATE: two review bugs fixed pre-merge (root-URL trailing-slash matching in `normalize_url_for_match`; source-side resolution now matches `requested_url` only) + 4 regression tests; store-loader evidence recorded against real Postgres; suite 680 passed / 41 skipped, ruff+mypy clean

### crawler_gui live operation (2026-07-17)

- `125` `done` (2026-07-17, commit `ee7ae6e`) [ticket-125-crawler-gui-all-crawls-access.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-125-crawler-gui-all-crawls-access.md) — **P2:** GUI live mode reaches every crawl run in the connected DB — `server.py` bridge landed with 11 unit tests + a DSN-gated integration test; `offset`/`limit` pagination with a `Showing X of Y` banner and Load more (no more silent 5k truncation); overview/issues moved to a whole-run SQL aggregate so they stay correct while paging; legacy pre-095 DBs collapse to one honest `current-state` entry instead of N runs each claiming the whole database; inlinks/outlinks/structured-data/response-time filled from the DB (absent stays `null`, not 0). Also fixed live-mode content-type never matching `text/html` (every HTML category tab and content stat silently read zero) and hid the empty `legacy` placeholder run
- `124` `done` (2026-07-17, commit `13911e1`) [ticket-124-crawler-gui-crawl-management.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-124-crawler-gui-crawl-management.md) — **P2, depended on 125:** manage crawls from the GUI — run-selector dropdown + clickable history cards (replacing hand-edited `?run=`, URLs stay shareable) and a working "+ New Crawl" via `POST /api/live/crawls` spawning the real `crawler_cli` CLI, with single-job 409 guard, progress polling, auto-load of the finished run, and failure output surfaced. Consciously extends the read-only bridge for local submission; **delete stays CLI/API-only**. Verified end-to-end against real crawls in headless Chromium. Fixed: empty-DB 500 and a stale `has_run_snapshots` flag that mislabelled runs until restart. Chrome-profile picker is the recorded follow-up; `legacy` backfill duplication → 126

### Active work — priority order (2026-07-18)

- `123` `done` [ticket-123-compare-urls-review-remediations.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-123-compare-urls-review-remediations.md) — **P2:** flag-less hash behaviour is explicit and single-pass; store-backed remaps load HTML or warn on fallback; persistence/CSV/exit-code/identity/error-path coverage added; hreflang scope corrected. Focused compare suite passes.
- `126` `done` (2026-07-18) [ticket-126-legacy-snapshot-backfill-duplication.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-126-legacy-snapshot-backfill-duplication.md) — **P3:** `initialize()` now backfills only when `page_run_snapshots` is newly created over genuine legacy state, so a fresh database keeps only real crawl runs. Existing duplicated snapshots are intentionally retained pending an explicit cleanup option; integration coverage needs a designated test DSN.
- `127` `done` [ticket-127-compare-store-dsn-env.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-127-compare-store-dsn-env.md) — **P2:** the ticket-122 per-side compare store flags take a literal DSN, putting credentials in shell history and the process list. Resolve each side from the environment instead — `CRAWLER_CLI_<SIDE>_POSTGRES_DSN` (also `PostgreSQLCrawler_` prefix) plus `--<side>-store-env VAR`, with inline `--<side>-store` kept as an override; named-but-unset variable fails fast. Implemented on `agent/127-compare-store-dsn-env`
- `128` `done` (2026-07-18) [ticket-128-crawler-gui-chrome-profile-picker.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-128-crawler-gui-chrome-profile-picker.md) — **P2:** live GUI Chrome/Chromium profile discovery, lock preflight, dedicated-user-data guidance, persistent Playwright argv mapping, and Obscura/profile exclusion.
- `129` `done` (2026-07-21) [ticket-129-playwright-auth-origin-scoping.md](/home/user256/GitRepos/crawler_cli/tickets/ticket-129-playwright-auth-origin-scoping.md) — **P2 (security):** Playwright backend sets `http_credentials` without an `origin` restriction. Scoped credentials/headers per-origin natively using `route.fetch` to ensure cross-origin redirects strip credentials while same-origin redirects retain them. Playwright now passes all security proof tests and is fully supported in the portal-integration contract.
- `130` `done` (2026-07-29, PR #53, released v0.2.2 2026-07-29) [ticket-130-v022-release-prep.md](./ticket-130-v022-release-prep.md) — **P0 release safety:** prepared crawler-cli v0.2.2 for the reviewed PR #51 HTTP-only Portal policy hook. The `v0.2.2` tag and GitHub Release exist and are the first immutable release Portal may pin; the remote `v0.2.1` tag remains permanently excluded. Superseded for new pins by `v0.3.0` (PR #61, released 2026-08-10).

### Magento hygiene pass (Timber Living / Yoma, 2026-08-12)

Layered-nav crawl explosion on timberlivingcompany.co.uk (119k URLs, 29 GB
JSONL, 0 noindex on 118k filter URLs). CMS detector has no Magento; ticket 102
treats canonical-elsewhere as handled. Do not bake “noindex all filters” into
the crawler — report and optionally refuse to follow.

- `131` `proposed` [ticket-131-magento-cms-detection.md](./ticket-131-magento-cms-detection.md) — **P1:** Magento/Adobe Commerce fingerprint in `CMSDetector` (blocks 134)
- `132` `proposed` [ticket-132-ecommerce-url-taxonomy.md](./ticket-132-ecommerce-url-taxonomy.md) — **P1:** URL taxonomy `faceted`/`toolbar`/`session`/`unrewritten`/`search`/`clean` at crawl time
- `133` `proposed` [ticket-133-indexable-despite-canonical.md](./ticket-133-indexable-despite-canonical.md) — **P1:** count INDEX+canonical-elsewhere; do not fold Magento filters out of hygiene reports
- `134` `proposed` [ticket-134-magento-facet-crawl-guard.md](./ticket-134-magento-facet-crawl-guard.md) — **P1, depends on 131+132:** skip enqueue of faceted/toolbar/session links unless `--follow-facets`

### Adversarial-crawler scope (sapiens.com wording, 2026-08-21)

`crawler_cli` does not meet either popular “adversarial crawler” definition.
144 writes that down. 145–154 add only bounded authorised measurement, passive
inventory, shared scope/evidence controls, and crawler self-safety. Evasion and
exploit payloads stay un-ticketed. Review the lane as a dependency graph, not
ticket-number order: 153 deliberately lands before the detectors that consume
its evidence contract.

- `144` `done` (2026-08-21, PR #64) [ticket-144-adversarial-crawler-scope.md](./ticket-144-adversarial-crawler-scope.md) — **P1:** README/SKILL/CLI help now name the product boundary — evidence crawler, not evasion, not pentest — with an explicit out-of-scope list, corrected dual-use flag help, and a `tests/contract/test_product_scope_contract.py` guard. Foundation for 145–154.
- `145` `proposed` [ticket-145-client-split-measurement.md](./ticket-145-client-split-measurement.md) — **P2, depends on 144+148+149+153:** bounded plain vs impersonate vs spoofed-bot UA matrix; no retry-on-403; spoofed Googlebot is not Googlebot
- `146` `done` (2026-09-23, PRs #80–#87) [ticket-146-authorised-exposure-inventory.md](./ticket-146-authorised-exposure-inventory.md) — **P2:** shipped the scope-gated `exposure-inventory` command, bounded declared-host probes, soft-404/sitemap evidence, redacted versioned artifact, and dedicated regression tests; no payloads
- `147` `proposed` [ticket-147-crawler-self-safety.md](./ticket-147-crawler-self-safety.md) — **P1/safety, depends on 144:** regression-lock existing GET-only HTTP(S); add session-mutating URL policy, robots confirmation, typed skip evidence; strict-mode integration uses 148
- `148` `done` (2026-08-21, PR #65) [ticket-148-authorisation-scope-manifest.md](./ticket-148-authorisation-scope-manifest.md) — **P1, depends on 144:** versioned operator attestation with exact origin/path/time/method scope and one fail-closed predicate applied to every URL source; gates security-adjacent fetch modes. Unblocks 149 and 152.
- `149` `done` (2026-09-07, PRs #72/#74/#75/#76 + browser/archive follow-up) [ticket-149-default-network-ssrf-safety.md](./ticket-149-default-network-ssrf-safety.md) — **P1/security, depends on 148:** block special/private destinations and rebinding across redirects/auxiliary fetches; honest per-backend capabilities; double-confirmed private-network exception. **Prior art:** `portal_adapter.py` on unmerged branch `feature/3350-portal-url-policy-v1` (`8fcdb54`) already implements the address-class policy and the per-hop resolve-validate-pin loop, with tests; read it first (see ticket 162).
- `150` `proposed` [ticket-150-passive-security-posture.md](./ticket-150-passive-security-posture.md) — **P2, depends on 144+149+153:** passive security headers, redacted cookie attributes, TLS capability/facts, observed CORS response posture, and mixed content
- `151` `proposed` [ticket-151-passive-form-api-inventory.md](./ticket-151-passive-form-api-inventory.md) — **P2, depends on 144+148+153+155:** passive forms/controls, linked API descriptions, router/GraphQL/source-map semantics; reuses 155 and never widens page-only following
- `152` `proposed` [ticket-152-supplied-session-differential.md](./ticket-152-supplied-session-differential.md) — **P2, depends on 129+148+149+153:** isolated anonymous/operator-supplied profiles over one fixed URL set; triage comparisons, no identifier or role mutation
- `153` `done` (2026-08-21, PR #66) [ticket-153-security-evidence-redaction.md](./ticket-153-security-evidence-redaction.md) — **P1/security, depends on 144:** shared versioned finding contract plus central header/cookie/query/config/body redaction, with retention and secret-absence proofs (including exported crawl-artifact header redaction). Unblocks 145, 146, 150, 151, 152, 154.
- `154` `proposed` [ticket-154-safe-error-disclosure-detection.md](./ticket-154-safe-error-disclosure-detection.md) — **P2, depends on 146+153:** passive multi-signal debug/error/directory-index/internal-disclosure findings over already-fetched responses; zero extra requests

### Static JavaScript URL discovery (2026-08-21)

- `155` `done` (2026-08-21) [ticket-155-static-javascript-url-discovery.md](./ticket-155-static-javascript-url-discovery.md) — **P1, blocks 156+157:** opt-in inline/linked-JS URL candidate inventory; explicit `--follow-js-urls` admits only strict page-like candidates; bounded/polite requests, provenance, artifact v3, run-scoped persistence/report; 846 non-integration tests passed; PostgreSQL test added but DSN unavailable; [review brief](./ticket-155-review-brief-2026-08-21.md)

### Speculative and render-time URL discovery follow-ups (2026-08-21)

The prototype's static and browser mechanisms deliberately split here. 156
owns false-positive filters, CSS semantics, priority, and the hard host cap.
157 owns observed browser traffic and raw-versus-hydrated DOM evidence. 158 is
an optional outcome-feedback layer and does not block either discovery path.

- `156` `done` (2026-08-21) [ticket-156-speculative-url-discovery-hardening-and-css.md](./ticket-156-speculative-url-discovery-hardening-and-css.md) — **P1, depends on 155; blocks 158:** unquoted absolute URLs, durable junk-filter reasons, inline/linked/imported CSS, explicit JS base policy, typed sibling provenance, href-first priority, and a persisted 50-outstanding-per-host speculative cap; artifact v4 and reports wired
- `157` `done` (2026-08-21) [ticket-157-selective-render-time-url-discovery.md](./ticket-157-selective-render-time-url-discovery.md) — **P1, depends on 155:** Playwright request outcomes and raw-versus-hydrated anchors, selective link-poor/script-heavy HTTP rendering, hard cost limits, inventory-only network observations, explicit rendered-link following, run-scoped evidence/reports, and real-Chromium smoke
- `158` `proposed` [ticket-158-adaptive-speculative-discovery-feedback.md](./ticket-158-adaptive-speculative-discovery-feedback.md) — **P3, depends on 156:** optional deterministic per-asset/host hit-rate throttle using only conclusive hard/soft misses; preserves all evidence and never treats operational failures as junk
- [Tickets 156–158 review brief](./ticket-156-158-url-discovery-review-brief-2026-08-21.md) — dependency graph, prototype deltas, safety decisions, risks, and required acceptance evidence

### Google-compatible JSON-LD parsing (2026-08-21)

- `159` `done` (2026-08-21, PR #67) [ticket-159-google-compatible-json-ld-single-unescape.md](./ticket-159-google-compatible-json-ld-single-unescape.md) — **P1, builds on completed 020:** exactly one HTML-unescape pass before RFC 8259 parsing; preserves raw source and residual double escapes, adds occurrence-level compatibility diagnostics/reporting and parser provenance, and never implies that syntax alone determines rich-result eligibility

### Raw-versus-rendered SEO parity audit (2026-08-24)

- `160` `done` (2026-08-24 PR #68, completed 2026-09-07 by ticket 161) [ticket-160-first-class-render-parity-audit.md](./ticket-160-first-class-render-parity-audit.md) — **P1, builds on completed 019+031+097+153+157+159:** `crawler-cli compare-renders` over exact URLs, `--csv-file`, and `--crawl-run-id`, same-navigation raw-versus-hydrated comparison, typed completeness, multiple typed findings, `crawler-cli/render-comparison/1` JSON plus CSV and self-contained HTML report with strata coverage and filter, and the `--fail-on`/`--fail-on-incomplete` exit contract. No Googlebot-emulation claim.
- `161` `done` (2026-09-07) [ticket-161-render-parity-run-selection-and-persistence.md](./ticket-161-render-parity-run-selection-and-persistence.md) — **P1, depends on 153+157+159 and the first delivery of 160:** run-backed `--crawl-run-id` selection with deterministic sampling and honest run/partial provenance, operator template labels plus computed path strata and stratum coverage/filtering in JSON/CSV/HTML, and the optional run-scoped render-comparison persistence session. Closes ticket 160.
- `162` `done` (2026-09-23) [ticket-162-orphaned-migration-manager-adapter.md](./ticket-162-orphaned-migration-manager-adapter.md) — **P2:** ticket 149 landed the relevant guard; retain `feature/3350-portal-url-policy-v1` as documented prior art, not merge material.

### Correctness backlog reconciliation (2026-09-23)

The 2026-07-22 wiring-audit tickets were renumbered from their colliding local
130–143 identifiers. Magento hygiene keeps 131–134 and the release remains
130; audit identifiers are now 163–176.

- `163` `proposed` [ticket-163-list-crawl-run-id-isolation.md](./ticket-163-list-crawl-run-id-isolation.md) — **P0:** List/CSV crawls honour `--crawl-run-id`
- `164` `proposed` [ticket-164-sitemap-hreflang-snapshot-retention.md](./ticket-164-sitemap-hreflang-snapshot-retention.md) — **P0:** retain sitemap-only hreflang in run snapshots
- `165` `proposed` [ticket-165-skip-outcomes-session-budget.md](./ticket-165-skip-outcomes-session-budget.md) — **P1:** make `--max-pages` semantics consistent for skips and content
- `166` `proposed` [ticket-166-playwright-max-response-bytes-text.md](./ticket-166-playwright-max-response-bytes-text.md) — **P1:** cap parsed Playwright text as well as body
- `167` `proposed` [ticket-167-obscura-fetch-auth-status-parity.md](./ticket-167-obscura-fetch-auth-status-parity.md) — **P1:** prevent silent Obscura auth/status falsehoods
- `168` `proposed` [ticket-168-playwright-per-host-proxy-select.md](./ticket-168-playwright-per-host-proxy-select.md) — **P1:** make browser `per-host` proxy selection honest
- `169` `proposed` [ticket-169-custom-ua-vs-per-domain-ua.md](./ticket-169-custom-ua-vs-per-domain-ua.md) — **P2:** restore per-domain UA precedence
- `170` `proposed` [ticket-170-challenge-escalate-fresh-proxy.md](./ticket-170-challenge-escalate-fresh-proxy.md) — **P2:** select a distinct proxy for bounded challenge escalation
- `171` `proposed` [ticket-171-rate-limit-cli-gui-delay.md](./ticket-171-rate-limit-cli-gui-delay.md) — **P2:** wire crawl rate limit through CLI/GUI
- `172` `proposed` [ticket-172-gui-crawl-dsn-env.md](./ticket-172-gui-crawl-dsn-env.md) — **P2:** keep GUI DSNs off argv
- `173` `proposed` [ticket-173-gui-run-scoped-link-graph.md](./ticket-173-gui-run-scoped-link-graph.md) — **P2:** scope GUI link graph to the selected run
- `174` `proposed` [ticket-174-refresh-days-run-scope.md](./ticket-174-refresh-days-run-scope.md) — **P3:** document and lock refresh-days scope
- `175` `proposed` [ticket-175-concurrency-skip-sitemaps-hygiene.md](./ticket-175-concurrency-skip-sitemaps-hygiene.md) — **P3:** resolve config/CLI drift
- `176` `proposed` [ticket-176-list-max-pages-semantics.md](./ticket-176-list-max-pages-semantics.md) — **P2:** make GUI List max-pages honest

### Shopify crawl correctness follow-ups (2026-09-23)

- `177` `proposed` [ticket-177-raw-http-sitemap-fetch-under-js.md](./ticket-177-raw-http-sitemap-fetch-under-js.md) — **P1:** fetch sitemap documents as raw HTTP under browser page backends
- `178` `proposed` [ticket-178-orphans-use-run-scoped-inlinks.md](./ticket-178-orphans-use-run-scoped-inlinks.md) — **P1:** define orphans from same-run internal inlinks
- `179` `proposed` [ticket-179-playwright-redirect-status-evidence.md](./ticket-179-playwright-redirect-status-evidence.md) — **P1:** retain requested/final redirect status evidence in Playwright
- `180` `proposed` [ticket-180-resume-seed-mismatch-intent.md](./ticket-180-resume-seed-mismatch-intent.md) — **P1:** do not silently discard changed resume seeds
- `181` `proposed` [ticket-181-rate-limit-vs-challenge-accounting.md](./ticket-181-rate-limit-vs-challenge-accounting.md) — **P2:** distinguish 429 rate limits from challenges and count distinct URLs
- `182` `proposed` [ticket-182-playwright-system-chromium-discovery.md](./ticket-182-playwright-system-chromium-discovery.md) — **P3:** bounded system-Chromium fallback after bundled launch failure

### Deterministic technical audit (2026-09-24)

- `183` `in review` [Audit check registry, provenance and coverage](./ticket-183-technical-audit-coverage-contract.md) — **P1**; [PR #88](https://github.com/user256/crawler_cli/pull/88).
- `184` `in review` [Fix false indexing-directive conflicts](./ticket-184-technical-audit-explicit-robots-conflicts.md) — **P1**; [PR #89](https://github.com/user256/crawler_cli/pull/89).
- `185` `in review` [Automate live rechecks and gate client publication](./ticket-185-technical-audit-live-rechecks-publication-gate.md) — **P1**; [PR #90](https://github.com/user256/crawler_cli/pull/90).
- `186` `in review` [Correct audit link graph and multi-issue classification](./ticket-186-technical-audit-link-graph-correctness.md) — **P1**; [PR #91](https://github.com/user256/crawler_cli/pull/91). Optional Search Console/analytics CSV URLs now join the run graph; current sitemap URL ingestion remains open in ticket 204.
- `187` `in review` [Make similarity and internal authority evidence representative](./ticket-187-technical-audit-content-similarity-authority.md) — **P1**; [PR #92](https://github.com/user256/crawler_cli/pull/92). Template-group classification is explicitly unavailable pending a stored template signal.
- `188` `in review` [Define and validate the audit Sheets template contract](./ticket-188-technical-audit-sheets-template-contract.md) — **P1**; [PR #93](https://github.com/user256/crawler_cli/pull/93), stacked on PR #92; its full suite also passes on the PR #94 stack (1,445 passed, 57 skipped), superseding the earlier temp-quota caveat.
- `189` `in review` [Validate, verify and recover Google Sheets publication](./ticket-189-technical-audit-sheets-publication-recovery.md) — **P1**; [PR #94](https://github.com/user256/crawler_cli/pull/94), stacked on PR #93; full suite passes, 1,445 passed and 57 skipped.
- `190` `in review` [Automate metadata, language and indexability inventories](./ticket-190-technical-audit-metadata-locale-inventory.md) — **P1**; [PR #95](https://github.com/user256/crawler_cli/pull/95), stacked on PR #94; full suite passes, 1,448 passed and 57 skipped. Thin-content scoring and rendered confirmation remain explicit limitations.
- `191` `in review` [Automate canonical and hreflang consistency checks](./ticket-191-technical-audit-canonical-hreflang-checks.md) — **P1**; [PR #96](https://github.com/user256/crawler_cli/pull/96), stacked on PR #95; full suite passes, 1,452 passed and 57 skipped. Sitemap hreflang comparison and live target checks remain unavailable.
- `192` `in review` [Automate current robots and sitemap evidence](./ticket-192-technical-audit-robots-sitemap-collector.md) — **P1**; [PR #97](https://github.com/user256/crawler_cli/pull/97), stacked on PR #96; full suite passes, 1,457 passed and 57 skipped; all 26 CI checks pass. Rendered/internal-link purpose classification remains open.
- `193` `in review` [Automate URL variants, canonicalized parameters and soft-404 probes](./ticket-193-technical-audit-url-variants-soft404.md) — **P1**; [PR #98](https://github.com/user256/crawler_cli/pull/98), stacked on PR #97; full suite passes, 1,462 passed and 57 skipped; all 26 CI checks pass. Rendered SPA/error-state, geo, and route/entity intent remain analyst follow-ups.
- `194` `in review` [Integrate rendered, mobile, geo and resource evidence](./ticket-194-technical-audit-render-geo-resource-evidence.md) — **P2**; [PR #99](https://github.com/user256/crawler_cli/pull/99), stacked on PR #98; full suite passes, 1,466 passed and 57 skipped; all 26 CI checks pass. Geo comparisons, interactions/screenshots, robots-aware resource impact, layout measurement, external-link and non-HTML asset checks remain open.
- `195` `in review` [Add versioned structured-data audit rules](./ticket-195-technical-audit-structured-data-rules.md) — **P2**; [PR #100](https://github.com/user256/crawler_cli/pull/100), stacked on PR #99; full suite passes, 1,474 passed and 57 skipped; all 26 CI checks pass after pinned-Ruff formatting fixes. Content/image/URL equivalence, contextual/restricted eligibility, and live Google validation remain analyst follow-ups.
- `196` `in review` [Automate timing distributions, conditional requests and optional log evidence](./ticket-196-technical-audit-performance-conditional-logs.md) — **P2**; [PR #101](https://github.com/user256/crawler_cli/pull/101), stacked on PR #100; 1,483 passed, 57 skipped; all 26 CI checks pass; field-CWV/browser-trace and validated access-log ingestion remain open pending source contracts.
- `197` `in review` [Build recipient-focused audit actions and healthy overview](./ticket-197-technical-audit-client-report-projection.md) — **P1**; [PR #102](https://github.com/user256/crawler_cli/pull/102), stacked on PR #101; 1,487 passed, 57 skipped; all 26 CI checks pass; depth/thin-content and business-specific severity remain explicitly unknown/analyst supplied.
- `198` `in review` [Prove the complete audit workflow and correct completion claims](./ticket-198-technical-audit-end-to-end-acceptance.md) — **P1**; [PR #103](https://github.com/user256/crawler_cli/pull/103), stacked on PR #102; 1,488 passed, 58 skipped, Ruff/mypy and all 26 CI checks pass, including PostgreSQL integration; live Sheets publication and representative-audit trace remain unverified.
- `199` `in review` [Move the audit skill to its owning repo and link all agents](./ticket-199-technical-audit-shared-skill-location.md) — **P2**; [PR #104](https://github.com/user256/crawler_cli/pull/104), stacked on PR #103; repo-owned skill validated, all five configured links resolve to the shared directory, and all 26 CI checks pass.
- `200` `in review` [Complete technical-audit skill requirement traceability](./ticket-200-technical-audit-skill-requirement-traceability.md) — **P1**; section-level inventory and guard submitted in [PR #109](https://github.com/user256/crawler_cli/pull/109), all 26 CI checks pass; per-control requirement mapping remains open under ticket 203.
- `201` `in review` [Handle legacy crawl snapshot schemas in technical audits](./ticket-201-technical-audit-legacy-snapshot-compatibility.md) — **P1**; [PR #105](https://github.com/user256/crawler_cli/pull/105), stacked on PR #104; real-run replay succeeds, and all 26 CI checks pass including PostgreSQL regression.
- `202` `proposed` [Audit non-production hosts and HTTPS hygiene](./ticket-202-technical-audit-nonproduction-hosts-https.md) — **P2**; uncovered requirement from the skill-coverage map; reuse URL/sitemap/redirect/exposure evidence.
- `203` `proposed` [Make technical-audit traceability requirement-level](./ticket-203-technical-audit-control-level-traceability.md) — **P1**; section-level control mapping does not prove each substantive skill requirement is mapped to evidence, tests, and an owner.
- `204` `in review` [Include supplied URL inventories in orphan analysis](./ticket-204-technical-audit-supplied-url-inventories.md) — **P2**; sitemap join and recipient projection submitted in [PR #106](https://github.com/user256/crawler_cli/pull/106), reusing CSV sources from PR #91.
- `205` `proposed` [Classify rendered links blocked by robots rules](./ticket-205-technical-audit-rendered-robots-link-purpose.md) — **P1**; rendered link instances need matched-rule and conservative purpose evidence.
- `206` `proposed` [Reconcile sitemap, HTML, and HTTP hreflang evidence](./ticket-206-technical-audit-hreflang-channel-reconciliation.md) — **P2**; audit-side channel comparison depends on ticket 164's retained sitemap annotations.
- `207` `in review` [Preserve incomplete live-recheck outcomes](./ticket-207-live-recheck-incomplete-state.md) — **P1**; keeps inconclusive observations from being interpreted as intermittent or persistent failures; [PR #107](https://github.com/user256/crawler_cli/pull/107).
- `208` `in review` [Capture pre-scroll and scroll-revealed rendered links](./ticket-208-rendered-link-scroll-evidence.md) — **P2**; adds bounded same-page/device rendered-link states without clicking controls; [PR #110](https://github.com/user256/crawler_cli/pull/110).
- `214` `proposed` [Stop reporting the Next.js RSC payload script as broken schema](./ticket-214-schema-parser-nextjs-rsc-payload-noise.md) — **P2**; untyped hydration scripts surface as `BrokenScriptSchema` site defects.
- `215` `proposed` [Do not classify a 200 page embedding Turnstile as a challenge](./ticket-215-challenge-detector-turnstile-false-positive.md) — **P1**; rainbet crawl 2026-09-25 recorded 399 real pages as blocked and stored no content.
- `216` `proposed` [Use Wayback Machine URL history as an audit inventory](./ticket-216-technical-audit-wayback-url-history.md) — **P1**; rainbet: 3,378 formerly live URLs now fail, invisible to the crawl; feeds 204.
- `217` `proposed` [Weight failing URLs by supplied backlink data](./ticket-217-technical-audit-backlink-weighting.md) — **P1**; Ahrefs/Semrush/GSC exports; rainbet dead URLs held ~34.8k referring domains (non-unique sum).
- `218` `proposed` [Generate a deterministic redirect map for failing URLs](./ticket-218-technical-audit-redirect-map.md) — **P1**; rule-based targets, similarity only as review-required, detect redirects into 404s; depends on 216/217.
- `219` `proposed` [Flag unresolved route placeholders in raw HTML links](./ticket-219-link-quality-route-placeholders.md) — **P2**; rainbet raw HTML carried 18,080 `[slug]` links that 404.
- `220` `proposed` [Detect growing internal URL families from repeated observations](./ticket-220-technical-audit-growing-url-families.md) — **P2**; route/parameter families beyond tracking params; growth only with timestamped re-observation.
- `221` `proposed` [Flag locale pages that reuse default-locale metadata](./ticket-221-technical-audit-untranslated-locale-metadata.md) — **P3**; extends 190.
- `222` `proposed` [Qualify orphan claims by crawl coverage](./ticket-222-orphans-coverage-qualification.md) — **P1**; capped crawls must not state absolute orphan status; complements 178.
- `223` `proposed` [Publish into a mapped client ticket template](./ticket-223-sheets-mapped-client-template.md) — **P2**; Canonicals Tickets/Config template; `sheets.copyTo` fallback under `drive.file`; builds on 188/189.
- `224` `proposed` [Coherent browser fetch profile and a shared live-check rate limit](./ticket-224-fetch-profile-and-shared-rate-limit.md) — **P1**; impersonation implies matching UA; one per-host budget across live modules; relates to 169/181.
- `225` `proposed` [Show the run and audit dates in the Markdown projection](./ticket-225-technical-audit-markdown-run-date.md) — **P3**; rainbet master rerun printed `Date: unknown`.

### Rainbet audit delivery and QA follow-up (2026-09-28)

The two-track plan separates the immediate, evidence-backed corrections needed
to finish the current Rainbet audit from reusable process work. All tickets in
this section are proposed; filing them does not claim that the audit or any
process change is complete. Tickets 240–246 do not depend on tickets 247–253.

- `240` `proposed` [Correct Rainbet validation statuses and client row selection](./ticket-240-rainbet-validation-status-and-client-selection.md) — **P0:** correct validation logic, omit no-action client rows, and retain the complete internal ledger.
- `241` `proposed` [Finish game-discovery checks and qualify Rainbet bot claims](./ticket-241-rainbet-game-discovery-and-bot-claims.md) — **P0:** finish Q23 and bound game-link, bot, and popup assertions to observed evidence.
- `242` `proposed` [Reverify Rainbet backlink and legacy redirect findings](./ticket-242-rainbet-backlinks-and-legacy-reverification.md) — **P0:** resolve Q19 and correct dates, totals, destinations, and retired-page advice.
- `243` `proposed` [Finish outstanding Rainbet checks and close the scope](./ticket-243-rainbet-finish-outstanding-audit-checks.md) — **P0:** prioritise Q32, finish feasible checks, and record precise external evidence gaps.
- `244` `proposed` [Correct Rainbet counts and incomplete remediation advice](./ticket-244-rainbet-factual-and-remediation-corrections.md) — **P0:** reconcile counts, link units, remediation branches, and security wording.
- `245` `proposed` [Repair Rainbet sheet readability and navigation](./ticket-245-rainbet-sheet-layout-and-navigation.md) — **P0:** fit populated content, repair navigation, reconcile final counts, and visually inspect the sheet.
- `246` `proposed` [Sign off the finished Rainbet audit for client review](./ticket-246-rainbet-final-qa-and-client-handoff.md) — **P0, depends on 240–245:** prepare one corrected audit for John’s review without external sending.
- `247` `proposed` [Do not populate client sheets when nothing is wrong](./ticket-247-audit-omit-no-action-client-rows.md) — **P1:** retain all checks internally while omitting Healthy/pass/N/A/no-action client rows.
- `248` `proposed` [Require claim-specific evidence for status changes](./ticket-248-audit-claim-specific-validation.md) — **P1:** prevent unrelated validation from promoting a finding to Issue.
- `249` `proposed` [Compare bot and user navigation without unsupported conclusions](./ticket-249-audit-bot-render-and-navigation-parity.md) — **P1:** separate raw/rendered, bot/user, and access-state evidence.
- `250` `proposed` [Reconcile audit counts, freshness and claim scope](./ticket-250-audit-count-freshness-and-scope-reconciliation.md) — **P1:** attach each assertion to its population, date, source, unit, and sample scope.
- `251` `proposed` [Review remediation branches and policy claims before publication](./ticket-251-audit-remediation-and-policy-review.md) — **P1:** ensure advice and conditional acceptance criteria follow the observed issue.
- `252` `proposed` [Verify published sheet content, links and visual layout](./ticket-252-audit-sheet-semantic-and-visual-qa.md) — **P1:** require semantic read-back, working links, current totals, and visual sign-off.
- `253` `proposed` [Keep client audit delivery independent of process improvements](./ticket-253-audit-delivery-independent-of-process-work.md) — **P1:** make the two-queue delivery rule part of the shared workflow.

See [delivery brief](./technical-audit-review-2026-09-24.md) for ordered phases,
existing-ticket reuse and review finding coverage.

### UA parity and third-party URL sources (2026-09-28)

- `254` `proposed` [Compare responses across crawler and browser User-Agents](./ticket-254-compare-agents-ua-differential.md) — **P1, depends on 224:** `compare-agents` fetches the same URLs as Googlebot, Screaming Frog and a browser from one egress, subtracts A/A noise, adds an optional `--render` pass, and reports differences for review, never as a cloaking verdict.
- `255` `proposed` [Add a UA-parity check to the technical audit's server-configuration group](./ticket-255-technical-audit-agent-parity-check.md) — **P2, depends on 254:** an opt-in `agent-parity` check alongside the host/variant and soft-404 probes (193/236); differences get Review status only.
- `256` `proposed` [Accept a Semrush Organic Pages export as a URL source](./ticket-256-semrush-organic-pages-url-source.md) — **P1:** fixes the `csv_urls` fallback that turned the rainbet export into 542 junk URLs; recognises Semrush exports; keeps traffic for `--top`/`--order-by`; flags ranking dev/staging hosts; shares the loader with 217.
- `257` `proposed` [Persist run-scoped custom probe results for generic GUI reporting](./ticket-257-run-scoped-custom-probe-results.md) — **P1, extends 193/236:** save actual bounded host/protocol, URL-variant and fictional-URL outcomes against a crawl run; generic consumers query only those rows, never source imports or inferred URLs.
- `263` `implemented (local)` [Answer the audit template's Questions tab from a saved technical audit](./ticket-263-technical-audit-question-runner.md) — **P1:** question registry, site profile, `technical-audit-questions` runner with Q26 run gate, data tabs, draft tickets and header-aware Tickets publish; answers 11 questions, the rest Pending with reasons. Real-run publish review outstanding.
- `264` `proposed` [Stored-HTML detectors for the question runner](./ticket-264-question-detectors-stored-html.md) — **P1, depends on 263:** 17 HTML-only detectors plus answerers over contract checks as their collectors land.
- `265` `proposed` [Site-profile detectors for the question runner](./ticket-265-question-detectors-site-profile.md) — **P1, depends on 263:** template/hub/parameter/affiliate/host/AI-policy rules; Rainbet profile first.
- `266` `proposed` [Render, probe and external detectors for the question runner](./ticket-266-question-detectors-render-probe-external.md) — **P2, depends on 263:** rendered, mobile, probe and third-party evidence; heuristics capped at Needs validation.
- Tickets **267–370** create one local implementation record for every Questions-tab row, Q1–Q104. See [the question-level implementation queue](./technical-audit-question-implementation-queue-2026-10-06.md). It refines detector batches 264–266; the 11 existing answerers are marked implemented locally (four partial, three without tests) and the rest are proposed; priorities follow the registry. Q104 is a supplied-evidence/manual workflow, not a crawler-only detector. Next unreserved ticket number is **400**.
- `371` `done` [Decode JSONB in Stream B report collectors](./ticket-371-stream-b-jsonb-decoding.md) — **P1, Stream B QA fix.**
- `372` `done` [Stop SVG titles and feed links tripping Q10 and Q12](./ticket-372-stream-b-svg-title-false-positives.md) — **P1, Stream B QA fix.**
- `373` `done` [Only treat real locale folders as locales in Q41](./ticket-373-stream-b-locale-folder-detection.md) — **P1, Stream B QA fix.**
- `374` `done` [Exclude homepage variants from Q73](./ticket-374-stream-b-q73-homepage-variants.md) — **P2, Stream B QA fix.**
- `375` `done` [Detect X-Robots-Tag by header name in Q87](./ticket-375-stream-b-q87-x-robots-tag.md) — **P1, Stream B QA fix.**
- `376` `done` [Never answer Healthy from a zero tested population](./ticket-376-stream-b-zero-population-healthy.md) — **P1, Stream B QA fix.**
- `377` `done` [Separate locale markup rows from Q32 and restore review qualifications](./ticket-377-stream-b-locale-check-populations.md) — **P1, Stream B QA fix.**
- `378` `done` [Keep heavy stored-HTML reports out of the default report run](./ticket-378-stream-b-report-cli-defaults.md) — **P2, Stream B QA fix.**
- `379` `done` [Scan stored HTML once, without loading the whole run into memory](./ticket-379-stream-b-stored-html-single-pass.md) — **P2, Stream B QA fix.**
- `380` `done` [Make profile page facts run-scoped and meaningful](./ticket-380-stream-b-profile-page-facts.md) — **P2, Stream B QA fix.**
- `381` `done` [Report header/HTML canonical mismatches as their own finding](./ticket-381-stream-b-q94-canonical-rows.md) — **P3, Stream B QA fix.**
- `382` `done` [Make Q54 rows traceable to individual images](./ticket-382-stream-b-q54-image-identity.md) — **P3, Stream B QA fix.**
- `383` `done` [Detect redirecting link targets by final URL, and compare canonicals normalised](./ticket-383-stream-b-link-target-redirects.md) — **P1, Stream B QA fix.**
- `384` `done` [Finish the Q81 run gate that Stream B started](./ticket-384-stream-b-q81-gate-scope.md) — **P2, Stream B QA fix.**
- `385` `done` [Tighten the soft-404 and discovery-provenance collectors Stream B added](./ticket-385-stream-b-soft404-and-provenance.md) — **P2, Stream B QA fix.**
- `386` `implemented (local)` [Keep Q28, Q31 and locale probes below Healthy when a field was never recorded](./ticket-386-stream-c-untested-fields-healthy.md) — **P1, Stream C QA fix.**
- `387` `implemented (local)` [Do not raise Q102 when robots blocking was never checked](./ticket-387-stream-c-q102-robots-unknown.md) — **P1, Stream C QA fix.**
- `388` `implemented (local)` [Treat a redirected robots.txt without a body as unknown in Q96](./ticket-388-stream-c-q96-redirected-robots.md) — **P1, Stream C QA fix.**
- `389` `implemented (local)` [Break the import cycle between the question runner and observed answerers](./ticket-389-stream-c-answerer-import-cycle.md) — **P2, Stream C QA fix.**
- `390` `implemented (local)` [Say truthfully how Q46 footer evidence is collected](./ticket-390-stream-c-q46-footer-parity-docs.md) — **P3, Stream C QA fix.**
- `391` `implemented (local)` [Tighten observed-answer edge cases](./ticket-391-stream-c-observed-answer-edge-cases.md) — **P3, Stream C QA fix.**
- `392` `implemented (local)` [Downgrade other answers only when a run gate answers Yes](./ticket-392-integration-run-gate-scope.md) — **P1, integration QA fix.**
- `393` `implemented (local)` [Count the indexable-page population for Q15 and Q71](./ticket-393-integration-indexable-population.md) — **P1, integration QA fix; Q39 part open.**
- `394` `proposed` [Give Q94 and Q41 rows their own ticket language](./ticket-394-integration-q94-q41-ticket-language.md) — **P3, integration QA.**
- `395` `implemented (local)` [Trust frontier depth for Q44 only when it is click depth from a homepage](./ticket-395-integration-q44-click-depth-provenance.md) — **P1, integration QA fix; homepage BFS follow-up open.**
- `396` `implemented (local)` [Never answer Q91 Healthy from an empty or partial link population](./ticket-396-integration-q91-zero-population.md) — **P1, integration QA fix.**
- `397` `implemented (local)` [Collect empty-anchor facts in the shared stored-HTML pass, bounded per page](./ticket-397-integration-empty-anchor-single-pass.md) — **P1, integration QA fix.**
- `398` `implemented (local)` [Make Q88 match its registry entry and keep untemplated pages in scope](./ticket-398-integration-q88-registry-alignment.md) — **P2, integration QA fix.**
- `399` `proposed` [Stream A follow-ups found in integration QA](./ticket-399-integration-stream-a-followups.md) — **P3, integration QA.**

Deferred lanes remain below.

**Deferred lanes**

12. **deferred** `035` [Redis frontier](./ticket-035-redis-frontier-queue.md) — architectural/infra
13. **proposed** `075` [Casino Guru review ingestion](./ticket-075-casino-guru-review-ingestion.md) — blocked on reliable authorised fetch path
