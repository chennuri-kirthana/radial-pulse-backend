# Testing

| Layer                     | Tool                                   | Where                                              | Runs in                                                           |
| ------------------------- | -------------------------------------- | -------------------------------------------------- | ----------------------------------------------------------------- |
| Backend unit              | pytest                                 | `tests/unit`                          | `make test`                                                     |
| API (HTTP → service → DB) | pytest + FastAPI TestClient            | `tests/api`                           | `make test` (SQLite) and `make integration-test` (PostgreSQL) |
| Database / migrations     | pytest + Alembic on PostgreSQL         | `tests/integration`                   | `make integration-test`, CI                                     |
| Tenant isolation          | pytest                                 | `tests/api/test_tenant_isolation.py`  | both                                                              |
| Row-level security        | pytest as the real non-owner app role  | `tests/integration/test_rls.py`       | `make integration-test`, CI                                     |
| Worker / assessments      | pytest, in-memory queue, fake engines  | `tests/api/test_assessments.py`                    | both                                                              |
| Chat / connections / settings | pytest, fake OAuth + secret store  | `tests/api/test_chat.py`, `test_connections.py`, `test_settings.py` | both                                          |
| Contract                  | `make contract-check` + oasdiff         | `openapi/openapi.json`                             | `make check`, CI `contract` job                                   |

## Principles

- **No fake auth.** Tests sign real JWTs with a test RSA key; the production verifier checks them.
- **No real third-party accounts.** S3 and Cognito userInfo are replaced through FastAPI
  dependency overrides with small in-memory doubles (`tests/conftest.py`). Google, Meta,
  etc. token exchanges use `FakeOAuthClient`, and AWS Secrets Manager `InMemorySecretStore` —
  never live calls in CI.
- **PostgreSQL is the truth.** SQLite is only the fast local path; CI runs the full suite
  on PostgreSQL 16, with the schema built by the real Alembic migrations.
- **Every new clinic-scoped route** gets a line in `test_tenant_isolation.py`.
- Test data comes from `tests/factories.py` — never from production.
- On PostgreSQL the app under test connects as a member of `radial_app`, so RLS is really
  enforced; test setup (`db` fixture) uses the owner connection.
- **Risk-based**: the heaviest tests sit where a bug is most expensive — tenant isolation,
  RLS, permissions, migrations of stored data, job retries/idempotency, evidence rules.
  Simple CRUD gets one happy path and one access test.
