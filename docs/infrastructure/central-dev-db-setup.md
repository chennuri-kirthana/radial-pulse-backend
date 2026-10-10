# Central DEV database setup (CloudFormation)

> **Easiest way:** the 3 scripts in `infra/deploy-dev/` do every step below, asking before each part.
> Start with `infra/deploy-dev/README.md`.

> **Revision 10 Oct 2026, no NAT gateway.** The network stack no longer creates a NAT gateway or an
> Elastic IP (about 45 USD/month saved). The app and db subnets have **no route to the internet**.
> The migration still works (section "No NAT: what works and what does not"); moving the API Lambda
> into this VPC does **not** work yet. Read that section before you plan the Lambda.

How to create the Central DEV database and get the values the API Lambda needs.
Region: **ap-south-1**. Do the steps in order.

| File | What it is |
|---|---|
| `infra/cloudformation/central-network-dev.yaml` | Network stack: VPC, subnets, S3 gateway endpoint. **No NAT.** Only if Central DEV has no Radial Pulse VPC yet. |
| `infra/cloudformation/central-db-dev.yaml` | Database stack: KMS key, security groups, Aurora PostgreSQL 16, master secret, Lambda permissions |
| `infra/cloudformation/central-migration-access-dev.yaml` | **Temporary** stack for the migration: a Secrets Manager interface endpoint in one app subnet. Created in step 1, deleted in step 3. |
| `infra/deploy-dev/*.sh` | The scripts that run this runbook (change sets, confirmations, offline toolkit) |
| `scripts/db/run_sql.py` | Runs a `.sql` file with psycopg (the VPC environment cannot install `psql`) |
| `infra/sql/create-app-login.sql` | Creates the API's database login `radial_api_iam` (run after the migration) |

## Network stack (only if there is no VPC yet)

`central-network-dev.yaml` creates, in 2 AZs:

| Subnets | CIDR (default VPC `10.40.0.0/16`) | Internet | Used by |
|---|---|---|---|
| `rp-central-public-{a,b}-dev` | `.0.0/24`, `.1.0/24` | route to the IGW, but **empty** | nothing (reserved for a NAT gateway, if one is ever added) |
| `rp-central-app-{a,b}-dev` | `.10.0/24`, `.11.0/24` | **none** (S3 only, through the gateway endpoint) | CloudShell for migrations; the Lambda later, see "No NAT" |
| `rp-central-db-{a,b}-dev` | `.20.0/24`, `.21.0/24` | **none** | the database |

Plus: an internet gateway (attached, used by nothing), three route tables, and a free S3 gateway
endpoint on the app route table. **No NAT gateway, no Elastic IP** (10 Oct 2026). Change `VpcCidr`
if `10.40.0.0/16` overlaps another VPC you will connect to. The account's default VPC
(`172.31.0.0/16`) is not used.

Create it as a change set and read the change set before you execute it (the script does this):

```bash
aws cloudformation deploy \
  --region ap-south-1 \
  --stack-name rp-central-network-dev \
  --template-file infra/cloudformation/central-network-dev.yaml \
  --no-execute-changeset \
  --tags Project=RadialPulse Team=Central Environment=dev
# read it: all Actions "Add", 20 resources, no AWS::EC2::NatGateway, no AWS::EC2::EIP; then
aws cloudformation execute-change-set --region ap-south-1 --change-set-name <arn printed above>
aws cloudformation wait stack-create-complete --region ap-south-1 --stack-name rp-central-network-dev

aws cloudformation describe-stacks --region ap-south-1 --stack-name rp-central-network-dev \
  --query "Stacks[0].Outputs" --output table
```

Use its outputs below: `VpcId` and `DbSubnetIds` go into the database stack; `AppSubnetIds`
are for the Lambda and for CloudShell.

## What the stack creates (and what it does not)

Creates:
- KMS key `alias/rp-central-dev` (rotation on) for the database and its secret
- Security groups:
  - `rp-central-api-lambda-sg-dev`: no inbound; outbound 443 and 5432 to the DB SG
  - `rp-central-db-sg-dev`: inbound 5432 **only** from the Lambda SG; no outbound
  - `rp-central-migrate-sg-dev`: for the migration runner; the DB lets it in only when `AllowMigrationAccess=true`
