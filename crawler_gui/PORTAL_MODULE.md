# Self-hosted crawler portal module

`crawler_cli` remains the crawl engine. The portal is a separate deployable
module that owns users, workspaces, job control, and the browser UI; it never
lets a browser process start a crawl directly.

## Deployment shape

```
browser ── HTTPS ──> portal-web ──> portal-api ──> job queue ──> crawler worker
                         │                │                         │
                         └──────────── PostgreSQL <──────────────────┘
```

Ship a small Compose bundle:

- `portal-web` — serves this UI as static files.
- `portal-api` — authenticated JSON API and report/export endpoints.
- `crawler-worker` — invokes the library API, enforces crawl policy, and emits
  progress; scale this independently.
- `postgres` — crawler data plus portal users, workspaces, memberships and job
  metadata. An existing managed Postgres instance is supported too.
- Optional `redis` — job broker/progress fan-out for multi-worker installs;
  the initial single-node edition can use Postgres-backed jobs.

## Portal surface

| Route | Purpose |
|---|---|
| `/workspaces` | Create/select an organisation or personal workspace. |
| `/crawls` | Run history, status, owner, timestamps, retention and actions. |
| `/crawls/new` | Seed URL, list/sitemap mode, limits, robots, rendering and schedules. |
| `/crawls/:id/runs/:runId` | Run-scoped overview, URL table, filters and page detail. |
| `/crawls/:id/runs/:runId/issues` | Indexability, response, canonical, hreflang and analytics findings. |
| `/crawls/:id/runs/:runId/intent-overlap` | Existing map/table viewer backed by a deterministic run-scoped export. |
| `/settings` | Workspace policy, users, retention, API tokens and outbound-network rules. |

The current `crawler_gui` grid becomes the run detail route. Its fixture contract
is replaced by `GET /api/v1/crawls/:crawlId/runs/:runId/ui-snapshot`; the intent
viewer uses `GET /api/v1/crawls/:crawlId/runs/:runId/intent-report`. Both routes
must select an explicit `runId`, never a mutable latest-state projection.

## API and job contract

```text
POST   /api/v1/crawls                  create a queued job
GET    /api/v1/crawls                  list workspace crawls
GET    /api/v1/crawls/:id              job and run history
POST   /api/v1/crawls/:id/cancel       cooperative worker cancellation
POST   /api/v1/crawls/:id/runs/:run/resume
GET    /api/v1/crawls/:id/runs/:run/events  progress SSE stream
GET    /api/v1/crawls/:id/runs/:run/ui-snapshot
GET    /api/v1/crawls/:id/runs/:run/export/*
```

The API records the selected configuration snapshot and starts the engine with a
new or explicit resumed run. Workers write only through `crawler_cli`'s store;
the API reads the snapshot-backed report methods. This preserves the historical
semantics implemented in Ticket 095.

## Safe default for a giveaway/self-host edition

- One local administrator on first boot; optional OIDC later.
- Workspace isolation via a `workspace_id` on portal-owned crawl/job records and
  authorization checks on every API query. Do not expose raw database access.
- Deny private, loopback, link-local and metadata-service targets by default;
  re-check resolved IPs at connection time to prevent DNS rebinding.
- Keep robots enabled, impose per-workspace concurrency/page/time budgets, and
  require an administrator setting before proxies or browser rendering are used.
- Store credentials as encrypted secret references, never in crawl configs,
  reports, logs or browser responses.
- Retention defaults: preserve run summaries and findings; make raw HTML and
  screenshots opt-in with a pruning schedule.

## Practical release sequence

1. **Community single-node:** Compose, local login, one workspace, queued
   spider/list crawls, history, run detail and CSV/HTML exports.
2. **Team:** invitations/roles, schedules, SSE progress, API tokens and object
   storage for larger exports.
3. **Scale:** Redis workers, per-workspace quotas, audit log, OIDC/SAML and
   bring-your-own Postgres/object storage.

The boundary is intentionally clean: users can run the engine through CLI or
Python without the portal, while a self-host operator can add the portal without
forking the crawler core.
