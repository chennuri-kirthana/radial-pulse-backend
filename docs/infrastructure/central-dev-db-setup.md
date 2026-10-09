# Central DEV database setup (CloudFormation)

How to create the Central DEV database and get the values the API Lambda needs.
Region: **ap-south-1**. Do the steps in order.

| File | What it is |
|---|---|
| `infra/cloudformation/central-network-dev.yaml` | Network stack: VPC, subnets, NAT, S3 endpoint. **Only if Central DEV has no VPC yet.** |
| `infra/cloudformation/central-db-dev.yaml` | Database stack: KMS key, security groups, Aurora PostgreSQL 16, master secret, Lambda permissions |
| `infra/sql/create-app-login.sql` | Creates the API's database login `radial_api_iam` (run after the migration) |

## Network stack (only if there is no VPC yet)

`central-network-dev.yaml` creates, in 2 AZs:

| Subnets | CIDR (default VPC `10.40.0.0/16`) | Internet | Used by |
|---|---|---|---|
| `rp-central-public-{a,b}-dev` | `.0.0/24`, `.1.0/24` | in + out (IGW) | the NAT only |
| `rp-central-app-{a,b}-dev` | `.10.0/24`, `.11.0/24` | out only, through the NAT | the Lambda, CloudShell for migrations |
| `rp-central-db-{a,b}-dev` | `.20.0/24`, `.21.0/24` | **none** | the database |

Plus: internet gateway, one NAT gateway with an Elastic IP (DEV: one NAT, about $35/month plus
data), route tables, and a free S3 gateway endpoint on the app subnets. Change `VpcCidr` if
`10.40.0.0/16` overlaps another VPC you will connect to.

```bash
aws cloudformation deploy \
  --region ap-south-1 \
  --stack-name rp-central-network-dev \
  --template-file infra/cloudformation/central-network-dev.yaml \
  --tags Project=RadialPulse Team=Central Environment=dev

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

> **The network must have a NAT (or VPC endpoints):** a Lambda inside the VPC can't reach
> Cognito (JWKS / userInfo) or Secrets Manager without one, so every login would fail. The
> migration runner (step 4) also needs outbound internet to download the code and packages.
> The network stack above has this.

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
| `LambdaSecurityGroupId` | Lambda VPC config, with the **app** subnets (the ones with the NAT), not the DB subnets |
| `DbSubnetIds` | reference (where the database lives) |
| `LambdaExecutionRoleArn` | the Lambda's execution role (the mentor's `rp-central-lambda-execution-dev`) |
| `LambdaDbAccessPolicyArn` | the policy the stack attached to that role |
| `DbSecurityGroupId`, `MigrateSecurityGroupId`, `KmsKeyArn` | reference |

Share the **secret ARN** only, never the password.

## 4. Run the v15 migration (inside the VPC)

The database is private, so this can't run from a laptop. Use **AWS CloudShell in VPC mode**.

1. Open the migration door:
   re-run step 2 with `AllowMigrationAccess=true` added to `--parameter-overrides`
   (keep the other values the same).
2. In CloudShell: **Actions → Create VPC environment**. Choose the same VPC, a subnet that has
   outbound internet (`rp-central-app-a-dev` if you used the network stack), and security group
   `rp-central-migrate-sg-dev`.
3. In that environment, get the code: `git clone` the repo at the release commit, **or**
   upload the handover zip (**Actions → Upload file**) and `unzip` it. Then:

   ```bash
   cd radial-pulse-backend
   curl -LsSf https://astral.sh/uv/install.sh | sh && export PATH="$HOME/.local/bin:$PATH"
   uv sync --locked --no-dev

   SECRET_ARN=<MasterSecretArn>
   # Read the password into this shell only: not into a file, not printed.
   export DB_PASSWORD="$(aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" \
       --query SecretString --output text | jq -r .password)"
   export DB_HOST=<DbEndpoint> DB_PORT=5432 DB_NAME=radial_pulse DB_USER=radial DB_SSLMODE=require
   export APP_ENV=dev
   # Settings are checked on start, so the Cognito values must be set too:
   export COGNITO_REGION=ap-south-1 COGNITO_USER_POOL_ID=<pool id> COGNITO_APP_CLIENT_IDS=<web client id>

   uv run --no-sync alembic upgrade head
   uv run --no-sync alembic current   # must show: v15_baseline (head)
   ```

## 5. Create the API login `radial_api_iam`

Still in the same CloudShell, right after step 4:

```bash
sudo dnf install -y postgresql16
PGPASSWORD="$DB_PASSWORD" psql "host=$DB_HOST dbname=radial_pulse user=radial sslmode=require" \
  -v ON_ERROR_STOP=1 -f infra/sql/create-app-login.sql
```

The last table it prints must show **`t` on all 8 rows** (can log in, not superuser, does not
bypass access rules, member of `radial_app`, member of `radial_service`, has `rds_iam`, not
`rds_superuser`, owns no tables).
If the script stops with "role radial_app is missing", step 4 did not run.

Then clean up:

```bash
unset DB_PASSWORD
```

Close the CloudShell VPC environment, and close the migration door: re-run step 2 with
`AllowMigrationAccess=false`.

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
