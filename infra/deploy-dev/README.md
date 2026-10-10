# Central DEV database: 3 scripts for Person 3 — **no NAT gateway** edition

From: Person 1 (scripts, 10 Oct 2026), revised for the no-NAT network the same day · goes with
`radial-pulse-backend-db-no-nat.zip`.

**Why there is no "database" in the zip:** an AWS database can't be put in a file. The zip has the
templates and scripts that **create** it in your AWS account. They take about 30–40 minutes in total.

**What changed from the NAT version:** the network has **no NAT gateway and no Elastic IP** (about
45 USD/month saved). The app and database subnets have no route to the internet. The migration still
works, because step 1 builds everything step 2 needs and copies it through S3, and a temporary VPC
endpoint gives step 2 the master password. **The API Lambda cannot be moved into this VPC yet**:
it would lose access to Cognito and every sign-in would fail. Details and the decision to make:
`docs/infrastructure/central-dev-db-setup.md`, section "No NAT: what works and what does not".
Nothing here touches the Lambda function or API Gateway.

## Before you start

- Sign in to the AWS console as a role (not a long-lived access key) that can create CloudFormation
  stacks, EC2/VPC resources, RDS, KMS, S3 buckets, VPC endpoints, and IAM policies
  (`CAPABILITY_NAMED_IAM` is used by the database stack). It also needs CloudShell with VPC
  environments (`cloudshell:CreateEnvironment` and the VPC condition keys).
- Account **243894881176**, region **ap-south-1 (Mumbai)**. Script 1 refuses any other account.
- The account's default VPC (`172.31.0.0/16`) is **not** used. The scripts create `10.40.0.0/16`.
- Nothing Radial Pulse must exist yet: no `rp-central-*` stacks, VPCs or RDS clusters. Script 1
  checks this and stops if it finds any.
- Costs after step 3: Aurora Serverless v2 (0–2 ACU, pauses when idle; a few USD/month in storage
  and backups), KMS key 1 USD/month. **No hourly network charge.** During steps 1–3 only: the
  Secrets Manager interface endpoint, about 0.013 USD/hour.
- No keys or passwords are typed, printed or saved. The master password is created by RDS, kept in
  Secrets Manager, and read into the step-2 shell only.

## Step 1: create the network and the database (normal CloudShell)

1. Open **CloudShell** (the `>_` icon in the top bar). Make sure it is the normal one (no VPC).
2. **Actions → Upload file** → `radial-pulse-backend-db-no-nat.zip`.
3. Run:
   ```bash
   unzip -q radial-pulse-backend-db-no-nat.zip && cd radial-pulse-backend
   bash infra/deploy-dev/1-deploy-network-and-db.sh
   ```
4. It checks the account, validates the 3 templates, lists existing VPCs and stacks, and refuses to
   continue if a `10.40.0.0/16` VPC or a `rp-central-*` stack already exists outside its own stacks.
5. For every stack it creates a **change set**, prints it, and asks before executing. Read it:
   - network: 20 rows, all `Add`, **no `AWS::EC2::NatGateway`, no `AWS::EC2::EIP`** (the script
     also refuses any change set that contains a NAT gateway);
   - database: about 16 rows, all `Add`, including one `AWS::IAM::ManagedPolicy` attached to
     `rp-central-lambda-execution-dev`;
   - migration access: 2 rows (`AWS::EC2::SecurityGroup`, `AWS::EC2::VPCEndpoint`).
6. Press Enter to accept the suggested Aurora engine version. Creating the database takes 10–15 min.
7. It then builds the **offline toolkit** (uv + Python 3.12 + the locked dependencies + this code,
   about 95 MB) and copies it to the private bucket `rp-central-deploy-dev-<account id>`. Step 3
   deletes the bucket.
8. At the end it prints the stack outputs (also saved to `central-dev-outputs.txt`, IDs and ARNs
   only) and the exact 3 values and 2 commands for step 2.

## Step 2: create the tables and the backend login (CloudShell VPC environment)

The database is private, so this step must run **inside** the VPC. That environment has **no
internet**: it downloads nothing and installs nothing; it uses the toolkit from step 1.

1. CloudShell → the **+** icon → **Create VPC environment**. Use the 3 values step 1 printed:
   the VPC, subnet **`rp-central-app-a-dev`** (it must be the same subnet as the Secrets Manager
   endpoint) and security group `rp-central-migrate-sg-dev`.
