#!/usr/bin/env bash
# READ-ONLY snapshot of the Radial Pulse Central DEV deployment. Changes nothing.
#
# WHERE: normal AWS CloudShell in account 243894881176, region ap-south-1. Then share the output
#        file. It holds IDs, ARNs, names and settings; it prints NO secret values (env var values
#        whose names contain SECRET/PASSWORD/TOKEN/KEY are masked) and never reads Secrets Manager.
#   bash infra/deploy-dev/inspect-central-dev.sh > central-dev-inspect.txt 2>&1
set -uo pipefail
R=ap-south-1
FN=rp-central-api-dev
API=h7uy2my2f5
POOL=ap-south-1_0BlsS6OwM
CLIENT=4ic2pjdot2du6bh5srjma0n9cm
sec() { echo; echo "===== $*"; }

sec "who"; aws sts get-caller-identity --output table
sec "lambda configuration"
aws lambda get-function-configuration --region $R --function-name $FN \
  --query "{Runtime:Runtime,Handler:Handler,Arch:Architectures,CodeSha256:CodeSha256,CodeSize:CodeSize,Memory:MemorySize,Timeout:Timeout,Role:Role,LastModified:LastModified,State:State,Vpc:VpcConfig,Layers:Layers[].Arn,Concurrency:ReservedConcurrentExecutions}" --output json
sec "lambda environment variable NAMES and non-secret values"
aws lambda get-function-configuration --region $R --function-name $FN --query "Environment.Variables" --output json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin) or {}; [print(f"  {k} = {\"<masked>\" if any(s in k for s in (\"SECRET\",\"PASSWORD\",\"TOKEN\",\"KEY\")) else v}") for k,v in sorted(d.items())]'
sec "lambda resource policy (who may invoke)"; aws lambda get-policy --region $R --function-name $FN --query Policy --output text | python3 -m json.tool
sec "lambda reserved concurrency"; aws lambda get-function-concurrency --region $R --function-name $FN --output json
sec "execution role policies"
ROLE=$(aws lambda get-function-configuration --region $R --function-name $FN --query Role --output text | awk -F/ '{print $NF}')
aws iam list-attached-role-policies --role-name "$ROLE" --output table
aws iam list-role-policies --role-name "$ROLE" --output table
for P in $(aws iam list-attached-role-policies --role-name "$ROLE" --query "AttachedPolicies[].PolicyArn" --output text); do
  echo "--- $P"; V=$(aws iam get-policy --policy-arn "$P" --query Policy.DefaultVersionId --output text)
  aws iam get-policy-version --policy-arn "$P" --version-id "$V" --query PolicyVersion.Document --output json
done
for P in $(aws iam list-role-policies --role-name "$ROLE" --query "PolicyNames[]" --output text); do
  echo "--- inline $P"; aws iam get-role-policy --role-name "$ROLE" --policy-name "$P" --query PolicyDocument --output json
done
sec "HTTP API"; aws apigatewayv2 get-api --region $R --api-id $API --query "{Name:Name,Protocol:ProtocolType,Endpoint:ApiEndpoint,Cors:CorsConfiguration}" --output json
aws apigatewayv2 get-stages --region $R --api-id $API --query "Items[].{Stage:StageName,AutoDeploy:AutoDeploy,Logs:AccessLogSettings}" --output json
aws apigatewayv2 get-routes --region $R --api-id $API --query "Items[].{Route:RouteKey,Auth:AuthorizationType,Authorizer:AuthorizerId,Target:Target}" --output table
aws apigatewayv2 get-integrations --region $R --api-id $API --query "Items[].{Id:IntegrationId,Type:IntegrationType,Uri:IntegrationUri,Payload:PayloadFormatVersion,Timeout:TimeoutInMillis}" --output table
aws apigatewayv2 get-authorizers --region $R --api-id $API --query "Items[].{Id:AuthorizerId,Name:Name,Type:AuthorizerType,Source:IdentitySource,Jwt:JwtConfiguration}" --output json
sec "REST APIs (internal API, if any)"; aws apigateway get-rest-apis --region $R --query "items[].{id:id,name:name,endpoint:endpointConfiguration.types}" --output table
sec "Cognito"
aws cognito-idp describe-user-pool --region $R --user-pool-id $POOL --query "UserPool.{Name:Name,Domain:Domain,CustomDomain:CustomDomain,UsernameAttributes:UsernameAttributes,CaseSensitive:UsernameConfiguration,AdminOnly:AdminCreateUserConfig.AllowAdminCreateUserOnly,Users:EstimatedNumberOfUsers}" --output json
aws cognito-idp describe-user-pool-client --region $R --user-pool-id $POOL --client-id $CLIENT --query "UserPoolClient.{Name:ClientName,Flows:AllowedOAuthFlows,Scopes:AllowedOAuthScopes,Callbacks:CallbackURLs,Logout:LogoutURLs,AuthFlows:ExplicitAuthFlows,Idps:SupportedIdentityProviders,HasSecret:ClientSecret!=null}" --output json
sec "stacks"; aws cloudformation describe-stacks --region $R --query "Stacks[].{Name:StackName,Status:StackStatus,Protected:EnableTerminationProtection,Updated:LastUpdatedTime}" --output table
for S in rp-central-network-dev rp-central-db-dev rp-central-migration-access-dev rp-central-jwks-sync-dev; do
  echo "--- $S outputs"; aws cloudformation describe-stacks --region $R --stack-name "$S" --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" --output text 2>&1 | head -40
  echo "--- $S parameters"; aws cloudformation describe-stacks --region $R --stack-name "$S" --query "Stacks[0].Parameters[].[ParameterKey,ParameterValue]" --output text 2>&1 | head -20
