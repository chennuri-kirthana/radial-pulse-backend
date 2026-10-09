# DEV deployment plan: API on Lambda

Status: **PROPOSAL. Nothing is deployed.** Written 2026-10-07 after a read-only look at the repo
and at the AWS account the local CLI points to.

Scope: DEV only. The synchronous API runs on Lambda behind an API Gateway HTTP API with a
Cognito JWT authorizer. No ECS, Fargate, ALB, VPC Link, SQS or worker.

This plan changes three earlier scaffolding choices in `docs/architecture/decisions.md`
(ECS Fargate + ALB + VPC link, one SQS queue + worker). Record the change there once it is agreed.

---

## 0. Blockers — must be fixed before any apply

| # | Blocker | What we found | Who fixes it |
|---|---|---|---|
| B1 | **Wrong AWS account** | The local CLI uses an IAM user in an account that has no Cognito pool, no CloudFront distribution, no Central roles, no KMS keys and only the default VPC. The Cognito domain `rp-central-rp-dev` is not in that account. | Platform team: give us the Central DEV account and a role to assume |
| B2 | **Long-lived access key** | The CLI signs in with an IAM user access key, and that user is in a group with `AdministratorAccess`. This breaks the "no long-lived keys" rule. | Use IAM Identity Center / assumed role for the DEV deploy. Do not use this key. |
| B3 | ~~User pool ID not found~~ **Resolved 10 Oct** | The ID was misspelled here (`…0Blss6OwM`, lower-case `s`). The console shows `ap-south-1_0BlsS6OwM` (upper-case `S`). Its public discovery document answers, with issuer `https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_0BlsS6OwM` and the `rp-central-rp-dev` Managed Login domain. | Done |
| B4 | **Web origin does not resolve** | `d8411y8p4kdlc.cloudfront.net` still has no DNS record (checked 10 Oct). | Confirm the CloudFront domain |
| B5 | ~~Web client ID missing~~ **Resolved 10 Oct** | Console: `rp-central-web-dev` = `4ic2pjdot2du6bh5srjma0n9cm` (public, no secret). Read from the console, not checked through the AWS API. | Done |
| B6 | ~~No IaC in this repo~~ **Fixed for the database:** CloudFormation, `infra/cloudformation/central-db-dev.yaml`. Network, Lambda, API Gateway and S3 still to do. | | Section 16 |
| B7 | **Open decisions** | #6 (separate dev/prod accounts), #13 (custom domains), #20 (who owns deploy workflows). | Team decision |

Everything below assumes B1–B7 are fixed. Values shown as `<…>` are filled in from variables.

---

## 1. Architecture

```
Browser (https://d8411y8p4kdlc.cloudfront.net)
   |  Bearer access token from Cognito Managed Login
   v
API Gateway HTTP API  rp-central-api-dev   ($default stage, CORS for the web origin only)
   |  GET /health, GET /ready            -> no authorizer
   |  ANY /api/v1/{proxy+}               -> JWT authorizer rp-central-users-dev
   |                                        issuer  https://cognito-idp.ap-south-1.amazonaws.com/<pool id>
   |                                        audience <web client id>  (+ mobile client id later)
   v
Lambda rp-central-api-dev  (container image, Lambda Web Adapter -> uvicorn -> FastAPI)
   |  in VPC rp-central-vpc-dev, private app subnets, SG rp-central-api-lambda-sg-dev
   +--> Aurora PostgreSQL rp-central-db-dev     (private DB subnets, IAM DB auth, KMS)
   +--> S3 rp-central-assets-dev                 (via S3 gateway endpoint; presigned URLs)
   +--> Secrets Manager radial-pulse/dev/connections/*   (connected-account tokens)
   +--> Cognito admin API + /oauth2/userInfo + JWKS     (via NAT)
   +--> OAuth providers (Google, Meta, LinkedIn, X)      (via NAT; not set up yet)
   KMS key alias/rp-central-dev encrypts DB, DB master secret, S3, connection secrets, logs
```

The app checks the token again itself (`app/core/security.py`): RS256, `token_use=access`,
`client_id` in the allow list. The gateway check is a first gate, not the only one.

---

## 2. Backend changes needed for Lambda