- DB subnet group `rp-central-db-subnets-dev`
- Cluster parameter group `rp-central-db-params-dev` with `rds.force_ssl = 1` (TLS required)
- Aurora PostgreSQL 16 Serverless v2 cluster `rp-central-db-dev` + instance `rp-central-db-dev-1`:
  database `radial_pulse`, private, encrypted, IAM auth on, 7-day backups, deletion protection on,
  0–2 ACU (pauses after 30 min idle; the first request after a pause can take ~15 s)
- Master password: created and kept by RDS in Secrets Manager (never typed, never in git)
- Lambda permissions: the Lambda keeps the mentor's role `rp-central-lambda-execution-dev`. The stack
  only ATTACHES one new managed policy to it, `rp-central-api-db-access-dev` (VPC/ENI access +
  `rds-db:connect` **only** as `radial_api_iam`). Nothing on the role is replaced. To create a
  separate role instead, deploy with `ExistingLambdaRoleName=` (empty).

Does **not** create the network: you pass in a VPC and private subnets, either existing ones
or the ones from the network stack above.

## No NAT: what works and what does not

The app subnets reach **only**: the VPC itself (the database), Amazon S3 (free gateway endpoint),
and any interface endpoint you add. Nothing on the public internet.

| Who | Needs | Without NAT | How this release handles it |
|---|---|---|---|
| Migration runner (CloudShell VPC environment, step 4) | the database | works (same VPC) | — |
| | the code, uv, Python, PyPI packages, `psql` | **cannot download** | Step 1 builds an **offline toolkit** in the normal CloudShell (which has internet) and copies it through S3. `psql` is replaced by `scripts/db/run_sql.py` (psycopg). |
| | the master password (Secrets Manager) | **cannot reach** the public endpoint | Temporary stack `rp-central-migration-access-dev`: Secrets Manager **interface endpoint** in app subnet A, reachable only from `rp-central-migrate-sg-dev`. About 0.013 USD/hour; step 3 deletes it. |
| | CloudFormation / STS | cannot reach | Step 1 writes the stack outputs into the toolkit (`rp-migrate/central-dev.env`). Step 2 reads that file and never calls CloudFormation or STS. |
| API Lambda (`rp-central-api-dev`), if moved into these subnets | Cognito **JWKS** (`cognito-idp.ap-south-1.amazonaws.com/<pool>/.well-known/jwks.json`) on every cold start | **cannot reach** → every token refused (401) | **Not solved. Blocker.** See below. |
| | Cognito `/oauth2/userInfo` on the Managed Login domain (first sign-in of an account without a `sub`) | cannot reach → 401 "Could not confirm your identity" | Not solved. |
| | Cognito admin API (invites, `IDENTITY_DIRECTORY_BACKEND=cognito`) | cannot reach | Not solved. |
| | S3 (photos, voice, avatars) | works (gateway endpoint) | — |
| | Aurora with IAM auth | works; the token is signed locally, no network call | — |
| | Secrets Manager (connected-account "disconnect") | cannot reach | would need its own interface endpoint (about 9.5 USD/month per AZ) |

**Why a Cognito VPC endpoint does not fix the Lambda.** Amazon Cognito user pools do support
AWS PrivateLink (`com.amazonaws.ap-south-1.cognito-idp`), but the AWS documentation states that a
user pool **with a domain assigned is incompatible with PrivateLink**: "The existence of a user pool
domain prevents completion of any user pool requests that transit a VPC endpoint", and "VPC private
DNS doesn't route requests for user pool domains to your VPC endpoint". Our pool has the Managed
Login domain `rp-central-rp-dev` (the web app signs in with it), so a `cognito-idp` endpoint would
not serve JWKS, the admin API, or `userInfo`. An S3 endpoint has nothing to do with Cognito.

**So, today:** leave the Lambda **outside** the VPC, as it is deployed now (it keeps internet and
Cognito works), which means it **cannot reach the private database**. Moving it in needs one of
these decisions (not made in this release, nothing is changed on the Lambda):

1. **NAT gateway** (the original design): about 45 USD/month. Add a small NAT stack: EIP + NAT in
   `rp-central-public-a-dev` + a `0.0.0.0/0` route in `AppRouteTableId` (network stack output).
2. **NAT instance** (EC2, e.g. a t4g.nano running a NAT image): about 4 USD/month, but one more
   server to patch and watch.
3. **Code change** in `app/`: read the JWKS from a copy in S3 that a small scheduled Lambda outside
   the VPC refreshes; turn the `userInfo` fallback off; keep invites outside the VPC. This is an
   architecture change for the backend owner, not a deployment setting.