done
sec "Aurora"
aws rds describe-db-clusters --region $R --db-cluster-identifier rp-central-db-dev --query "DBClusters[0].{Status:Status,Engine:EngineVersion,Endpoint:Endpoint,Port:Port,Db:DatabaseName,Master:MasterUsername,IamAuth:IAMDatabaseAuthenticationEnabled,Encrypted:StorageEncrypted,DeleteProtect:DeletionProtection,Scaling:ServerlessV2ScalingConfiguration,ParamGroup:DBClusterParameterGroup,Sgs:VpcSecurityGroups[].VpcSecurityGroupId,SubnetGroup:DBSubnetGroup}" --output json
aws rds describe-db-instances --region $R --filters Name=db-cluster-id,Values=rp-central-db-dev --query "DBInstances[].{Id:DBInstanceIdentifier,Status:DBInstanceStatus,Class:DBInstanceClass,Public:PubliclyAccessible,AZ:AvailabilityZone}" --output table
aws rds describe-db-cluster-parameters --region $R --db-cluster-parameter-group-name rp-central-db-params-dev --query "Parameters[?ParameterName=='rds.force_ssl'].[ParameterName,ParameterValue]" --output text
sec "network"
VPC=$(aws cloudformation describe-stacks --region $R --stack-name rp-central-network-dev --query "Stacks[0].Outputs[?OutputKey=='VpcId'].OutputValue" --output text)
echo "VPC=$VPC"
aws ec2 describe-vpcs --region $R --query "Vpcs[].{Id:VpcId,Cidr:CidrBlock,Default:IsDefault,Name:Tags[?Key=='Name']|[0].Value}" --output table
aws ec2 describe-subnets --region $R --filters Name=vpc-id,Values="$VPC" --query "Subnets[].{Id:SubnetId,Name:Tags[?Key=='Name']|[0].Value,Cidr:CidrBlock,AZ:AvailabilityZone,PublicIp:MapPublicIpOnLaunch}" --output table
aws ec2 describe-route-tables --region $R --filters Name=vpc-id,Values="$VPC" --query "RouteTables[].{Id:RouteTableId,Name:Tags[?Key=='Name']|[0].Value,Subnets:Associations[].SubnetId,Routes:Routes[].[DestinationCidrBlock,DestinationPrefixListId,GatewayId,NatGatewayId,State]}" --output json
aws ec2 describe-nat-gateways --region $R --query "NatGateways[].{Id:NatGatewayId,State:State,Vpc:VpcId}" --output table
aws ec2 describe-vpc-endpoints --region $R --filters Name=vpc-id,Values="$VPC" --query "VpcEndpoints[].{Id:VpcEndpointId,Service:ServiceName,Type:VpcEndpointType,State:State,PrivateDns:PrivateDnsEnabled,Subnets:SubnetIds}" --output json
aws ec2 describe-security-groups --region $R --filters Name=vpc-id,Values="$VPC" --query "SecurityGroups[].{Id:GroupId,Name:GroupName,In:IpPermissions[].[FromPort,ToPort,UserIdGroupPairs[].GroupId,IpRanges[].CidrIp],Out:IpPermissionsEgress[].[IpProtocol,FromPort,ToPort,UserIdGroupPairs[].GroupId,IpRanges[].CidrIp]}" --output json
sec "logs: last 50 lines with status >= 500 or errors (no bodies/tokens are logged by the app)"
aws logs filter-log-events --region $R --log-group-name /aws/lambda/$FN --start-time $(( ($(date +%s) - 7*86400) * 1000 )) \
  --filter-pattern '?"\"status\": 5" ?error ?Error ?Traceback' --limit 50 --query "events[].message" --output text 2>&1 | cut -c1-400 | tail -50
sec "done"
