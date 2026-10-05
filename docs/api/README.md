# API

Base path: `/api/v1`. JSON only. Auth: `Authorization: Bearer <Cognito access token>`.
Interactive docs: `http://localhost:8000/docs` (LOCAL and DEV only; off in PROD).
Contract file: `openapi/openapi.json` (generated — do not edit). Current version: see `openapi/CHANGELOG.md`.

## Endpoints (foundation)

| Area          | Method & path                                                                                              | Permission                                 |
| ------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| health        | `GET /health` · `GET /ready`                                                                               | public                                     |
| auth          | `GET /auth/me`                                                                                             | signed in                                  |
| users         | `GET /users` · `POST /users`                                                                               | `users:read` · `users:manage`              |
| clinics       | `GET /clinics` · `POST /clinics`                                                                           | signed in · `clinics:create`               |
|               | `GET/PATCH /clinics/{clinic_id}`                                                                           | `clinics:read` · `clinics:write`           |
|               | `GET/POST /clinics/{clinic_id}/team`                                                                       | `clinics:read` · `team:manage`             |
| doctors       | `GET/POST /clinics/{clinic_id}/doctors` · `PATCH …/{doctor_id}`                                            | `doctors:read` · `doctors:write`           |
| assignments   | `GET/POST /clinics/{clinic_id}/assignments` · `DELETE …/{id}`                                              | `clinics:read` · `assignments:manage`      |
| profiles      | `GET/PUT /clinics/{clinic_id}/profile`                                                                     | `profile:read` · `profile:write`           |
| assets        | `POST …/assets/uploads` · `POST …/assets/{id}/confirm` · `GET …/assets` · `GET …/assets/{id}/download-url` | `assets:upload` / `assets:read`            |
| approvals     | `POST …/approvals/actions` · `GET …/approvals` · `GET …/approvals/{id}`                                    | per action (see contracts)                 |
| audit log     | `GET …/audit-events`                                                                                       | `audit_log:read`                           |
| work items    | `GET/POST …/work-items` · `GET/PATCH …/work-items/{id}`                                                    | `work_items:read` · `work_items:write`     |
| notifications | `GET /notifications` · `POST /notifications/{id}/read`                                                     | own only                                   |
| snapshots     | `GET/POST …/snapshots`                                                                                     | `snapshots:read` · `snapshots:write`       |
| reports       | `GET/POST …/reports` · `GET …/reports/{id}`                                                                | `reports:read` · `reports:write`           |
| presence      | `GET/POST …/presence-profiles` · `PATCH …/presence-profiles/{id}` (confirm/reject)                         | `presence:read` · `presence:write`         |
| assessments   | `POST …/assessments` (202, queued) · `GET …/assessments` · `GET …/assessments/{id}`                        | `assessments:request` · `assessments:read` |
| chat          | `GET/POST …/chat/messages` · `POST …/chat/read` · `GET /chat/inbox`                                       | `chat:read` · `chat:write`                 |
| connections   | `GET …/connections` · `POST …/connections/{platform}/start` · `…/complete` · `…/disconnect`                | `connections:read` · `connections:manage`  |
| settings      | `GET/PATCH /settings/platform` · `GET /settings/integrations` · `/auth/me/notification-settings` · `/auth/me/avatar…` | signed in · `settings:manage`       |

`…` = `/clinics/{clinic_id}`.

Notes:

- There is **one** Digital Presence Assessment endpoint family. There are no per-channel
  endpoints (`/audits`, `/digital-presence`, `/social-media` were removed in the 2026-09 review).
- Clinic users only see **published** assessments and reports. Publishing goes through
  approvals and needs `approvals:publish` (Radial Pulse staff only).
- Assessment results are written only by the worker (`assessments:write_results` is a
  service-only permission; no HTTP endpoint accepts results).

## Conventions

- **Errors** are RFC 9457 `application/problem+json`:
  `{ "type": "forbidden", "title": "Not allowed", "status": 403, "detail": "…", "request_id": "…" }`.
  Validation errors add `errors: [{loc, msg, type}]` and never echo your input back.
- **401** no/invalid token · **403** not allowed (or `not_provisioned`) · **404** not found
  _or no access to that clinic_ · **409** state/version conflict · **422** invalid input.
- **Pagination**: `?limit=50&offset=0` → `{ items, total, limit, offset }` (max limit 200).
- **Ids** are UUIDs. **Times** are ISO 8601 with timezone (UTC).
- **Request ids**: send `X-Request-ID` or get one back on every response; quote it in bug reports.
- **Versioning**: breaking changes go to `/api/v2`. Adding optional fields/endpoints is not breaking.

## Changing the API (contract workflow)

```bash
make openapi                         # regenerate openapi/openapi.json
# bump CONTRACT_VERSION in app/core/contract.py, add "## vX.Y.Z" to openapi/CHANGELOG.md
git add openapi app/core/contract.py # commit the regenerated contract in the SAME PR
```

CI regenerates the contract and fails if the committed copy is stale or the version was not
bumped. Releasing it to the frontend: [contract-versioning.md](contract-versioning.md).

## Rules for new endpoints

1. Clinic data lives under `/clinics/{clinic_id}/…` and depends on `clinic_access(Permission.X)`.
2. Router → one service call. No SQL in routers.
3. State changes write an audit event (`app/services/audit.py`) in the same transaction.
4. Request models reject unknown fields (`ApiModel`). Response models never expose
   storage keys, tokens or other clinics' ids.
5. Add the route to `tests/api/test_tenant_isolation.py`.
   A new clinic-scoped **table** also needs a row-level security policy in its migration
   (`tests/integration/test_rls.py` fails otherwise).
6. Slow work (crawling, external APIs) returns `202` and runs in the worker — see
   [background-jobs.md](../architecture/background-jobs.md).
7. Do not create endpoints that return fake data to "fill" a screen.
