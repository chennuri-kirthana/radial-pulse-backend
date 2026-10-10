#!/usr/bin/env bash
# Radial Pulse Central DEV: create the network and the Aurora database (step 1 of 3). NO NAT GATEWAY.
#
# WHERE: AWS CloudShell (normal, not VPC mode), region ap-south-1, from the unzipped
#        radial-pulse-backend/ folder in your home directory. CloudShell uses your console login.
# WHAT:  0. checks the account, the templates and that nothing Radial Pulse exists already
#        1. network stack rp-central-network-dev: VPC 10.40.0.0/16, 2 AZs, NO NAT, S3 endpoint
#        2. database stack rp-central-db-dev: Aurora PostgreSQL 16, private, encrypted, door OPEN for step 2
#        3. temporary stack rp-central-migration-access-dev: Secrets Manager endpoint for step 2 (step 3 deletes it)
#        4. termination protection on the network and database stacks; prints the outputs (no passwords)
#        5. builds the OFFLINE migration toolkit (uv + Python 3.12 + locked dependencies) and copies it
#           to a private S3 bucket: the VPC environment of step 2 has no internet and cannot download anything
# HOW:   every stack change is a CloudFormation CHANGE SET that is shown and confirmed before it runs.
# COST:  no NAT gateway, no Elastic IP. Aurora pauses when idle. The interface endpoint costs about
#        0.013 USD/hour until step 3 deletes it. KMS key 1 USD/month.
# Never prints or saves a password. Never touches the Lambda function or API Gateway.
set -euo pipefail

REGION="ap-south-1"
NET_STACK="rp-central-network-dev"
DB_STACK="rp-central-db-dev"
ACCESS_STACK="rp-central-migration-access-dev"
VPC_CIDR="10.40.0.0/16"
EXPECTED_ACCOUNT="${EXPECTED_ACCOUNT:-243894881176}"   # Central DEV. Override only on purpose.
LAMBDA_ROLE="${LAMBDA_ROLE:-rp-central-lambda-execution-dev}"
UV_VERSION="${UV_VERSION:-0.12.24}"                    # the uv release used to build and test this toolkit
TAGS=(Project=RadialPulse Team=Central Environment=dev)
TOOLKIT_DIR="$HOME/rp-migrate"
TOOLKIT_TAR="$HOME/rp-migrate-toolkit.tar.gz"
OUT_FILE="central-dev-outputs.txt"

ask() { read -r -p "$1 [y/N] " answer; [[ "$answer" == "y" || "$answer" == "Y" ]]; }
fail() { echo "ERROR: $*" >&2; exit 1; }
stack_status() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].StackStatus" --output text 2>/dev/null || echo "NONE"
}
output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}
# deploy_stack NAME TEMPLATE [more `aws cloudformation deploy` arguments]
# Creates a change set, shows it, asks, executes it. Never runs a change set unseen.
deploy_stack() {
  local name="$1" template="$2"; shift 2
  local out arn before
  before="$(stack_status "$name")"   # NONE = this change set CREATES the stack
  out="$(aws cloudformation deploy --region "$REGION" --stack-name "$name" --template-file "$template" \
      --no-execute-changeset --no-fail-on-empty-changeset --tags "${TAGS[@]}" "$@" 2>&1)" || {
    echo "$out"; fail "could not create a change set for $name"; }
  arn="$(grep -o 'arn:aws:cloudformation:[^ "]*changeSet/[^ "]*' <<<"$out" | head -n 1 || true)"
  if [[ -z "$arn" ]]; then
    echo "   $name: no changes."; return 0
  fi
  echo "   Change set for $name:"
  aws cloudformation describe-change-set --region "$REGION" --change-set-name "$arn" \
    --query "Changes[].ResourceChange.[Action,ResourceType,LogicalResourceId,Replacement]" --output table
  local removes
  removes="$(aws cloudformation describe-change-set --region "$REGION" --change-set-name "$arn" \
    --query "length(Changes[?ResourceChange.Action=='Remove' || ResourceChange.Replacement=='True'])" --output text)"
  if [[ "$removes" != "0" ]]; then
    echo "   WARNING: this change set REMOVES or REPLACES $removes resource(s). Read it carefully."
  fi
  # Declining (or the NAT guard) must leave nothing behind: delete the change set, and for a
  # CREATE also the empty REVIEW_IN_PROGRESS stack that `deploy` made for it.
  discard() {
    aws cloudformation delete-change-set --region "$REGION" --change-set-name "$arn"
    if [[ "$before" == "NONE" ]]; then
      aws cloudformation delete-stack --region "$REGION" --stack-name "$name"
    fi
  }
  if aws cloudformation describe-change-set --region "$REGION" --change-set-name "$arn" \
      --query "Changes[].ResourceChange.ResourceType" --output text | grep -q "AWS::EC2::NatGateway"; then
    discard; fail "the change set would create a NAT gateway. Stopped and deleted it."
  fi
  if ! ask "Execute this change set for $name?"; then
    discard; fail "stopped; the change set was deleted and nothing was changed."
  fi
  aws cloudformation execute-change-set --region "$REGION" --change-set-name "$arn"
  echo "   Waiting for $name ..."
  if [[ "$before" == "NONE" ]]; then
    aws cloudformation wait stack-create-complete --region "$REGION" --stack-name "$name"
  else
    aws cloudformation wait stack-update-complete --region "$REGION" --stack-name "$name"
  fi
  echo "   $name: $(stack_status "$name")"
}

