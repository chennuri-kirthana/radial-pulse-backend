# Central DEV database: handover

From: Person 1 (Backend) · To: Person 3 · updated 9 Oct 2026

This covers the 10 items you asked for. Everything is written as CloudFormation, plus one SQL
file, and tested locally. **Nothing has been created in AWS yet**: I don't have access to the
Central DEV account, so the deploy steps are yours.

Full step-by-step commands: `docs/infrastructure/central-dev-db-setup.md`.
**Quickest (10 Oct):** run the 3 scripts in `infra/deploy-dev/` (see its README) from AWS CloudShell.

> **Revision 10 Oct 2026 (no NAT gateway), by Person 3's deployment prep.** `central-network-dev.yaml`
> no longer creates a NAT gateway or Elastic IP. Item 4 below ("NAT for Cognito / JWKS") is therefore
> **not** provided. The migration (items 6, 7, 9) still works without internet: step 1 builds an
> offline toolkit and a temporary Secrets Manager VPC endpoint (`central-migration-access-dev.yaml`)
> that step 3 deletes. The API Lambda cannot be placed in this VPC until a decision on its internet
> egress is made. Read: `docs/infrastructure/central-dev-db-setup.md`, section "No NAT: what works and
> what does not", and `infra/deploy-dev/CHANGES-no-nat.md`. Rows below that mention a NAT describe the
> earlier design.

## Your questions, answered

**The 4 files you asked for** (all in this zip, inside the `radial-pulse-backend/` folder):

| File | Path in the zip |
|---|---|
| `central-network-dev.yaml` | `radial-pulse-backend/infra/cloudformation/central-network-dev.yaml` |
| `central-db-dev.yaml` | `radial-pulse-backend/infra/cloudformation/central-db-dev.yaml` |
| `create-app-login.sql` | `radial-pulse-backend/infra/sql/create-app-login.sql` |
| `central-dev-db-setup.md` | `radial-pulse-backend/docs/infrastructure/central-dev-db-setup.md` |

**Lambda role: keep the mentor's `rp-central-lambda-execution-dev`.** The DB stack no longer
creates a role. It only **attaches one new managed policy** to that role:
`rp-central-api-db-access-dev` = VPC/ENI permissions + `rds-db:connect` **only** as
`radial_api_iam`. Nothing already on the role is replaced, and deleting the stack removes only that
policy. (Parameter `ExistingLambdaRoleName`, default `rp-central-lambda-execution-dev`. Set it
empty only if you ever want the stack to create its own role instead.)

**Network:** there is no Central VPC yet, so deploy `central-network-dev.yaml` first.

**v15 application code (Steps C-F): done on my side.** `app/` now uses schema v15: session /
row-level-security layer, models, all endpoints, the Practitioner Profile. 440 tests pass on
PostgreSQL 16. Please don't change `app/`; use this copy for the Lambda deployment.

## What changed since the zip you got on 8 Oct

- `central-db-dev.yaml`: uses the mentor's Lambda role (see above). New output
  `LambdaDbAccessPolicyArn`.
- `create-app-login.sql`: `radial_api_iam` is now also a member of `radial_service` (needed by the
  read-only `/api/v1/internal` routes for other teams). It prints **8** checks now (was 7).
- `app/`: the whole v15 backend (Steps C-F). API contract `openapi/openapi.json` is version 0.4.0.

## What is in this zip

| Path | What |
|---|---|
| `infra/cloudformation/central-network-dev.yaml` | Items 2 + 4: VPC, public / app / db subnets in 2 AZs, NAT, S3 endpoint. **Skip it if Central DEV already has a VPC with a NAT.** |
| `infra/cloudformation/central-db-dev.yaml` | Items 1, 3, 5, 8, 10: Aurora PostgreSQL 16, security groups, IAM auth, master secret, Lambda permissions |
| `infra/sql/create-app-login.sql` | Items 6 + 7: creates `radial_api_iam` after the migration and prints 8 checks |
| `alembic/`, `app/`, `db/schema-v15.sql`, `pyproject.toml`, `uv.lock` | What item 9 (the v15 migration) runs. Use this copy: the v15 baseline is not on `main` yet. |
| `docs/infrastructure/central-dev-db-setup.md` | The runbook |

## What I did (Person 1)