The app is close to Lambda-ready. Routes are sync, there is no startup work, no background
threads, no file writes, and every heavy client is created lazily and reused.

**Recommended adapter: AWS Lambda Web Adapter (LWA) in the existing Dockerfile.**
Why: the repo already ships a tested Docker image that runs uvicorn. LWA runs that same image on
Lambda with **no Python code change**. Mangum would need a new handler module, a new dependency,
and a zip build of native wheels (psycopg, cryptography, pydantic-core) for Linux from Windows.

| Change | File | Size |
|---|---|---|
| Add a `lambda` build stage: copy the LWA extension into `/opt/extensions/`, set `AWS_LWA_PORT=8000`, `AWS_LWA_READINESS_CHECK_PATH=/health`. Default stage stays as it is. | `Dockerfile` | ~6 lines |
| Add a `docker-build-lambda` target | `Makefile` | 2 lines |
| Record the Lambda / no-SQS choice | `docs/architecture/decisions.md` | doc |

Settings only (no code):

| Need | Setting |
|---|---|
| Small DB pool per Lambda instance (one request at a time per instance) | `DB_POOL_SIZE=1`, `DB_MAX_OVERFLOW=0` |
| DB credentials without a password in Lambda | `DB_IAM_AUTH=true`, `DB_USER=radial_api_iam` (already supported in `app/db/session.py`) |
| Clean failure for job routes | `JOB_QUEUE_BACKEND=memory` (see section 9) |

Not needed now: RDS Proxy. Cap Lambda reserved concurrency at 10 instead, so the API can open
at most 10 DB connections.

---

## 3. Endpoints that do not work without SQS / a worker

| Endpoint | With `JOB_QUEUE_BACKEND=memory` | Note |
|---|---|---|
| `POST /api/v1/clinics/{clinic_id}/assessments` | **503** "Background jobs are not configured". No row is written. | The only route that queues work. With the default `database` backend it would return 202 and the job would stay `queued` forever, so we do not use that. No assessment engines are registered yet anyway. |
| Reads of assessments (`GET …/assessments`, `GET /assessments`) | Work | Show existing rows only. |

Other things that will not work in this phase (not SQS-related):

