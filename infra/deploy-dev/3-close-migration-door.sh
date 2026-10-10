#!/usr/bin/env bash
# Radial Pulse Central DEV: close the migration door (step 3 of 3).
#
# WHERE: normal AWS CloudShell, region ap-south-1 (no need for the code folder).
# WHAT:  1. deletes the temporary stack rp-central-migration-access-dev (Secrets Manager endpoint, billed per hour)
#        2. updates rp-central-db-dev with AllowMigrationAccess=false and the SAME other values,
#           so only the Lambda security group can reach the database on 5432
#        3. deletes the temporary code bucket from step 1
# After this, nothing in the account is billed per hour except Aurora when it is awake.
set -euo pipefail

REGION="ap-south-1"
DB_STACK="rp-central-db-dev"
ACCESS_STACK="rp-central-migration-access-dev"
EXPECTED_ACCOUNT="${EXPECTED_ACCOUNT:-243894881176}"

fail() { echo "ERROR: $*" >&2; exit 1; }
stack_status() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].StackStatus" --output text 2>/dev/null || echo "NONE"
}
param() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$DB_STACK" \
    --query "Stacks[0].Parameters[?ParameterKey=='$1'].ParameterValue" --output text
}

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
[[ "$ACCOUNT_ID" == "$EXPECTED_ACCOUNT" ]] || fail "signed in to account $ACCOUNT_ID, expected $EXPECTED_ACCOUNT."

# ---------------------------------------------------------------- 1. temporary endpoint stack
if [[ "$(stack_status "$ACCESS_STACK")" == "NONE" ]]; then
  echo "== $ACCESS_STACK: already gone."
else
  echo "== Deleting $ACCESS_STACK (the Secrets Manager endpoint; stops its hourly charge)"
  aws cloudformation delete-stack --region "$REGION" --stack-name "$ACCESS_STACK"
  aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$ACCESS_STACK"
  echo "   deleted."
fi

# ---------------------------------------------------------------- 2. close the door
CURRENT="$(param AllowMigrationAccess)"
echo "== Migration door is now: AllowMigrationAccess=$CURRENT"
if [[ "$CURRENT" == "false" ]]; then
  echo "   Already closed."
else
  # Keep every other parameter exactly as it is (UsePreviousValue).
  aws cloudformation update-stack --region "$REGION" --stack-name "$DB_STACK" \
    --use-previous-template --capabilities CAPABILITY_NAMED_IAM \
    --parameters \
      ParameterKey=VpcId,UsePreviousValue=true \
      ParameterKey=DbSubnetIds,UsePreviousValue=true \
      ParameterKey=EngineVersion,UsePreviousValue=true \
      ParameterKey=MinCapacity,UsePreviousValue=true \
      ParameterKey=MaxCapacity,UsePreviousValue=true \
      ParameterKey=MasterUsername,UsePreviousValue=true \
      ParameterKey=ExistingLambdaRoleName,UsePreviousValue=true \
      ParameterKey=AllowMigrationAccess,ParameterValue=false >/dev/null
  echo "   Updating... (a few minutes)"
  aws cloudformation wait stack-update-complete --region "$REGION" --stack-name "$DB_STACK"
  echo "   Migration door: AllowMigrationAccess=$(param AllowMigrationAccess)"
fi

# ---------------------------------------------------------------- 3. temporary code bucket
BUCKET="rp-central-deploy-dev-$ACCOUNT_ID"
if aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  aws s3 rm "s3://$BUCKET" --recursive --only-show-errors
  aws s3api delete-bucket --bucket "$BUCKET" --region "$REGION"
  echo "== Deleted the temporary code bucket $BUCKET."
fi
rm -rf "$HOME/rp-migrate" "$HOME/rp-migrate-toolkit.tar.gz" 2>/dev/null || true

echo
echo "Done. Hourly charges left: none from this setup (Aurora only while awake; KMS key 1 USD/month)."
echo "Send central-dev-outputs.txt (from step 1) and the 8 checks from step 2 to Person 1."
echo "The API Lambda is NOT in this VPC yet: see docs/infrastructure/central-dev-db-setup.md, section 'No NAT'."
