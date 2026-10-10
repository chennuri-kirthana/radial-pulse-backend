#!/usr/bin/env bash
# Radial Pulse Central DEV: create the tables and the backend's login (step 2 of 3). WORKS WITHOUT INTERNET.
#
# WHERE: AWS CloudShell **VPC environment** in the Radial Pulse VPC, app subnet rp-central-app-a-dev,
#        security group rp-central-migrate-sg-dev. Run from your home directory after:
#          aws s3 cp s3://rp-central-deploy-dev-<account id>/rp-migrate-toolkit.tar.gz . && tar -xzf rp-migrate-toolkit.tar.gz
#          bash radial-pulse-backend/infra/deploy-dev/2-migrate-and-create-login.sh
# WHAT:  1. reads the master password from Secrets Manager (through the temporary VPC endpoint) into THIS shell only
#        2. alembic upgrade head  -> schema v15 (all tables, rules, roles), using the toolkit built in step 1
#        3. infra/sql/create-app-login.sql -> login radial_api_iam (IAM auth, no password); 8 checks
#        4. optional, asks first: FAKE demo data (db/seed-family-dental-v15.sql + db/seed-demo-internal-v15.sql)
# The network has NO NAT gateway. This script downloads nothing and installs nothing: uv, Python 3.12
# and every dependency come from the toolkit (same OS, CPU and home directory as the normal CloudShell).
# The only network calls are: S3 (gateway endpoint), Secrets Manager (interface endpoint), the database.
set -euo pipefail

fail() { echo "ERROR: $*" >&2; exit 1; }

TOOLKIT_DIR="$HOME/rp-migrate"
ENV_FILE="$TOOLKIT_DIR/central-dev.env"
[[ -f "$ENV_FILE" ]] || fail "$ENV_FILE not found. From your home directory run:
  aws s3 cp s3://rp-central-deploy-dev-<account id>/rp-migrate-toolkit.tar.gz . && tar -xzf rp-migrate-toolkit.tar.gz"
# shellcheck source=/dev/null
source "$ENV_FILE"
REGION="$RP_REGION"
[[ "$RP_HOME" == "$HOME" ]] || fail "the toolkit was built for home directory $RP_HOME but this shell has $HOME; the Python inside would not start."
[[ "$(uname -m)" == "x86_64" ]] || fail "this environment is $(uname -m); the toolkit was built for x86_64."

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"
[[ -f alembic.ini && -f infra/sql/create-app-login.sql && -f scripts/db/run_sql.py ]] || fail "unexpected folder layout in $REPO_DIR"

export PATH="$TOOLKIT_DIR/bin:$PATH"
export UV_PYTHON_INSTALL_DIR="$TOOLKIT_DIR/python" UV_PROJECT_ENVIRONMENT="$TOOLKIT_DIR/venv"
export UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never
PY="$TOOLKIT_DIR/venv/bin/python"
[[ -x "$PY" ]] || fail "toolkit Python not found at $PY (was the tar extracted in $HOME?)"
"$PY" -c "import alembic, psycopg, sqlalchemy" || fail "toolkit is incomplete; run step 1 again."
echo "Toolkit OK: $("$PY" -V), uv $(uv --version | cut -d' ' -f2) (offline)."

echo "Database: $RP_DB_HOST:$RP_DB_PORT/$RP_DB_NAME   owner login: $RP_MASTER_USER"
echo "== Can we reach the database on $RP_DB_PORT?"
if ! timeout 10 bash -c "</dev/tcp/$RP_DB_HOST/$RP_DB_PORT" 2>/dev/null; then
  fail "cannot reach $RP_DB_HOST:$RP_DB_PORT. Check: this is a CloudShell VPC environment in $RP_VPC_ID,
  subnet $RP_APP_SUBNET_A, security group $RP_MIGRATE_SG, and step 1 finished with the migration door open.
  (A paused Aurora cluster takes about 15 s to wake up: try again.)"
fi
echo "Reachable."

echo "== Can we reach Secrets Manager through the VPC endpoint?"
SM_HOST="secretsmanager.$REGION.amazonaws.com"
SM_IP="$(getent ahostsv4 "$SM_HOST" | awk 'NR==1 {print $1}' || true)"
case "$SM_IP" in
  10.*) echo "$SM_HOST resolves to $SM_IP (inside the VPC: the endpoint from stack rp-central-migration-access-dev)." ;;
  "")   fail "$SM_HOST does not resolve. The stack rp-central-migration-access-dev is missing or not finished (step 1)." ;;
  *)    echo "WARNING: $SM_HOST resolves to $SM_IP, a public address. Without a NAT this call will hang. Is the endpoint stack there?" ;;
esac

echo "== Reading the master password into this shell only (never printed or saved)"
DB_PASSWORD="$(aws secretsmanager get-secret-value --region "$REGION" --secret-id "$RP_MASTER_SECRET_ARN" \
  --query SecretString --output text | "$PY" -c 'import json, sys; print(json.load(sys.stdin)["password"])')"
[[ -n "$DB_PASSWORD" ]] || fail "empty password from Secrets Manager."
export DB_PASSWORD
trap 'unset DB_PASSWORD' EXIT
# APP_ENV=local only skips the Cognito settings check at start-up; it does not change the migration.
export DB_HOST="$RP_DB_HOST" DB_PORT="$RP_DB_PORT" DB_NAME="$RP_DB_NAME" DB_USER="$RP_MASTER_USER" DB_SSLMODE=require APP_ENV=local

echo "== Migration (schema v15)"
uv run --offline --no-sync alembic upgrade head
CURRENT="$(uv run --offline --no-sync alembic current 2>/dev/null | tail -n 1)"
echo "alembic current: $CURRENT"
[[ "$CURRENT" == *"v15_baseline (head)"* ]] || fail "expected 'v15_baseline (head)'. Stopped."

echo "== Creating the backend login radial_api_iam"
uv run --offline --no-sync python scripts/db/run_sql.py infra/sql/create-app-login.sql
echo
echo "Check the table above: the 'ok' column must be t (True) on all 8 rows."

# ---------------------------------------------------------------- optional: FAKE demo data (DEV only)
echo
read -r -p "Load FAKE demo data for the DEV demo (5 sample clinics, no real people)? [y/N] " answer
if [[ "$answer" == "y" || "$answer" == "Y" ]]; then
  HAS_FAMILY="$(uv run --offline --no-sync python scripts/db/run_sql.py \
    --scalar "SELECT count(*) FROM clinics WHERE id = '00000000-0000-0000-0000-00000000cc01'")"
  if [[ "$HAS_FAMILY" == "0" ]]; then
    uv run --offline --no-sync python scripts/db/run_sql.py db/seed-family-dental-v15.sql >/dev/null
    echo "Loaded db/seed-family-dental-v15.sql"
  else
    echo "Family Dental sample already there (not loaded again)."
  fi
  uv run --offline --no-sync python scripts/db/run_sql.py db/seed-demo-internal-v15.sql >/dev/null
  echo "Loaded db/seed-demo-internal-v15.sql"
  echo "Demo ids: active 00000000-0000-0000-0000-00000000cc01 (full NAP), ...cc02 (no website/phone);"
  echo "          lead 00000000-0000-0000-0000-00000000cc04 and archived ...cc05 (both 404)."
fi
echo
echo "NEXT (step 3): close this VPC environment (its files are deleted with it), go back to the"
echo "normal CloudShell and run, from the radial-pulse-backend/ folder:"
echo "   bash infra/deploy-dev/3-close-migration-door.sh"
