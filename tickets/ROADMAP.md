# crawler_cli Ticket Roadmap

**Last reconciled:** 2026-07-15
**Authoritative register:** [ticket-queue.md](./ticket-queue.md)

This is the dependency-ordered delivery view. Ticket files remain the source
of truth for scope and acceptance criteria.

## Current position

- Tickets 101–105 are merged on `master` after code, ticket, and cross-feature
  review. Their relationship, parameterised-URL, AMP, thin-content, and
  time-sequenced fields now form the baseline for future report work.
- Tickets 108 and 109 record the two bounded review remediations. Ticket 108 is
  correctness-sensitive and should land before the interactive report consumes
  AMP classifications. Ticket 109 completes diagnostic fields without changing
  the reviewed thin-content policy.
- PR #110 was explicitly excluded from this review and was not inspected,
  modified, reopened, or merged.

## Delivery order

### 1. Crawl correctness and persistence safety

1. [087 — Sitemap scope, budget, and politeness](./ticket-087-sitemap-scope-budget-politeness.md) — P0.
2. [088 — Robots RFC 9309 follow-up](./ticket-088-robots-rfc9309-follow-up.md) — P0.
3. [089 — Challenge hard-stop persistence](./ticket-089-challenge-hard-stop-persistence.md) — P0.
4. [092 — Persistence-failure exit policy](./ticket-092-persist-failure-exit-policy.md) — P1.
5. [108 — AMP classification evidence hardening](./ticket-108-amp-classification-evidence-hardening.md) — P1; after 103.

### 2. Run-aware reporting and verification

1. [095 — Run-aware snapshots/reporting](./ticket-095-run-aware-snapshots-reporting.md) — after 086.
2. [096 — Persistence coverage gate](./ticket-096-persistence-coverage-gate.md).
3. [093 — CLI/config numeric validation](./ticket-093-cli-config-numeric-validation.md).
4. [099 — Crawl-run isolation follow-ups](./ticket-099-crawl-run-isolation-followups.md).
5. [109 — Thin-content diagnostic completeness](./ticket-109-thin-content-diagnostic-completeness.md) — after 104 and before finalising the Ticket 106 page schema.

### 3. Interactive intent-overlap reporting

1. [106 — Machine-readable JSON report](./ticket-106-report-data-json-export.md) — consume the merged 101–105 fields plus the 108/109 outcomes.
2. [107 — Self-contained interactive HTML report](./ticket-107-interactive-html-cluster-report.md) — after 106.

### 4. Lower-priority hardening

1. [098 — Packaging/docs/release hygiene](./ticket-098-packaging-docs-release-hygiene.md).
2. [100 — Obscura installer test hardening](./ticket-100-obscura-installer-test-hardening.md).
3. [111 — CI artifact/action runtime hygiene](./ticket-111-ci-artifact-action-runtime-hygiene.md).

## Deferred lanes

- [035 — Redis frontier queue](./ticket-035-redis-frontier-queue.md) remains an architectural/infra change.
- [075 — Casino Guru review ingestion](./ticket-075-casino-guru-review-ingestion.md) remains blocked on a reliable authorised fetch path.

## Ordering rules

- Correctness and evidence hardening precede presentation work that consumes the affected fields.
- Ticket 107 cannot start before Ticket 106 defines and tests the JSON contract.
- External/manual evidence is recorded as a blocker; it is never inferred from unit tests.
- New remediation work uses the next free number, 112; number 110 was left unused in this pass to avoid collision with the explicitly excluded PR reference.