| # | Item | Done | How it was checked |
|---|---|---|---|
| 1 | Aurora PostgreSQL 16, private, encrypted, DB `radial_pulse` | In `central-db-dev.yaml` | cfn-lint 1.57.2: no errors, no warnings |
| 2 | VPC / private subnets | In `central-network-dev.yaml` (optional) | cfn-lint: clean |
| 3 | Lambda SG + DB SG, 5432 only from the Lambda SG | In `central-db-dev.yaml`. DB SG has no outbound. A 3rd SG for the migration runner, opened only when `AllowMigrationAccess=true` | cfn-lint: clean |
| 4 | NAT for Cognito / JWKS | In `central-network-dev.yaml`: app subnets go out through one NAT | cfn-lint: clean |
| 5 | IAM DB auth | On. TLS forced (`rds.force_ssl=1`) | cfn-lint: clean |
| 6 | Roles `radial_app` (+ `radial_service`) | Created by the v15 migration | Ran on a fresh PostgreSQL 16 set up like RDS: OK |
| 7 | `radial_api_iam` with `rds_iam` | `create-app-login.sql` | All 8 checks true; safe to run twice; logged in as it: can switch to `radial_app`, access rules apply, cannot drop tables |
| 8 | Master credentials in Secrets Manager | RDS creates and keeps the password (`ManageMasterUserPassword`), encrypted with our KMS key | cfn-lint: clean |
| 9 | v15 migration with the owner login | Runbook step 4 | Ran the runbook's exact commands in Linux (`uv sync --locked --no-dev`, `alembic upgrade head`): `v15_baseline (head)`, 22 tables, all owned by the master user |
| 10 | Lambda role: VPC/ENI + `rds-db:connect` | **Keeps the mentor's role `rp-central-lambda-execution-dev`.** The stack only ATTACHES one new policy to it, `rp-central-api-db-access-dev` (VPC/ENI + `rds-db:connect` **only** as `radial_api_iam`). Nothing on the role is replaced. (Leave `ExistingLambdaRoleName` empty to create a separate role instead.) | cfn-lint: clean |

## What you need to do (Person 3), in order

1. **Check the account:** `aws sts get-caller-identity` shows Central DEV, region `ap-south-1`.
   Use an assumed role, not a long-lived access key.
2. **Pick the engine version** (16.3 or newer), using the command in runbook step 0. The default is `16.6`.
3. **Network:** if Central DEV has no VPC, deploy `central-network-dev.yaml`. Otherwise note the
   existing VPC ID, 2 private DB subnets, and 2 app subnets that have a NAT.
4. **Deploy `central-db-dev.yaml`** (runbook step 2). It takes about 10–15 min. Turn on termination protection.
5. **Run the migration** from CloudShell in VPC mode (runbook step 4): open the migration door,
   run `alembic upgrade head`, keep the shell open.
6. **Create `radial_api_iam`** with `create-app-login.sql` (runbook step 5), then close the door
   (`AllowMigrationAccess=false`) and close CloudShell.
7. **Send me the values** listed at the end of this file.

## What to check

| Check | Expected |
|---|---|
| Both stacks | `CREATE_COMPLETE` |
| RDS console → `rp-central-db-dev` | Engine Aurora PostgreSQL 16.x, **Publicly accessible: No**, Encryption on, IAM DB auth **Enabled**, Deletion protection on |
| Parameter group `rp-central-db-params-dev` | `rds.force_ssl = 1` |
| `rp-central-db-sg-dev` inbound | Only TCP 5432 from `rp-central-api-lambda-sg-dev` (plus the migrate SG only while migrating) |
| DB route table `rp-central-rt-db-dev` (network stack) | Only the `local` route. No `0.0.0.0/0` |
| App route table `rp-central-rt-app-dev` | `0.0.0.0/0` → NAT, plus the S3 endpoint |
| Secrets Manager | One `rds!cluster-…` secret, KMS key `alias/rp-central-dev` |
| `alembic current` | `v15_baseline (head)` |
| `create-app-login.sql` output | `t` on all 8 rows |
| IAM role `rp-central-lambda-execution-dev` | Its old policies are unchanged, plus `rp-central-api-db-access-dev`, whose `rds-db:connect` resource ends in `dbuser:cluster-…/radial_api_iam` (not `*`, not `radial`) |
| After you deploy the Lambda | `GET /ready` returns 200. The first call after the DB has been idle can take ~15 s. |

## What I need back

From the stack outputs (runbook step 3), **not passwords**:

- `DbEndpoint`, `DbPort`, `DbResourceId`
- `AppDbUser` (`radial_api_iam`) and `MasterUsername`
- `MasterSecretArn` (the ARN only)
- `VpcId`, `AppSubnetIds`, `DbSubnetIds`
- `LambdaSecurityGroupId`, `DbSecurityGroupId`, `LambdaExecutionRoleArn`, `LambdaDbAccessPolicyArn`, `KmsKeyArn`

## Not in this handover (later)

- Lambda role permissions for S3 (photos / voice), Secrets Manager (`radial-pulse/dev/connections/*`)
  and Cognito admin (invites). These are needed when those features go live
  (see `docs/infrastructure/backend-aws-needs.md`).
- Lambda function, API Gateway, S3 bucket. You said you will handle the Lambda deployment.
- The Lambda settings it needs: `DB_HOST=<DbEndpoint>`, `DB_USER=radial_api_iam`,
  `DB_IAM_AUTH=true`, `DB_SSLMODE=require`, `DB_NAME=radial_pulse`. **Never** the master secret.

## Costs (DEV, rough)

NAT gateway ~$35/month + data. Aurora Serverless v2 pauses at 0 ACU when idle (storage and
backups still cost a little). KMS key $1/month.
