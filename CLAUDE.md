# CLAUDE.md

**Read [AGENTS.md](AGENTS.md) first — it is the single source of truth for AI agents in this
repo.** This file only adds Claude-specific notes and must never contradict AGENTS.md.

- Use `make <target>` (see `make help`); Python runs through `uv run`.
- When a task needs a decision listed as open in `docs/architecture/decisions.md`, stop and ask.
- Plan changes that touch migrations + API contract before editing: list the files first.
- Plain English in docs and messages: the team prefers simple words and short sentences.

---

<!-- Added from the database integration pack (schema v15), 8 Oct 2026. -->

# Radial Pulse: Central backend

Radial Pulse helps clinics improve their digital presence. This repo is the **Central backend**: users, roles,
clinics, practitioners, photos/voice, reports, work items, chat, connected accounts. Ignore any older "Phase 0" code.
If this repo already has backend code, connect it to the database with `prompts/DB-INTEGRATION-PROMPTS.md`.
The frontend is in `frontend/` (read-only for you unless asked).

## Source of truth (in this order; never contradict a higher one)
1. `db/schema-v15.sql`: the database. **Final and tested. Do not change it without asking me.**
   `docs/00-terminology.md`: the official names (from `docs/Project_Entity_Terminology_Mapping.pdf`) and the
   **same-name-in-every-layer** convention (table → model → schema → router → API path → UI text). Follow it exactly.
