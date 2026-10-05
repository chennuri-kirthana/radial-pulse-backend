# AGENTS.md — rules for AI coding agents (backend repo)

The **single source of truth** for AI agents (Claude Code, Codex, Cursor, Copilot, …) in this
repo. `CLAUDE.md` points here; if anything disagrees, **this file wins**.

Radial Pulse is a multi-clinic platform. The two things you must never get wrong:
**tenant isolation** (one clinic never sees another's data) and **secrets** (never in git,
never in the database for third-party tokens, never in logs).

## 1. Before you write code

1. Read `README.md` and the doc for the area you touch (`docs/architecture/*`).
2. Look for existing code first (`app/core`, services, repositories). Reuse; do not duplicate.
3. If a rule is not written down in `docs/`, **ask** — do not invent domain rules (scoring,
   workflows of other teams, pricing). Decisions are listed in `docs/architecture/decisions.md`.

## 2. Backend rules

- Layers: `routers → services → repositories → models`. **No SQL in routers. No FastAPI in services.**
- Every route under `/clinics/{clinic_id}/…` **must** depend on `clinic_access(Permission.X)`.
  No access → 404, missing permission → 403. Do not invent another access check.
- Repository methods for clinic data **must** take `clinic_id` and filter on it.
  Never write `session.get(Model, id)` for clinic-scoped data.
- Any id from the client that points at another row (asset, owner, approval…) must be checked
  to belong to the same clinic.
- Every state change calls `app.services.audit.record(...)` in the same transaction. Never put
  message text, tokens or file contents in audit details.
- In-app notifications go through `app.services.notify.send` (it respects the person's switches).
- Raise `app.core.errors.*` (never `HTTPException`) from services.
- New permission? Add it to `Permission` in `app/core/rbac.py`, the role tables, the unit test,
  and the permission table in `docs/api/milestone1-api.md`.
- **Add every new clinic route to `tests/api/test_tenant_isolation.py`.**
- **Role words**: Platform Administrator, Digital Success Manager, Clinic Administrator,
  Clinic Team Member. A doctor is **not** a role.
- **One Digital Presence Assessment.** Never add per-channel report types or endpoints.
- **Slow work goes to the worker** (`app/worker`, `JobType`). Job messages carry ids only.
- **Third-party tokens** (connected accounts) live only in AWS Secrets Manager via
  `app.integrations.secrets.SecretStore`. The database stores the secret's ARN, nothing more.

## 3. Database & migrations

- Change models → `make migration NAME="…"` → **read and fix** the generated file.
- Migrations must work with the currently running app version (expand → migrate → contract).
- Never edit a migration that is already on `main`. Add a new one.
- No PostgreSQL ENUM types (VARCHAR + CHECK via `str_enum`).
- **Keys:** every table has an `id` primary key; "these columns never repeat" = a composite unique
  key; a link to a parent of the SAME clinic = a composite foreign key on (parent id, clinic_id).
- **Indexes and data rules (0012):** every foreign key needs an index that STARTS with it (partial
  `WHERE col IS NOT NULL` when most rows have none; links to `users` are the exception). Never add a
  one-column index that a bigger index or unique key already starts with. Ranges and "done ⇔ date"
  rules are CHECK constraints in the migration AND the model (PostgreSQL-only syntax:
  `.ddl_if(dialect="postgresql")`). `tests/unit/test_schema_review.py` enforces the index rules.
  See `docs/architecture/database-relationships.md`.
- **Every new table needs row-level security in the same migration.** Clinic tables: the
  `rp_all_clinics() OR clinic_id = ANY (rp_clinic_ids())` rule. Per-person tables: also
  `user_id = rp_user_id()`. `tests/integration/test_rls.py` fails otherwise.
- The API and worker run as `radial_app` members (RLS applies). Never grant `BYPASSRLS` or ownership.
- Changing stored values = a data migration with a mapping and a downgrade.

## 4. API contract

- This repo is the source of truth. After changing schemas/routes: `make openapi`, bump
  `CONTRACT_VERSION` (`app/core/contract.py`), add a `## vX.Y.Z` section to `openapi/CHANGELOG.md`.
- Never hand-edit `openapi/openapi.json`.
- Breaking change (removing/renaming a field or route, new required input) = bump the MINOR
  number while we are 0.x, and tell the frontend in the changelog.

## 5. Security rules

- Never commit secrets, `.env`, keys, real clinic/patient data. Use `.env.example`.
- Never log tokens, passwords, presigned URLs, OAuth codes or request bodies.
- Never disable TLS verification, auth, or the tenant gate — not even in tests.
- Never claim HIPAA or any compliance in code, docs or messages.

## 6. After you change something — run the checks

```bash
make check               # always
make integration-test    # if you touched models, migrations or SQL (needs `make db`)
make openapi             # if you changed the API
```

Report what you ran and the result. **Never claim a check passed without running it.**

## 7. Commits & PRs

- Branch: `feature/…`, `fix/…`, `chore/…`, `docs/…`.
- Commit: Conventional Commits `type(scope): summary` (scopes: `api`, `db`, `contract`, `ci`, `docs`).
- Fill in the PR checklist honestly.