# ---------------------------------------------------------------- 0. checks
[[ -f infra/cloudformation/central-db-dev.yaml && -f pyproject.toml && -f uv.lock ]] \
  || fail "run this from the radial-pulse-backend/ folder."
NET_TEMPLATE="infra/cloudformation/central-network-dev.yaml"
DB_TEMPLATE="infra/cloudformation/central-db-dev.yaml"
ACCESS_TEMPLATE="infra/cloudformation/central-migration-access-dev.yaml"
# Belt and braces: this release must never create a NAT gateway or an Elastic IP.
if grep -q -E "AWS::EC2::(NatGateway|EIP)" "$NET_TEMPLATE" "$DB_TEMPLATE" "$ACCESS_TEMPLATE"; then
  fail "a template contains a NAT gateway or Elastic IP resource. This is the no-NAT release; wrong file?"
fi
[[ "$(uname -m)" == "x86_64" ]] || fail "this CloudShell is $(uname -m); the toolkit must be built on x86_64 (same as the VPC environment)."

echo "== Who am I"
aws sts get-caller-identity --output table
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
[[ "$ACCOUNT_ID" == "$EXPECTED_ACCOUNT" ]] \
  || fail "signed in to account $ACCOUNT_ID, expected Central DEV $EXPECTED_ACCOUNT (set EXPECTED_ACCOUNT=... only on purpose)."
ask "Is this the Central DEV account, region $REGION?" || fail "stopped."

echo "== Checking the templates"
for t in "$NET_TEMPLATE" "$DB_TEMPLATE" "$ACCESS_TEMPLATE"; do
  aws cloudformation validate-template --region "$REGION" --template-body "file://$t" >/dev/null
done
echo "Templates OK."

echo "== Existing stacks (any state)"
for s in "$NET_STACK" "$DB_STACK" "$ACCESS_STACK"; do
  st="$(stack_status "$s")"; echo "   $s: $st"
  case "$st" in
    ROLLBACK_COMPLETE|ROLLBACK_FAILED|*_FAILED|REVIEW_IN_PROGRESS)
      fail "$s is in state $st. Delete it (CloudFormation console) and run again." ;;
  esac
done

echo "== Existing VPCs in $REGION"
aws ec2 describe-vpcs --region "$REGION" \
  --query "Vpcs[].[VpcId,CidrBlock,IsDefault,Tags[?Key=='Name']|[0].Value]" --output table
if [[ "$(stack_status "$NET_STACK")" == "NONE" ]]; then
  CLASH="$(aws ec2 describe-vpcs --region "$REGION" --filters "Name=cidr,Values=$VPC_CIDR" --query "Vpcs[].VpcId" --output text)"
  [[ -z "$CLASH" ]] || fail "a VPC with CIDR $VPC_CIDR already exists ($CLASH) but not from stack $NET_STACK. Not creating a second one."
  NAMED="$(aws ec2 describe-vpcs --region "$REGION" --filters "Name=tag:Name,Values=rp-central-vpc-dev" --query "Vpcs[].VpcId" --output text)"
  [[ -z "$NAMED" ]] || fail "a VPC named rp-central-vpc-dev already exists ($NAMED) outside stack $NET_STACK."
