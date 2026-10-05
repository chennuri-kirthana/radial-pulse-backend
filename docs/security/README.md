# Security baseline

Security is part of the platform, not a later phase. This page lists what is in place,
where it lives, and the rules everyone follows.

> **Compliance:** Radial Pulse does **not** claim HIPAA or any other healthcare
> compliance. Today the platform stores business/marketing data about clinics (names,
> addresses, brand, public metrics), not patient health records. If health information
> is ever handled, formal compliance requires an additional organizational, legal,
> security and infrastructure assessment **before** that data is collected.

## In place

| Area                     | Control                                                                                                                                                                                           | Where                                                               |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Authentication           | Cognito + Google, Authorization Code + PKCE, public clients (no secrets in apps)                                                                                                                  | `infra/…/auth`, `apps/*/features/auth`                              |
| Token validation         | At API Gateway **and** in the API (RS256, issuer, expiry, `token_use=access`, client id)                                                                                                          | `app/core/security.py`                                              |
| Authorization / RBAC     | One permission table; one tenant gate; 404 for foreign clinics                                                                                                                                    | `app/core/rbac.py`, `app/dependencies/tenancy.py`                   |
| Tenant isolation         | Clinic-scoped repositories; isolation tests for every route                                                                                                                                       | `app/repositories`, `tests/api/test_tenant_isolation.py`            |
| Database isolation (RLS) | PostgreSQL row-level security on every clinic table; API/worker run as non-owner `radial_app` members; scope is transaction-local; no scope → no rows                                             | migration 0004, `app/db/tenant.py`, `tests/integration/test_rls.py` |
| Database logins          | API and worker use IAM DB auth (short-lived tokens); only the one-off migrate task gets the master secret                                                                                         | `compute` module, `app/db/session.py`                               |
| Service identity         | Worker is a `ServicePrincipal` with a fixed permission set, scoped to one clinic per job; audit rows say `actor_type=service`                                                                     | `app/core/rbac.py`, `app/worker`                                    |
| Invite-only accounts     | Unknown Google accounts get 403 `not_provisioned`                                                                                                                                                 | `app/services/identity.py`                                          |
| Audit trail              | Every state change → `audit_events` (append-only trigger; app role has no UPDATE/DELETE). Application audit ≠ infrastructure logs (CloudTrail/CloudWatch)                                         | `app/services/audit.py`, migrations 0001 + 0004                     |
| Input validation         | Pydantic models reject unknown fields; size/type limits on uploads                                                                                                                                | `app/schemas`                                                       |
| Error hygiene            | Problem+JSON; no stack traces, SQL or input echo; 500s show only a request id                                                                                                                     | `app/core/error_handlers.py`                                        |
| Safe logging             | JSON logs; tokens/passwords/URLs redacted; no query strings or bodies                                                                                                                             | `app/core/logging.py`                                               |
| Secure headers           | nosniff, frame DENY, no-referrer, CSP `default-src 'none'`, no-store, HSTS (dev/prod)                                                                                                             | `app/middleware/security_headers.py`; CloudFront policy for web     |
| CORS                     | Explicit allow-list; prod refuses `*` and `http://`                                                                                                                                               | `app/core/config.py`, `api` module                                  |
| Production safety        | Prod refuses `DEBUG=true`, non-TLS DB; docs off                                                                                                                                                   | `app/core/config.py`                                                |
| Secrets                  | Secrets Manager (+ RDS-managed rotating DB password); nothing in git/tfvars/images                                                                                                                | `database`, `secrets` modules                                       |
| Encryption               | KMS CMK (rotation on) for Aurora, S3 assets, secrets, logs, SNS, ECR; TLS everywhere on the internet side; DB `rds.force_ssl`                                                                     | `kms` module                                                        |
| Storage                  | Private buckets, public access blocked, TLS-only policy, presigned URLs (5 min), tenant-prefixed keys                                                                                             | `storage` module, `app/services/assets.py`                          |
| Network                  | DB in subnets with no internet route; API tasks accept traffic only from the internal ALB; ALB only from the VPC link                                                                             | `networking`, `compute`, `database` modules                         |
| Least-privilege IAM      | One role per task (api: S3 prefix + KMS + SQS send + own DB login; worker: SQS consume + own DB login); deploy role limited to its ECR/ECS/bucket; OIDC trust pinned to repo + GitHub environment | `compute`, `iam` modules                                            |
| No long-lived CI keys    | GitHub OIDC → STS                                                                                                                                                                                 | `.github/workflows`                                                 |
| Containers               | Non-root user, read-only root filesystem, no build tools, pinned base                                                                                                                             | `Dockerfile`                                           |
| Secret scanning          | gitleaks pre-commit + CI                                                                                                                                                                          | `lefthook.yml`, `ci.yml`                                            |
| Dependency scanning      | `pnpm audit`, `pip-audit`, Trivy (vulns + IaC/Dockerfile misconfig), Dependabot                                                                                                                   | `ci.yml`, `dependabot.yml`                                          |
| Budgets / abuse          | API Gateway throttling, AWS Budgets alerts                                                                                                                                                        | `api`, `budget` modules                                             |

## Rules for everyone (humans and AI agents)

1. Never commit secrets, `.env` files, keys, state files or real clinic/patient data.
2. Never log tokens, passwords, cookies, presigned URLs or request bodies.
3. Never trust the frontend for access decisions. The API decides.
4. Never return data for a clinic without passing `clinic_access(...)`. Never grant the app
   database role `BYPASSRLS` or table ownership.
5. Never widen CORS, IAM or security groups "to make it work" — ask Person 3.
6. Never disable TLS verification.
7. Report anything suspicious in the team channel with the request id, not the data.

## Known gaps (tracked in [../architecture/decisions.md](../architecture/decisions.md))

- No HTTP service-to-service identity yet (Cognito client credentials) — only the worker
  exists as a machine identity today.
- Identity tables (`users`, `clinic_memberships`, `clinic_assignments`, `organizations`,
  `notifications`) are not under RLS; they are protected by the application layer only.
- Evidence excerpts from crawled pages are stored as text; engines must not store personal data.
- No WAF (HTTP APIs don't support it directly), GuardDuty or Security Hub yet.
- ALB ↔ task hop inside the VPC is plain HTTP.
- GitHub Actions are pinned to major versions; pin to commit SHAs before PROD go-live.