Option 3 is the only one with zero hourly network cost, and the only one that touches application
code. Until a decision is made, `GET /ready` on the deployed Lambda will keep answering 503.

## 0. Before you start

You need: the AWS CLI with a role in the Central DEV account that can create these resources,
and `CAPABILITY_NAMED_IAM` (the stack creates a named IAM role).

```bash
aws sts get-caller-identity          # check you are in the Central DEV account
aws configure get region             # must be ap-south-1
```

Check the Aurora PostgreSQL 16 versions available (pick 16.3 or newer, needed for pause at 0 ACU):

```bash
aws rds describe-db-engine-versions --engine aurora-postgresql --region ap-south-1 \
  --query "DBEngineVersions[?starts_with(EngineVersion,'16.')].EngineVersion" --output text
```

Pick the VPC and **at least 2 private subnets in 2 different AZs** (no route to an internet gateway).
If there is no VPC yet, deploy the network stack first (section above).

## 1. Check the template

```bash
aws cloudformation validate-template --template-body file://infra/cloudformation/central-network-dev.yaml
aws cloudformation validate-template --template-body file://infra/cloudformation/central-db-dev.yaml
```

## 2. Create the stack

```bash
aws cloudformation deploy \
  --region ap-south-1 \
  --stack-name rp-central-db-dev \
  --template-file infra/cloudformation/central-db-dev.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      VpcId=vpc-XXXXXXXX \
      DbSubnetIds=subnet-AAAAAAAA,subnet-BBBBBBBB \
      EngineVersion=16.X \
  --tags Project=RadialPulse Team=Central Environment=dev
```

Takes about 10–15 minutes. Then turn on termination protection, so the stack can't be deleted
by mistake:

```bash
aws cloudformation update-termination-protection --region ap-south-1 \
  --stack-name rp-central-db-dev --enable-termination-protection
```

## 3. Read the outputs

```bash
aws cloudformation describe-stacks --region ap-south-1 --stack-name rp-central-db-dev \
  --query "Stacks[0].Outputs" --output table
```

| Output | Use |
|---|---|
| `DbEndpoint`, `DbPort`, `DbName` | Lambda `DB_HOST`, `DB_PORT`, `DB_NAME` |
| `AppDbUser` (`radial_api_iam`) | Lambda `DB_USER` (with `DB_IAM_AUTH=true`, `DB_SSLMODE=require`) |
| `DbResourceId` | already used in the role's `rds-db:connect` permission |
| `MasterSecretArn` | migration runner only. **Never** give it to the Lambda. |
| `LambdaSecurityGroupId` | Lambda VPC config (later, once the Lambda may run without internet: see "No NAT"), with the **app** subnets, not the DB subnets |
| `DbSubnetIds` | reference (where the database lives) |
| `LambdaExecutionRoleArn` | the Lambda's execution role (the mentor's `rp-central-lambda-execution-dev`) |
| `LambdaDbAccessPolicyArn` | the policy the stack attached to that role |
| `DbSecurityGroupId`, `MigrateSecurityGroupId`, `KmsKeyArn` | reference |

Share the **secret ARN** only, never the password.

## 4. Run the v15 migration (inside the VPC)

The database is private, so this can't run from a laptop. Use **AWS CloudShell in VPC mode**.

The VPC environment has **no internet** (no NAT), so it cannot install anything. Everything it
runs is prepared first in the normal CloudShell. `infra/deploy-dev/1-deploy-network-and-db.sh`
does 1–3 below; `2-migrate-and-create-login.sh` does 4–5.

1. Open the migration door: re-run step 2 with `AllowMigrationAccess=true` added to
   `--parameter-overrides` (keep the other values the same).
2. Create the temporary Secrets Manager endpoint (about 0.013 USD/hour; deleted in step 5):

   ```bash
   aws cloudformation deploy --region ap-south-1 --stack-name rp-central-migration-access-dev \
     --template-file infra/cloudformation/central-migration-access-dev.yaml \
     --parameter-overrides VpcId=<VpcId> EndpointSubnetId=<first of AppSubnetIds> \
         MigrateSecurityGroupId=<MigrateSecurityGroupId> \
     --tags Project=RadialPulse Team=Central Environment=dev
   ```