| Feature | Why | Effect |
|---|---|---|
| `/api/v1/internal/*` (AWS IAM, D33) | The separate internal REST API (`AWS_IAM` + resource policy) is not created yet; `INTERNAL_*` settings are empty. | 503 from the backend (401 at the HTTP API's JWT authorizer for service callers). |
| `POST …/connections/{platform}/complete` | No OAuth apps or redirect URIs configured. | Fails with a config error. |
| Scheduled `archive-old-data`, `cleanup-stale-uploads` | Were planned as ECS RunTask + EventBridge. | Not scheduled. Run by hand if needed. |

---

## 4. AWS resources to create (all in ap-south-1, all tagged)

Required tags on every resource that supports tags:
`Project=RadialPulse`, `Team=Central`, `Environment=dev`. Applied through the IaC provider's
default tags so nothing is missed.

| Resource | Name | Notes |
|---|---|---|
| VPC | `rp-central-vpc-dev` | Only if no Central DEV VPC exists in the real account. Two AZs. |
| Subnets ×6 | `rp-central-public-{a,b}-dev`, `rp-central-app-{a,b}-dev`, `rp-central-db-{a,b}-dev` | Public subnets hold the NAT only. |
| Internet gateway | `rp-central-igw-dev` | For the NAT. |
| NAT gateway + EIP | `rp-central-nat-dev` | One NAT for DEV (decisions.md: single NAT in dev). Needed for Cognito userInfo, JWKS, Cognito admin API and OAuth providers. |
| Route tables | `rp-central-rt-{public,app,db}-dev` | DB route table has no internet route. |
| S3 gateway endpoint | `rp-central-s3-vpce-dev` | Free. Keeps S3 traffic off the NAT. |
| Security groups | `rp-central-api-lambda-sg-dev`, `rp-central-db-sg-dev` | See section 7. |
| KMS key + alias | `alias/rp-central-dev` | Only if no approved Central KMS key exists. Rotation on. |
| DB subnet group | `rp-central-db-subnets-dev` | DB subnets only. |
| Aurora PostgreSQL cluster + 1 instance | `rp-central-db-dev` | See section 11. |
| DB master secret | managed by RDS (`ManageMasterUserPassword`) | Encrypted with the KMS key. Used only for migrations. |
| S3 bucket | `rp-central-assets-dev` (add `-<suffix>` if the name is taken) | See section 12. |
| ECR repository | `rp-central-api-dev` | Scan on push, immutable tags, keep last 10 images. |
| Lambda function | `rp-central-api-dev` | See section 8. |
| Lambda execution role | `rp-central-api-lambda-role-dev` | Only if no Central execution role exists. See section 6. |
| HTTP API + stage + authorizer + routes | `rp-central-api-dev`, authorizer `rp-central-users-dev` | See section 9. |
| Log groups | `/aws/lambda/rp-central-api-dev`, `/aws/apigateway/rp-central-api-dev` | 14-day retention, KMS. |
| IaC state bucket | `rp-central-tfstate-dev` | Only if we use Terraform and no Central state bucket exists. |

Not created: SQS, worker, ECS, ALB, VPC Link, RDS Proxy, CloudFront, Route 53, ACM, Cognito
resources, IAM users, access keys, anything named or tagged `prod`.

## 5. Existing resources to reuse

| Resource | Value |
|---|---|
| Cognito user pool | `<pool id>` (B3) |
| Web app client | `rp-central-web-dev`, ID `<web client id>` (B5) |
| Managed Login domain | `https://rp-central-rp-dev.auth.ap-south-1.amazoncognito.com` |
| Web origin (CloudFront) | `https://d8411y8p4kdlc.cloudfront.net` (B4) |
| Central VPC / subnets / NAT / KMS / execution roles | Use them if the real DEV account has them. The inspected account had none. |

---

## 6. IAM

No IAM users, no access keys, no admin roles, no `*` resources except where AWS requires it.

**Lambda execution role** `rp-central-api-lambda-role-dev` (or the approved Central role).
Trust: `lambda.amazonaws.com`, with `aws:SourceAccount` condition.

| Statement | Actions | Resource |
|---|---|---|
| Logs | `logs:CreateLogStream`, `logs:PutLogEvents` | the Lambda log group |
| VPC | AWS managed `AWSLambdaVPCAccessExecutionRole` (ENI create/describe/delete; AWS requires `*`) | `*` |
| DB login | `rds-db:connect` | `arn:aws:rds-db:ap-south-1:<acct>:dbuser:<cluster resource id>/radial_api_iam` |
| Assets | `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` | `rp-central-assets-dev/clinics/*`, `…/users/*` |
| Assets list (so HEAD returns 404, not 403) | `s3:ListBucket` with `s3:prefix` in `clinics/`, `users/` | the bucket |
| Connection secrets | `secretsmanager:CreateSecret`, `PutSecretValue`, `RestoreSecret`, `DeleteSecret`, `TagResource` | `arn:aws:secretsmanager:ap-south-1:<acct>:secret:radial-pulse/dev/connections/*` |
| KMS | `kms:GenerateDataKey`, `kms:Encrypt`, `kms:Decrypt` with `kms:ViaService` = s3 / secretsmanager | the KMS key |
| Cognito invites | `cognito-idp:AdminCreateUser`, `AdminGetUser`, `AdminDisableUser`, `AdminEnableUser`, `AdminUserGlobalSignOut` | the user pool ARN |

The Cognito admin calls only work if the Lambda is in **the same account as the user pool**.
The code has no cross-account role switch.

**Deploy role:** the person or pipeline that applies the IaC uses an approved Central deploy role
(assumed, short-lived). We do not create one.

**Migration runner:** a person with an approved role that can read the DB master secret.

---

## 7. Security groups

| SG | Direction | Rule | Why |
|---|---|---|---|
| `rp-central-api-lambda-sg-dev` | Inbound | none | Lambda takes no inbound traffic. |
| | Outbound | TCP 5432 to `rp-central-db-sg-dev` | Database |
| | Outbound | TCP 443 to `0.0.0.0/0` | AWS APIs, Cognito, OAuth providers (through the NAT / S3 endpoint) |
| `rp-central-db-sg-dev` | Inbound | TCP 5432 from `rp-central-api-lambda-sg-dev` | API only |
| | Inbound | TCP 5432 from `rp-central-migrate-sg-dev` (only while migrating) | Migration runner (section 15) |
| | Outbound | none | |

No rule allows the internet into the database.

---

## 8. Lambda configuration

| Setting | Value | Why |
|---|---|---|
| Name | `rp-central-api-dev` | |
| Package | Container image from `rp-central-api-dev` ECR, `lambda` stage of the Dockerfile | Reuses the tested image |
| Architecture | x86_64 | Build machine is x86; switch to arm64 later if wanted |
| Memory | 1024 MB | FastAPI + pydantic + boto3 + psycopg; faster cold start |
| Timeout | 29 s | HTTP API stops waiting at 30 s. Slowest calls are outbound HTTP with 5–10 s timeouts. |
| Reserved concurrency | 10 | Caps DB connections at 10 |
| Ephemeral storage | 512 MB | Nothing writes to disk |
| VPC | app subnets a/b, SG `rp-central-api-lambda-sg-dev` | |
| Logs | `/aws/lambda/rp-central-api-dev`, 14 days, app already writes JSON lines | |
| Env var encryption | KMS key `alias/rp-central-dev` | No secrets in env anyway |

### Environment variables

| Name | DEV value | Secret? |
|---|---|---|
| `APP_ENV` | `dev` | no |
| `LOG_LEVEL` | `INFO` | no |
| `DEBUG` | `false` | no |
| `DOCS_ENABLED` | `false` (docs routes are behind the authorizer) | no |
| `SERVICE_VERSION` | git SHA of the image | no |
| `CORS_ALLOWED_ORIGINS` | `https://d8411y8p4kdlc.cloudfront.net` (the gateway answers CORS; this keeps local and Lambda the same) | no |
| `COGNITO_REGION` | `ap-south-1` | no |
| `COGNITO_USER_POOL_ID` | `<pool id>` | no |
| `COGNITO_APP_CLIENT_IDS` | `<web client id>` (add mobile later) | no |
| `COGNITO_DOMAIN` | `https://rp-central-rp-dev.auth.ap-south-1.amazoncognito.com` (full URL; code appends `/oauth2/userInfo`) | no |
| `IDENTITY_DIRECTORY_BACKEND` | `cognito` (so invites create real Cognito users) | no |
| `DB_IAM_AUTH` | `true` | no |
| `DB_HOST` | cluster writer endpoint | no |
| `DB_PORT` | `5432` | no |
| `DB_NAME` | `radial_pulse` | no |
| `DB_USER` | `radial_api_iam` | no |
| `DB_SSLMODE` | `require` | no |
| `DB_POOL_SIZE` | `1` | no |
| `DB_MAX_OVERFLOW` | `0` | no |
| `DB_POOL_RECYCLE_SECONDS` | `600` | no |
| `JOB_QUEUE_BACKEND` | `memory` | no |
| `S3_ASSETS_BUCKET` | `rp-central-assets-dev` | no |
| `S3_PRESIGN_TTL_SECONDS` | `300` | no |
| `CONNECTION_SECRETS_PREFIX` | `radial-pulse` | no |
| `CONNECTION_SECRETS_KMS_KEY_ID` | KMS key ARN | no |
| `AWS_LWA_PORT` / `AWS_LWA_READINESS_CHECK_PATH` | `8000` / `/health` (set in the image) | no |

`AWS_REGION` is set by Lambda itself. Left empty on purpose: `DATABASE_URL`, `DB_PASSWORD`,
`MIGRATION_DATABASE_URL`, `INTERNAL_SERVICE_ROLES`, `INTERNAL_API_ID`, `INTERNAL_TRUST_LAMBDA_CONTEXT` (until §3 of manual-aws-setup.md is done),
`OAUTH_REDIRECT_URIS`, all OAuth client IDs and secrets, `ARCHIVE_BUCKET`.

### Which values are secrets

| Secret | Where it lives |
|---|---|
| DB master password | RDS-managed secret in Secrets Manager. Only the migration runner reads it. Never in Lambda. |
| API DB login | None. IAM token, made fresh for each new connection, valid 15 minutes. |
| Connected-account tokens | Created at runtime under `radial-pulse/dev/connections/*`. DB stores the ARN only. |
| OAuth app client secrets | Not set up yet. Today the app reads them only from env vars. Before we add them, change the app to read them from Secrets Manager (follow-up). |

---

## 9. API Gateway configuration

HTTP API (no REST-only feature is needed: no API keys, usage plans or request validation).

| Setting | Value |
|---|---|
| Name | `rp-central-api-dev` |
| Stage | `$default`, auto-deploy |
| Integration | Lambda proxy, payload format 2.0, timeout 29 s |
| Authorizer | `rp-central-users-dev`, type JWT, identity source `$request.header.Authorization` |
| Issuer | `https://cognito-idp.ap-south-1.amazonaws.com/<pool id>` |
| Audience | `<web client id>`. Cognito access tokens have no `aud`, so the gateway matches `client_id`. Add the mobile client ID here later. |
| Routes | `GET /health` (no auth), `GET /ready` (no auth), `ANY /api/v1/{proxy+}` (JWT) |
| Later | `ANY /api/v1/internal/{proxy+}` with a second authorizer whose audience is the service client IDs |
| CORS origins | `https://d8411y8p4kdlc.cloudfront.net` only |
| CORS methods | `GET, POST, PUT, PATCH, DELETE` (preflight `OPTIONS` is answered by the gateway, no auth) |
| CORS headers | `authorization, content-type, x-request-id, x-clinic-id` (the app's list; confirm with the frontend) |
| CORS expose / max age / credentials | `x-request-id` / 600 / false |
| Throttling | default route: 50 burst, 20 per second |
| Access log | `/aws/apigateway/rp-central-api-dev`, 14 days. Fields: requestId, ip, requestTime, routeKey, status, responseLength, integrationLatency, integrationErrorMessage, authorizer error. **No headers, no query string, no body.** |
| Custom domain | None. Open decision #13. No Route 53 zone or ACM certificate exists in the inspected account. |

**Base URL:** `https://<api id>.execute-api.ap-south-1.amazonaws.com` (API routes at
`/api/v1/...`). The real ID is known only after apply.

---

## 10. Cognito configuration (existing, not changed)

| Item | Value |
|---|---|
| Pool | `<pool id>`, ap-south-1 |
| Web client | `rp-central-web-dev`, public, code grant, scopes `openid email`, revocation on |
| Callback / sign-out | `https://d8411y8p4kdlc.cloudfront.net` / `…/sign-in` |
| What the API needs | **access tokens** (ID tokens are rejected by the app). `openid email` is enough: on first sign-in the API calls `/oauth2/userInfo` for `email` and `email_verified`. Without the `profile` scope, the person's name is not copied from Cognito. That is fine. |
| Mobile client | Not required. Later: add its ID to the authorizer audience and `COGNITO_APP_CLIENT_IDS`. |

---

## 11. Database configuration

The local setup and CI use PostgreSQL 16. `decisions.md` chose Aurora Serverless v2 with
scale-to-zero for dev, so this plan follows that.

| Setting | Value |
|---|---|
| Engine | Aurora PostgreSQL 16 (latest 16.x minor) |
| Cluster / instance | `rp-central-db-dev` / `rp-central-db-dev-1`, class `db.serverless` |
| Capacity | min 0 ACU (auto-pause after 30 min idle), max 2 ACU |
| Database name | `radial_pulse` |
| Master user | `radial`, password managed by RDS in Secrets Manager |
| IAM DB auth | on |
| Encryption | on, KMS `alias/rp-central-dev` |
| Public access | **off** |
| Subnets | `rp-central-db-subnets-dev` (no internet route) |
| SG | `rp-central-db-sg-dev` |
| TLS | `rds.force_ssl=1` in a cluster parameter group `rp-central-db-params-dev` |
| Backups | 7 days, automated |
| Deletion protection | on; final snapshot on delete |
| Multi-AZ | no (one instance, DEV) |
| Logs | none exported at first; turn on `postgresql` export only if needed, with statement logging off |

After resume from 0 ACU the first request can take ~15 s. `/ready` may return 503 once.

**Roles:** the v15 baseline migration makes `radial_app` and `radial_service` (no login). It does
**not** make `radial_api_iam`. Create it once, after the migration, with
`infra/sql/create-app-login.sql` (IAM login, member of `radial_app`, owns no tables). The API logs
in as `radial_api_iam`, so row-level security applies. The API must never log in as the master user.
Step by step: `docs/infrastructure/central-dev-db-setup.md`.

---

## 12. S3 configuration

| Setting | Value |
|---|---|
| Bucket | `rp-central-assets-dev` |
| Block public access | all four on |
| Object ownership | bucket owner enforced (no ACLs) |
| Encryption | SSE-KMS with `alias/rp-central-dev`, bucket key on |
| Bucket policy | deny non-TLS; deny `PutObject` without KMS encryption |
| Versioning | on |
| Lifecycle | abort incomplete multipart uploads after 1 day; expire old versions after 30 days |
| CORS | origin `https://d8411y8p4kdlc.cloudfront.net`, methods `PUT, GET, HEAD`, headers `content-type, content-length`, expose `etag`, max age 600 (browsers upload with presigned PUT) |
| Prefixes used | `clinics/{clinic_id}/…`, `users/{user_id}/avatar/…` |

No archive bucket in this phase.

## 13. Secrets Manager configuration

| Secret | Created by | KMS |
|---|---|---|
| DB master secret | RDS (managed) | `alias/rp-central-dev` |
| `radial-pulse/dev/connections/{clinic_id}/{platform}` | The API at runtime | `alias/rp-central-dev` via `CONNECTION_SECRETS_KMS_KEY_ID` |

Deleted connection secrets have a 7-day recovery window (set in code).

---

## 14. Logging and secrets in logs

Already in the code:

- JSON lines to stdout (`app/core/logging.py`), with keys like `authorization`, `token`,
  `password`, `secret`, `upload_url` masked.
- The access log records method, path, route, status and duration. It records no query
  string, headers or body.
- Error handlers log the error code or class name, not the message body.

Infra rules:

- API Gateway access log has no header fields.
- Lambda does not log the event.
- LWA does not log requests by default.
- Log retention is 14 days for both groups.

---

## 15. Database migration procedure (new database)

Migrations are plain `alembic upgrade head`. They use the master login and are not destructive on
a new database. Do **not** run them from the API Lambda.

Recommended for DEV: **AWS CloudShell in VPC mode** (no new compute, no new code).

1. Create `rp-central-migrate-sg-dev` (no inbound; outbound 5432 to the DB SG and 443 out). Add
   the DB SG rule from it.
2. Start a CloudShell VPC environment in `rp-central-app-a-dev` with that SG, using an approved
   role that can read the DB master secret.
3. Clone the repo at the release commit. Install uv. Run `uv sync --locked --no-dev`.
4. Read the master secret into the shell only (not into a file, not echoed):
   `export DB_PASSWORD="$(aws secretsmanager get-secret-value --secret-id <arn> --query SecretString --output text | jq -r .password)"`.
   Set `DB_HOST`, `DB_USER=radial`, `DB_NAME=radial_pulse`, `DB_SSLMODE=require`, `APP_ENV=dev`.
   Set the Cognito variables too, because settings are checked on start.
5. Run `uv run alembic upgrade head`, then `uv run alembic current`.
6. Create `radial_api_iam`: run `infra/sql/create-app-login.sql` with `psql` as the master user.
   All 8 checks it prints must be `t`.
7. Create the first admin: `uv run python -m app.cli create-platform-admin --email <email> --name "<name>"`.
   This needs the Cognito admin permissions in the same account.
8. Close CloudShell. Remove the migrate SG rule.

For later releases: run the same steps before deploying the new image (expand → migrate →
contract, as `AGENTS.md` says). Never run a downgrade on a shared DB without a snapshot first.

---

## 16. Infrastructure as code

**Decided (8 Oct): CloudFormation.** The database stack is in
`infra/cloudformation/central-db-dev.yaml` (runbook: `docs/infrastructure/central-dev-db-setup.md`).
The network (VPC, subnets, NAT, S3 endpoint) is planned later. The text below is the earlier
recommendation, kept for history.

Earlier recommendation: **Terraform** in `infra/terraform/` (`modules/` +
`envs/dev/`). Reasons:

- The docs already assume Terraform modules.
- Terraform 1.16 is installed.
- `default_tags` puts the three required tags on every resource.
- `terraform plan` gives the review step this deploy needs.
- State goes in an S3 backend with a native lock file. No DynamoDB table is needed.

All account-specific values (account ID, pool ID, client IDs, CIDRs) come from `dev.tfvars` or
data lookups. Nothing secret goes into tfvars or state. The DB password is managed by RDS.

Alternatives: AWS SAM is simpler for Lambda + HTTP API alone, but is weak for VPC, Aurora and KMS.
If the platform team already runs Terraform or CDK in a separate repo, use that instead and keep
only the Dockerfile change here.

**Not added yet**, pending answers to B6/B7.

---

## 17. Deployment procedure (after the plan is approved)

1. Fix B1–B7. Sign in with the approved DEV role (short-lived).
2. `make check`. Integration tests on PostgreSQL in CI.
3. `terraform init` / `terraform plan -var-file=dev.tfvars -out=dev.plan`. Review the plan:
   - only creates, no destroys;
   - every resource has the three tags;
   - nothing named or tagged `prod`.
4. Apply in two steps:
   - Step 1: network, KMS, DB, S3, ECR, roles.
   - Step 2: Lambda and API, after the image is pushed.
5. Build and push: `docker build --target lambda -t <ecr>/rp-central-api-dev:<git sha> .`, then
   push. Use the image **digest** in Terraform.
6. Run migrations (section 15).
7. Apply step 2.
8. Smoke test:
   - `GET /health` returns 200.
   - `GET /ready` returns 200.
   - `GET /api/v1/auth/me` without a token returns 401 from the gateway.
   - `GET /api/v1/auth/me` with a web access token returns 200 for the invited admin.
   - A CORS preflight from the web origin passes.
   - A CORS preflight from another origin is refused.
   - `POST …/assessments` returns 503.
9. Check that the logs contain no tokens.

## 18. Rollback procedure

- **Code:** point the Lambda back to the previous image digest (`terraform apply` with the old
  digest, or `aws lambda update-function-code --image-uri <old digest>`). Use a Lambda alias
  `live` so the API can switch versions fast.
- **Migrations:** expand/contract means the old image still works with the new schema. Downgrade
  only after a manual cluster snapshot, and only if the migration's downgrade is safe.
- **Infra:** revert the Terraform change and apply. Deletion protection stays on for the DB. The S3
  bucket is not force-destroyed.
- **Full removal (DEV only, needs explicit approval):** snapshot the DB, then destroy.

## 19. Security notes

- **DB:** private, encrypted, TLS forced, only the Lambda SG can reach it, the API uses IAM auth
  and is not the owner (RLS applies).
- **Secrets:** no secrets in env vars, image, tfvars or git. The DB master secret is read only by
  the migration runner.
- **Tokens:** they are checked twice, once by the gateway and once by the app (access tokens only,
  client allow list).
- **CORS:** one exact origin, no `*`, no credentials.
- **S3:** private, KMS, TLS only, short-lived presigned URLs (5 minutes).
- **Logs:** no headers, tokens or bodies, 14-day retention.
- **Concurrency:** the cap of 10 limits DB load and cost.
- **Local access key:** do not use the local IAM-user key for this deploy (B2). The platform team
  should review that user.
- **DB cert check:** `DB_SSLMODE=require` encrypts but does not check the server certificate.
  Moving to `verify-full` needs the RDS CA bundle in the image (follow-up).

## 20. Manual steps

1. Platform team:
   - Give us the Central DEV account and an assumable deploy role.
   - Say which Central VPC, KMS key and execution role to reuse, if any.
2. Confirm the user pool ID, the web client ID and the CloudFront domain.
3. Decide on IaC (Terraform recommended) and where it lives. Decide the state bucket.
4. Answer open decisions #6, #13 and #20, and record the Lambda / no-SQS change in
   `decisions.md`.
5. Run the migrations and create the first admin (section 15). A person does this by hand.
6. Confirm the CORS headers the frontend sends.