2. In that new environment, copy the two lines step 1 printed:
   ```bash
   aws s3 cp s3://rp-central-deploy-dev-<account id>/rp-migrate-toolkit.tar.gz . && tar -xzf rp-migrate-toolkit.tar.gz
   bash radial-pulse-backend/infra/deploy-dev/2-migrate-and-create-login.sh
   ```
   (**Actions → Upload file** does not work in a VPC environment. ✅ AWS: "You cannot use the
   CloudShell upload and download options in the Actions menu for VPC environments.")
3. Expected:
   - `Toolkit OK: Python 3.12.x, uv 0.12.24 (offline).`
   - `secretsmanager.ap-south-1.amazonaws.com resolves to 10.40.x.x` (the endpoint);
   - `alembic current: v15_baseline (head)`;
   - a table with **`True` on all 8 rows** of the `ok` column.
4. It then asks: **Load FAKE demo data?** Answer `y` in DEV, so the demo has clinics to show. These
   are sample clinics with made-up addresses (`.example` websites) and no real people. Never do this
   in PROD. Afterwards `/active-clinics` shows 3 clinics; the lead and the archived clinic give 404.

## Step 3: close the migration door (normal CloudShell)

Close the VPC environment (its files are deleted with it). Back in the normal CloudShell tab, from
the `radial-pulse-backend` folder:
```bash
bash infra/deploy-dev/3-close-migration-door.sh
```
It deletes the temporary endpoint stack (stops the hourly charge), sets `AllowMigrationAccess=false`
on the database stack (only the Lambda security group may reach port 5432 now), and deletes the
temporary code bucket. **Run it even if step 2 failed**, then fix and start again from step 1
(it skips stacks that already exist).

## Send back to Person 1

- `central-dev-outputs.txt` from the normal CloudShell (**Actions → Download file**, or copy the
  text). It has no passwords.
- A screenshot or copy of the 8 checks from step 2.

**Never send:** the master password or any `secretsmanager get-secret-value` output.

## If something fails

| Message | Meaning |
|---|---|
| `signed in to account ... expected Central DEV 243894881176` | Wrong account. Sign in to Central DEV. |
| `a VPC with CIDR 10.40.0.0/16 already exists` / `already exists outside stack` | Radial Pulse networking exists but was not made by these stacks. Stop; find out who made it. Do not create a second one. |
| `... is in state ROLLBACK_COMPLETE` | A previous create failed. Open CloudFormation → the stack → Events for the cause, delete the stack, run again. |
| `AccessDenied` | Your role lacks a permission. Ask the account admin. |
| `Lambda role rp-central-lambda-execution-dev was NOT found` | The mentor's Lambda role doesn't exist yet. Choose `y` to let the stack create its own role, or create the role first. |
| `the change set would create a NAT gateway` | Wrong template file. This release must not have one. |
| `Cannot reach ...:5432` (step 2) | Not in the VPC environment, wrong subnet or security group, step 1 didn't finish, or Aurora is waking up (wait 15 s, retry). |
| `secretsmanager.ap-south-1.amazonaws.com does not resolve` (step 2) | Stack `rp-central-migration-access-dev` is missing (step 1 was stopped early, or step 3 already ran). |
| `resolves to ..., a public address` (step 2) | The VPC environment is not in the endpoint's VPC/subnet, or private DNS is off. Recreate the environment with the printed values. |
| `the toolkit was built for home directory ...` | Toolkit built on a different machine. Run step 1 again in CloudShell. |
| `role radial_app is missing` | The migration didn't run. Run step 2 again. |
| `role "rds_superuser" does not exist` | You are not on Aurora/RDS (only happens on a plain PostgreSQL test server). |

## Rollback

- **Before step 2 ran:** `3-close-migration-door.sh`, then delete the stacks in this order:
  `rp-central-migration-access-dev` (if still there), `rp-central-db-dev` (turn termination
  protection off first; the cluster keeps a final snapshot and has deletion protection on: turn
  that off on the cluster first, on purpose), then `rp-central-network-dev`. The KMS key is kept
  (`Retain`): schedule its deletion by hand if you really want it gone.
- **After step 2 ran:** the data is a fresh v15 schema plus (optionally) fake demo rows. Dropping
  the stack as above removes it; a snapshot is kept.
- **Never** run `alembic downgrade` on the shared database without a manual cluster snapshot first.

Full background: `docs/infrastructure/central-dev-db-setup.md` and `infra/HANDOVER.md` in the zip.
Change list for this revision: `infra/deploy-dev/CHANGES-no-nat.md`.
