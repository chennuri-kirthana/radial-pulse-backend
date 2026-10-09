# Environments and configuration

| Environment | Where        | Database                          | Auth              | Deploys                   |
| ----------- | ------------ | --------------------------------- | ----------------- | ------------------------- |
| **LOCAL**   | your machine | Docker PostgreSQL 16              | DEV Cognito pool  | —                         |
| **DEV**     | AWS (dev)    | Aurora Serverless v2 (auto-pause) | DEV Cognito pool  | set up by DevOps          |
| **PROD**    | AWS (prod)   | Aurora Serverless v2, 2 instances | PROD Cognito pool | set up by DevOps          |

DEV and PROD share **nothing**: separate VPC, database, bucket, user pool, KMS key,
secrets, logs, alarms, budget and IAM roles (ideally separate AWS accounts).

## Where each setting lives

| Kind of value                                                                           | LOCAL                          | DEV / PROD                                                   |
| --------------------------------------------------------------------------------------- | ------------------------------ | ------------------------------------------------------------ |
| API plain settings (`APP_ENV`, `COGNITO_*`, `S3_ASSETS_BUCKET`, `CORS_ALLOWED_ORIGINS`) | `.env`                         | ECS task definition env (Terraform `compute` module)         |
| App database login (`DATABASE_URL`, RLS applies)                                        | `.env`: `radial_app_local`     | IAM DB auth (`DB_IAM_AUTH=true`), no password                |
| Migration login (`MIGRATION_DATABASE_URL`, owner)                                       | `.env`: `radial` (throwaway)   | RDS-managed secret → injected **only** into the migrate task |
| Job queue (`JOB_QUEUE_BACKEND`, `JOB_QUEUE_URL`)                                        | `database` (worker polls DB)   | `sqs` + queue URL from Terraform                             |
| Third-party API keys (future)                                                           | `.env`                         | Secret `radial-pulse/<env>/api` → injected by ECS            |
| AWS credentials                                                                         | `aws sso login` (your profile) | GitHub OIDC → short-lived role session                       |

## Rules

- `.env*` files are git-ignored (except `.env.example`). The pre-commit hook and gitleaks block them.
- The API validates its settings at startup and refuses to run in `prod` with
  `DEBUG=true`, wildcard/`http://` CORS, or a database connection without TLS.
- Never hard-code an environment URL or id in code. Read it from config.
- Terraform `terraform.tfvars` per environment is committed and must never contain secrets.

## API settings reference

See `app/core/config.py` (every field is documented there) and
`.env.example`.

Frontend settings (`VITE_*`, `EXPO_PUBLIC_*`) live in the frontend repo. The API only needs the
frontend's origins in `CORS_ALLOWED_ORIGINS`.