fi
echo "   The default VPC (172.31.0.0/16) is NOT used by Radial Pulse."

# ---------------------------------------------------------------- 1. network
if [[ "$(stack_status "$NET_STACK")" == "NONE" ]]; then
  echo "== Network stack $NET_STACK does not exist yet."
  echo "   It creates: VPC $VPC_CIDR, public/app/db subnets in 2 AZs, internet gateway (unused), S3 gateway endpoint."
  echo "   It creates NO NAT gateway and NO Elastic IP: the app and db subnets have no route to the internet."
  deploy_stack "$NET_STACK" "$NET_TEMPLATE" --parameter-overrides "VpcCidr=$VPC_CIDR"
else
  echo "== Network stack already exists: $(stack_status "$NET_STACK") (not changed)."
fi
VPC_ID="$(output "$NET_STACK" VpcId)"
DB_SUBNETS="$(output "$NET_STACK" DbSubnetIds)"
APP_SUBNETS="$(output "$NET_STACK" AppSubnetIds)"
APP_SUBNET_A="${APP_SUBNETS%%,*}"
echo "VPC: $VPC_ID   DB subnets: $DB_SUBNETS   App subnets: $APP_SUBNETS"
# The app route table must have no internet route (the whole point of this release).
if aws ec2 describe-route-tables --region "$REGION" --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Name,Values=rp-central-rt-app-dev" \
     --query "RouteTables[].Routes[?DestinationCidrBlock=='0.0.0.0/0']" --output text | grep -q .; then
  fail "the app route table has a 0.0.0.0/0 route. This network is not the no-NAT layout; stopped."
fi
echo "   App route table: no internet route (OK)."

# ---------------------------------------------------------------- 2. database
echo "== Aurora PostgreSQL 16 versions in $REGION:"
VERSIONS="$(aws rds describe-db-engine-versions --engine aurora-postgresql --region "$REGION" \
  --query "DBEngineVersions[?starts_with(EngineVersion,'16.')].EngineVersion" --output text)"
echo "$VERSIONS"
LATEST="$(tr '\t ' '\n' <<<"$VERSIONS" | sort -V | tail -n 1)"
read -r -p "Engine version to use (16.3 or newer) [$LATEST]: " ENGINE_VERSION
ENGINE_VERSION="${ENGINE_VERSION:-$LATEST}"

ROLE_PARAM="ExistingLambdaRoleName=$LAMBDA_ROLE"
if aws iam get-role --role-name "$LAMBDA_ROLE" >/dev/null 2>&1; then
  echo "Lambda role $LAMBDA_ROLE exists: the stack will only ATTACH one policy to it."
else
  echo "Lambda role $LAMBDA_ROLE was NOT found."
  if ask "Let the stack create its own role (rp-central-api-lambda-role-dev) instead?"; then
    ROLE_PARAM="ExistingLambdaRoleName="
  else
    fail "stopped. Create the role first, or run again with LAMBDA_ROLE=<name>."
  fi
fi

echo "== Database stack $DB_STACK: current status $(stack_status "$DB_STACK")"
echo "   Aurora Serverless v2 (0-2 ACU), engine $ENGINE_VERSION, VPC $VPC_ID, private DB subnets."
echo "   The migration door (AllowMigrationAccess) will be OPEN for step 2. Step 3 closes it."
echo "   Creating takes about 10-15 minutes."
deploy_stack "$DB_STACK" "$DB_TEMPLATE" --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides VpcId="$VPC_ID" DbSubnetIds="$DB_SUBNETS" \
      EngineVersion="$ENGINE_VERSION" AllowMigrationAccess=true "$ROLE_PARAM"
MIGRATE_SG="$(output "$DB_STACK" MigrateSecurityGroupId)"

