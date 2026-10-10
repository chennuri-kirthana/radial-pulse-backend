# Changes in `radial-pulse-backend-db-no-nat.zip` (10 Oct 2026)

Base: `radial-pulse-backend-db-deploy.zip` (Person 1, 10 Oct). `app/`, `alembic/`, `db/`,
`pyproject.toml`, `uv.lock` and `infra/cloudformation/central-db-dev.yaml` are **unchanged**.
Nothing was deployed; no AWS resource, the Lambda or API Gateway was touched.

## Network: no NAT gateway

| File | Change |
|---|---|
| `infra/cloudformation/central-network-dev.yaml` | Removed `NatEip` (EIP), `NatGateway` and `AppDefaultRoute` (the `0.0.0.0/0` → NAT route). Removed outputs `NatGatewayId`, `NatPublicIp`. Added outputs `AppRouteTableId` (for a future NAT add-on) and `InternetEgress` (`none`). Public subnets and the internet gateway stay, empty, reserved. 23 → 20 resources. |
| `infra/cloudformation/central-migration-access-dev.yaml` | **New, temporary.** Secrets Manager interface endpoint in one app subnet (private DNS on, endpoint policy: read `rds!cluster-*` secrets only) + its security group (443 from `rp-central-migrate-sg-dev` only). Created in step 1, deleted in step 3. ~0.013 USD/hour while it exists. |

## Migration without internet

| File | Change |
|---|---|
| `infra/deploy-dev/build-migration-toolkit.sh` | **New.** Builds, where there is internet (normal CloudShell), an offline toolkit: pinned `uv 0.12.24`, uv-managed CPython 3.12, the locked runtime dependencies (`uv sync --locked --no-dev`), and this source folder, as one tar.gz. |
| `scripts/db/run_sql.py` | **New.** Runs a `.sql` file with psycopg (already a locked dependency), so `psql` need not be installed. Skips psql meta-commands (`\set`), keeps the file's own `BEGIN/COMMIT`, prints result rows, `--scalar` mode for shell checks. Connection from `DB_*` env vars only. |
| `infra/deploy-dev/1-deploy-network-and-db.sh` | Account check (`EXPECTED_ACCOUNT`, default 243894881176); refuses templates containing `AWS::EC2::NatGateway`/`EIP`; validates 3 templates; checks existing stacks (any state), VPCs with CIDR `10.40.0.0/16` or name `rp-central-vpc-dev`; every stack goes through a **change set that is printed and confirmed** (declining deletes it and any empty stack); refuses a change set with a NAT gateway; verifies the app route table has no `0.0.0.0/0`; deploys the temporary endpoint stack; writes `rp-migrate/central-dev.env` (IDs only) and builds + uploads the toolkit instead of the zip. |
| `infra/deploy-dev/2-migrate-and-create-login.sh` | Downloads nothing. Uses the toolkit (`uv run --offline --no-sync`), reads IDs from `central-dev.env` (no CloudFormation/STS calls), checks that `secretsmanager.ap-south-1.amazonaws.com` resolves inside the VPC, reads the master password through the endpoint, runs the migration, `create-app-login.sql` and the optional seeds with `run_sql.py`. Verifies home directory and CPU match the toolkit. |
| `infra/deploy-dev/3-close-migration-door.sh` | Also deletes `rp-central-migration-access-dev` (the hourly-billed endpoint) before closing the door and deleting the bucket; account check. |
| `infra/deploy-dev/README.md` | Rewritten for the no-NAT flow: costs, permissions, what to expect, failure table, rollback. |
| `docs/infrastructure/central-dev-db-setup.md` | No-NAT revision note; new section **"No NAT: what works and what does not"** (incl. why a Cognito VPC endpoint does not help a pool with a Managed Login domain, and the 3 options for the Lambda); steps 4–5 rewritten for the offline toolkit and the temporary endpoint; cleanup order. |
| `infra/HANDOVER.md`, `docs/infrastructure/dev-lambda-plan.md`, `docs/architecture/decisions.md` | Dated notes pointing to the no-NAT design; new blocker B8 (Lambda egress). Older NAT text left as history, marked. |

## Carried over from the validated Lambda release (10 Oct, earlier)

`scripts/lambda/build_zip.py` (`--output`, no stray `.lock`, LF `.sha256`), `scripts/lambda/verify_zip.py`
(new), `openapi/openapi.json` (regenerated; the bundle's copy was stale against v0.5.0 code),
`sdk/central-client/README.md` (format fix), `docs/infrastructure/lambda-package.md`. The deployed Lambda
ZIP (`radial-pulse-api-dev-x86_64.zip`, SHA-256 `e4475a95…4e48`) is unchanged and not in this zip.

## Intentional remaining "NAT" mentions

`central-db-dev.yaml` line 86 ("needs NAT or VPC endpoints", a security-group comment: still true),
`docs/architecture/decisions.md` row "Single NAT in DEV" (the earlier decision, now annotated),
`dev-lambda-plan.md` sections 1/4/7 (the NAT-era plan, annotated at the top), the "No NAT" sections
themselves.

## Validation (all run on 10 Oct 2026; nothing against AWS)

| Check | Result |
|---|---|
| `cfn-lint 1.57.2 --regions ap-south-1` on the 3 templates | no errors, no warnings |
| `bash -n` on the 4 scripts | OK |
| `shellcheck -x -S style` on the 4 scripts | 0 findings |
| `ruff check`, `ruff format --check`, `mypy --strict` on `scripts/db/run_sql.py` | pass |
| Templates contain `AWS::EC2::NatGateway` or `AWS::EC2::EIP` | **no** (grep); script 1 enforces it too |
| **Offline migration test**: `build-migration-toolkit.sh` run in an Amazon Linux 2023 x86_64 container with internet (21 s, 94 MB), then the **real** `2-migrate-and-create-login.sh` run in a second AL2023 container on a Docker network with **no internet** (`curl https://pypi.org` fails), against PostgreSQL 16 with TLS (`sslmode=require`) and the `rds_iam`/`rds_superuser` roles, Secrets Manager stubbed | `alembic current: v15_baseline (head)`; 23 tables; `radial_api_iam` created, **8/8 checks True**; both seeds loaded (5 clinics); exit 0 |
| Repo checks on the assembled tree (`ruff`, `mypy`, `openapi_export --check`, fast tests) | see the zip's `VALIDATION.txt` |

**Not validated (needs the Central DEV account):** the CloudFormation API itself (`validate-template`,
change sets), CloudShell VPC environment behaviour (credentials without an STS endpoint; AWS documents
no-internet VPC environments but this exact flow has not been run), Aurora IAM auth, the Secrets
Manager endpoint's private DNS inside CloudShell, the Lambda role existing.

## Still blocked

- **The API Lambda cannot run inside this VPC.** Without NAT it cannot fetch Cognito's JWKS, call
  `/oauth2/userInfo` or the Cognito admin API; a `cognito-idp` VPC endpoint does not work for a pool
  that has a Managed Login domain (AWS docs). So the deployed Lambda must stay outside the VPC (as it
  is), and then it cannot reach the private database. Decision needed: NAT gateway (~45 USD/month),
  NAT instance (~4 USD/month), or an application change (JWKS from S3, no `userInfo` fallback).
  Details: `docs/infrastructure/central-dev-db-setup.md`, "No NAT: what works and what does not".
- The Lambda role `rp-central-lambda-execution-dev` must exist (or let the stack create one).
- A CloudShell VPC environment needs IAM permission for `cloudshell:CreateEnvironment` with VPC settings.
