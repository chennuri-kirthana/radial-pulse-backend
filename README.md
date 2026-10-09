# Radial Pulse — Backend (API + worker)

Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · Pydantic 2 · PostgreSQL 16 (Aurora in AWS) · Cognito.
Owner: **Person 1 (Backend / Data)**. The frontend (web + mobile) lives in its own repo and uses
the **API contract** this repo publishes.

```
radial-pulse-backend/
├── app/                  the API and the background worker (one image)
├── alembic/              database migrations (0001 … 0012)
├── tests/                fast tests (SQLite) + integration tests (PostgreSQL, row-level security)
├── openapi/
│   ├── openapi.json      THE CONTRACT with the frontend (generated — never edit by hand)
│   └── CHANGELOG.md      what changed for the screens, per contract version
├── docs/                 architecture, database schema, API guides, AWS notes
├── scripts/db/           local database roles
├── docker-compose.yml    local PostgreSQL (+ API + worker)
└── Makefile              every command (make help)
```

## One-time: publish this repo and the first contract (Person 1)

Done on 27 Sep 2026: `uv.lock` and `openapi/openapi.json` (contract v0.1.0) are generated and
committed, and the full test suite passes on PostgreSQL. Until the GitHub release exists, the
frontend team can take `openapi/openapi.json` straight from this repo.

Still to do:

```bash
# on GitHub: create an EMPTY private repo <org>/radial-pulse-backend (no README), then
git remote add origin git@github.com:<org>/radial-pulse-backend.git
git push -u origin main
# when CI is green:
git tag v0.1.0 && git push origin v0.1.0     # → release "API contract v0.1.0"
```

What the backend needs from AWS (to share with the DevOps owner): [docs/infrastructure/backend-aws-needs.md](docs/infrastructure/backend-aws-needs.md).

## First time on your machine

```bash
# needs: Python 3.12, uv (https://docs.astral.sh/uv/), Docker
make install                 # Python packages into .venv
cp .env.example .env         # local settings (git-ignored)
make db                      # local PostgreSQL 16 in Docker
make migrate                 # build the tables
make create-admin EMAIL=you@example.com NAME="You"   # first Platform Administrator
make dev                     # http://localhost:8000/docs
make worker                  # background jobs (second terminal)
```

## Every day

```bash
make check                   # lint + format + types + fast tests + contract up to date
make integration-test        # full suite on PostgreSQL (after `make db`; set TEST_DATABASE_URL)
make migration NAME="add x"  # new migration after changing models — READ the generated file
make openapi                 # regenerate the contract after changing routes/schemas
```

## The API contract

1. Change routes or schemas → `make openapi` → bump `CONTRACT_VERSION` in
   `app/core/contract.py` → add a `## vX.Y.Z` section to `openapi/CHANGELOG.md` → pull request.
   CI fails if `openapi.json` is stale or the version was not bumped.
2. After merging: `git tag vX.Y.Z && git push origin vX.Y.Z`. GitHub Actions creates the
   release **"API contract vX.Y.Z"** with `openapi.json` attached.
3. Share the release with the frontend team. How they use it is up to them.

Rules for version numbers: [docs/api/contract-versioning.md](docs/api/contract-versioning.md).

## Layers (one direction only)

```
routers  →  services  →  repositories  →  models
   ↑            ↑
schemas     core (config, security, rbac, errors, logging)
```

| Folder | Job | Must NOT |
|---|---|---|
| `api/v1/routers` | HTTP: parse input, call one service function, shape the response | query the DB, hold business rules |
| `schemas` | Pydantic request/response models (the API contract) | import sessions |
| `services` | Business rules, audit events, commit | import FastAPI |
| `repositories` | All SQL. Clinic-scoped reads always take `clinic_id` | contain business rules |
| `models` | SQLAlchemy tables | contain request logic |
| `dependencies` | DB session, auth (`get_principal`), tenancy (`clinic_access`) | |
| `integrations` | S3, Cognito, SES, Secrets Manager, OAuth (behind small Protocols) | |
| `worker`, `jobs` | background jobs (SQS in AWS, database polling locally) | import FastAPI |

## Tenant isolation — the one rule

Every route under `/clinics/{clinic_id}/…` depends on `clinic_access(Permission.X)`:
no access → **404**, access but missing permission → **403**. PostgreSQL **row-level security**
is the second net on **every** table (`tests/integration/test_rls.py` fails if a table has none).

## More

- Architecture and decisions: [docs/architecture](docs/architecture) (start with `database-schema-simple.md`)
- All routes and who may call them: [docs/api/milestone1-api.md](docs/api/milestone1-api.md)
- Chat, connected accounts, settings: [docs/architecture/chat-connections-settings.md](docs/architecture/chat-connections-settings.md)
- What the backend needs from AWS: [docs/infrastructure/backend-aws-needs.md](docs/infrastructure/backend-aws-needs.md)
- Building the AWS Lambda ZIP: [docs/infrastructure/lambda-package.md](docs/infrastructure/lambda-package.md)
- Rules for AI coding agents: [AGENTS.md](AGENTS.md)