3. Still in the normal CloudShell (it has internet), build the **offline toolkit** and copy it to a
   private bucket in ap-south-1 (the app subnets reach S3 through the gateway endpoint):

   ```bash
   cd radial-pulse-backend
   mkdir -p ~/rp-migrate
   # IDs step 4 needs (no secrets). The VPC environment cannot call CloudFormation.
   printf 'RP_REGION=ap-south-1\nRP_HOME=%s\nRP_DB_HOST=%s\nRP_DB_PORT=5432\nRP_DB_NAME=radial_pulse\nRP_MASTER_USER=radial\nRP_MASTER_SECRET_ARN=%s\nRP_VPC_ID=%s\nRP_APP_SUBNET_A=%s\nRP_MIGRATE_SG=%s\nRP_BUCKET=%s\n' \
     "$HOME" <DbEndpoint> <MasterSecretArn> <VpcId> <app subnet A> <MigrateSecurityGroupId> rp-central-deploy-dev-<account id> \
     > ~/rp-migrate/central-dev.env
   bash infra/deploy-dev/build-migration-toolkit.sh ~/rp-migrate ~/rp-migrate-toolkit.tar.gz
   aws s3 cp ~/rp-migrate-toolkit.tar.gz s3://rp-central-deploy-dev-<account id>/rp-migrate-toolkit.tar.gz
   ```

   The toolkit holds uv (pinned), a uv-managed CPython 3.12, the locked runtime dependencies and
   this source folder. It works in the VPC environment because both CloudShell kinds are Amazon
   Linux 2023 on x86_64 with the same home directory (`/home/cloudshell-user`).
4. CloudShell: the **+** icon → **Create VPC environment**. Choose the Radial Pulse VPC, subnet
   `rp-central-app-a-dev` (the **same** subnet as the Secrets Manager endpoint) and security group
   `rp-central-migrate-sg-dev`. In that environment (**Actions → Upload file** does not work there,
   and there is no internet):

   ```bash
   aws s3 cp s3://rp-central-deploy-dev-<account id>/rp-migrate-toolkit.tar.gz . && tar -xzf rp-migrate-toolkit.tar.gz
   bash radial-pulse-backend/infra/deploy-dev/2-migrate-and-create-login.sh
   ```

   The script checks the database port and that `secretsmanager.ap-south-1.amazonaws.com` resolves
   to a `10.40.x.x` address (the endpoint), reads the master password into the shell only, runs
   `alembic upgrade head` offline (`uv run --offline --no-sync`), checks `v15_baseline (head)`,
   then runs `infra/sql/create-app-login.sql`.

## 5. Create the API login `radial_api_iam`

Done by `2-migrate-and-create-login.sh` right after the migration; by hand it is:

```bash
# in the VPC environment, after step 4, same shell (DB_* variables still set)
uv run --offline --no-sync python scripts/db/run_sql.py infra/sql/create-app-login.sql
```

The last table it prints must show **`t` on all 8 rows** (can log in, not superuser, does not
bypass access rules, member of `radial_app`, member of `radial_service`, has `rds_iam`, not
`rds_superuser`, owns no tables).
If the script stops with "role radial_app is missing", step 4 did not run.

Then clean up:

```bash
unset DB_PASSWORD
```

Close the CloudShell VPC environment (its files go with it). Then, in the normal CloudShell,
`infra/deploy-dev/3-close-migration-door.sh` does the cleanup; by hand:

1. Delete the temporary endpoint stack (stops its hourly charge):
   `aws cloudformation delete-stack --region ap-south-1 --stack-name rp-central-migration-access-dev`
2. Close the migration door: re-run step 2 with `AllowMigrationAccess=false`.
3. Empty and delete the bucket `rp-central-deploy-dev-<account id>`.

Do not skip 1 and 2: together they are the temporary database access.

## 6. Check the API login works (after the Lambda is deployed)

The Lambda logs in as `radial_api_iam` with an IAM token (no password). `GET /ready` should
return 200. If it returns 503, check in this order:

1. The Lambda uses `rp-central-lambda-execution-dev` (with `rp-central-api-db-access-dev` attached) and `rp-central-api-lambda-sg-dev`.
2. `DB_USER=radial_api_iam`, `DB_IAM_AUTH=true`, `DB_SSLMODE=require`.
3. The database was paused (first request ~15 s): try again.

## Later releases

New migrations: repeat steps 4.1–4.3 (open door, migrate, close door). Step 5 is only needed once.
Take a manual cluster snapshot before any risky migration. Never downgrade a shared DB without one.

## Deleting (only if really needed)

Deletion protection is on, and deleting the stack keeps a final snapshot and the KMS key.
Turn off termination protection and the cluster's deletion protection first, on purpose.