2. `docs/01-decisions.md`: product decisions already made.
3. `docs/02-access-rules.md`: who can see / change what (also enforced in the database).
4. `docs/03-backend-rules.md`: how the API must use the database (must-follow rules).
5. Other teams read Central data through **`/api/v1/internal/*` routes in this backend** (changed 8 Oct:
   no separate MCP server). These routes are **read only**: callers sign with their own **AWS IAM role** (SigV4; changed 9 Oct,
   no Cognito service tokens), never a user token, and the backend runs
   each request with `SET LOCAL ROLE radial_service` (the database's read-only role for other backends).
6. `frontend/`: what screens need. If a screen needs data that is NOT in the schema, **stop and ask me**.
7. `docs/old-contracts-OUTDATED/`: old API contracts. **Outdated names and removed features.** Use only for
   response shapes and error format; never copy names from them. See `docs/06-what-changed-since-old-contracts.md`.

## Stack
- Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, psycopg 3, Alembic, pytest
- PostgreSQL 16 (AWS Aurora PostgreSQL in the cloud), Amazon Cognito (email + password), Amazon S3 (private bucket)
- API Gateway (HTTP API): `/api/*` → user-token authorizer (Cognito)
- API Gateway (separate REST API, `AWS_IAM` + resource policy): `/api/v1/internal/*` → other teams' IAM roles
- Region ap-south-1 (Mumbai)

## Hard rules (never break these)
1. **Never edit `db/schema-v15.sql` or invent tables/columns.** If something seems missing, ask me first.
2. **Use the exact names** from `docs/00-terminology.md` in every layer. Never `doctor`, `chat`, `organizations`,
   `work_items`, `owner`, `clinic_user`, `seo_report_id`, `assessments` (old names). Its grep check must find nothing.
3. **The first Alembic migration runs `db/schema-v15.sql` as-is** (`op.execute`). Do NOT autogenerate it:
   autogenerate doesn't know triggers, functions, policies or roles and would silently drop them.
   Later migrations are written by hand and reviewed.
4. **Two database logins:** a migration/owner login (owns tables) and an **app login that does NOT own tables**
   and is a member of role `radial_app`. The table owner skips all access rules, so the app must never use it.
5. **Every request = one transaction that starts with**
   `SET LOCAL ROLE radial_app;` and `SET LOCAL rp.user_id = '<users.id>';`
   Only `SET LOCAL` (never plain `SET`): pooled connections must not keep another user's id.
   Background jobs use `SET LOCAL rp.actor = 'system'` instead of a user id.
6. **Login:** verify the Cognito **access** token (signature, issuer, expiry, `token_use=access`, client id), then call
   `SELECT * FROM rp_user_for_login(sub, email)`. No row or `is_active = false` → 403 `account_disabled`.
   There are no `/login`, `/logout`, `/register` endpoints (the app talks to Cognito directly).
7. **Never write to `clinic_stage_changes`.** To move a stage: `SET LOCAL rp.stage_note = '…'` then
   `UPDATE clinics SET stage = …`. A trigger writes the history.
8. **`audit_events` is insert-only.** Write one row in the SAME transaction as each change (who, action, resource).
9. **Don't set `updated_at` yourself**: a trigger does it.
10. **Never store tokens or secrets in the database.** OAuth tokens go to AWS Secrets Manager; only `secret_ref` is stored.
11. **Files:** only S3 keys are stored. Uploads use presigned URLs; no download endpoint, only short-lived view links,
    and every view is audited. Keys must start with `clinics/<clinic_id>/photos/`, `/voice/`, or `users/<id>/`.
12. **Never log** tokens, secrets, passwords or presigned URLs.
13. Don't hide data by filtering in Python only: the database rules already hide rows; the API also checks roles
    (defense in depth). A clinic the caller can't see → **404**, a forbidden action → **403**.
14. **Years of experience is never stored**: compute it as current year − `practitioners.practice_start_year`.
    `consultation_hours` has ONE shape (see `docs/01-decisions.md` §14); validate it in the API too.

## Error mapping (database error → API response)
| Database error | HTTP | `code` |
|---|---|---|
| row not visible / not found | 404 | `not_found` |
| `insufficient_privilege` (42501), RLS "violates row-level security policy" | 403 | `forbidden` |
| `unique_violation` (23505) | 409 | `state_conflict` (voice title: message "This title is already used. Please give another title.") |
| `check_violation` (23514) from triggers (last admin, assignee, role) | 409 | `state_conflict` with the trigger's message |
| `check_violation` from the v15 input triggers ("… cannot be in the future", "… is not a known time zone") | 400 | `invalid_request` with `fields` |
| `check_violation` from CHECK rules / `not_null_violation` | 400 | `invalid_request` with `fields` |
| `foreign_key_violation` (23503) | 409 | `state_conflict` |
Error body = RFC 9457 Problem JSON: `type, title, status, code, detail, request_id` (+ `fields` for 400).
Every response has header `X-Request-Id`.

## How to work (always)
- **Plan first.** For any task bigger than one file, write a short plan and wait for my OK.
- Work in **small steps** (one area at a time, see `prompts/KICKOFF-PROMPTS.md`). After each step: run tests, show
  results, commit with a clear message.
- **Tests are required:** pytest against a **real PostgreSQL 16** (docker), never SQLite. Every endpoint gets tests
  for: allowed role ✅, forbidden role (403), other clinic (404), bad input (400).
- Convert `db/tests/*.sql` into pytest tests early. They must keep passing.
- If anything is unclear or two sources disagree: **stop and ask me**. Don't guess, don't "improve" decisions.
- At the end of each step, list anything you assumed.

## Commands (fill in as the project grows)
- Start DB: `docker compose up -d postgres`
- Migrate: `alembic upgrade head`
- Tests: `pytest -q`
- Lint/types: `ruff check . && ruff format --check . && mypy .`
- Run API: `uvicorn app.main:app --reload`

## Glossary (use these words in code, API and UI)
| Term | Meaning | In the schema |
|---|---|---|
| Platform Administrator | internal admin | `users.platform_role = 'platform_administrator'` |
| Digital Success Manager (DSM) | manages allocated clients | `'digital_success_manager'` + `portfolio_allocations` |
| Client Organization | the business (e.g. Shah Healthcare Pvt Ltd) | `client_organizations` |
| Clinic | one branch of a Client Organization (the tenant) | `clinics` |
| Clinic Administrator / Clinic Team Member | clinic-side people | `clinic_members.role`; login `platform_role = 'clinic_member'` |
| Practitioner | doctor or other professional (shared across businesses) | `practitioners` + `clinic_practitioners` |
| Portfolio Allocation / My Client Portfolio | a Client Organization given to one DSM | `portfolio_allocations` (one active per org) |
| Prospective Client → Client Activation | clinic stages | `clinics.stage` (5 values) |
| Digital Presence Intelligence Agent | finds the clinic online | stage `presence_discovered`, `clinic_online_profiles` |
| Digital Growth Team | the SEO team (separate backend) | `digital_growth_report_id` |
| Digital Presence Assessment | a report | `digital_presence_assessments` |
| Improvement Opportunity / Work Item | a problem found / a task to fix it | `opportunity_code` / `improvement_work_items` |
| Client Collaboration | chat between clinic and DSM | `collaboration_messages` |