# ---------------------------------------------------------------- 3. temporary migration access
echo "== Temporary stack $ACCESS_STACK (Secrets Manager endpoint for the migration runner, ~0.013 USD/hour)"
deploy_stack "$ACCESS_STACK" "$ACCESS_TEMPLATE" \
  --parameter-overrides VpcId="$VPC_ID" EndpointSubnetId="$APP_SUBNET_A" MigrateSecurityGroupId="$MIGRATE_SG"

echo "== Termination protection on the network and database stacks"
aws cloudformation update-termination-protection --region "$REGION" --stack-name "$NET_STACK" --enable-termination-protection >/dev/null
aws cloudformation update-termination-protection --region "$REGION" --stack-name "$DB_STACK" --enable-termination-protection >/dev/null

# ---------------------------------------------------------------- 4. outputs
{
  echo "# Central DEV stack outputs ($(date -u +%FT%TZ)). IDs and ARNs only, no passwords."
  for s in "$NET_STACK" "$DB_STACK" "$ACCESS_STACK"; do
    echo "## $s"
    aws cloudformation describe-stacks --region "$REGION" --stack-name "$s" \
      --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" --output text
  done
} | tee "$OUT_FILE"

# ---------------------------------------------------------------- 5. offline migration toolkit
# The VPC environment (step 2) has no internet: no uv, no PyPI, no dnf. So everything it needs is
# built HERE (same OS and CPU: Amazon Linux 2023, x86_64, same home directory) and copied through S3,
# which the app subnets reach through the free gateway endpoint.
BUCKET="rp-central-deploy-dev-$ACCOUNT_ID"
echo "== Building the offline migration toolkit in $TOOLKIT_DIR (a few minutes)"
rm -rf "$TOOLKIT_DIR" "$TOOLKIT_TAR"
mkdir -p "$TOOLKIT_DIR"
# Values step 2 needs. The VPC environment has no CloudFormation or STS endpoint, so it reads this file.
cat > "$TOOLKIT_DIR/central-dev.env" <<EOF
# Written by 1-deploy-network-and-db.sh on $(date -u +%FT%TZ). IDs and hostnames only, no secrets.
RP_REGION=$REGION
RP_HOME=$HOME
RP_DB_HOST=$(output "$DB_STACK" DbEndpoint)
RP_DB_PORT=$(output "$DB_STACK" DbPort)
RP_DB_NAME=$(output "$DB_STACK" DbName)
RP_MASTER_USER=$(output "$DB_STACK" MasterUsername)
RP_MASTER_SECRET_ARN=$(output "$DB_STACK" MasterSecretArn)
RP_VPC_ID=$VPC_ID
RP_APP_SUBNET_A=$APP_SUBNET_A
RP_MIGRATE_SG=$MIGRATE_SG
RP_BUCKET=$BUCKET
EOF
bash infra/deploy-dev/build-migration-toolkit.sh "$TOOLKIT_DIR" "$TOOLKIT_TAR" "$UV_VERSION"

echo "== Copying the toolkit to the private bucket s3://$BUCKET (step 3 deletes it)"
if ! aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi
aws s3 cp "$TOOLKIT_TAR" "s3://$BUCKET/rp-migrate-toolkit.tar.gz" --only-show-errors
aws s3 cp "$OUT_FILE" "s3://$BUCKET/$OUT_FILE" --only-show-errors
rm -rf "$TOOLKIT_DIR" "$TOOLKIT_TAR"   # CloudShell home is small; the copy in S3 is what step 2 uses

echo
echo "Done. Outputs saved to $OUT_FILE (safe to send to Person 1: ARNs and IDs only)."
echo
echo "NEXT (step 2): CloudShell > the + icon > Create VPC environment:"
echo "   VPC:            $VPC_ID"
echo "   Subnet:         $APP_SUBNET_A (rp-central-app-a-dev; the SAME subnet as the Secrets Manager endpoint)"
echo "   Security group: $MIGRATE_SG (rp-central-migrate-sg-dev)"
echo "Then, in that VPC environment (it has NO internet; only S3 and the database are reachable):"
echo "   aws s3 cp s3://$BUCKET/rp-migrate-toolkit.tar.gz . && tar -xzf rp-migrate-toolkit.tar.gz"
echo "   bash radial-pulse-backend/infra/deploy-dev/2-migrate-and-create-login.sh"
