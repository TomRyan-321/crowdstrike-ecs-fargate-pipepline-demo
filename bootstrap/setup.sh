#!/usr/bin/env bash
# One-time setup for the CrowdStrike Falcon ECS Fargate pipeline samples.
#
#   1. Deploys bootstrap.yaml (OIDC provider, deploy role, ECR, execution role, TF state bucket,
#      and the cluster, public network and scheduler role for the detection container demo)
#   2. Creates the two GitHub environments that gate access to the AWS role:
#        aws-main     - main branch only, runs without approval
#        aws-approval - any other branch, requires approval from REVIEWER
#   3. Stores the stack outputs as GitHub repository variables
#
# Requires: AWS CLI with admin credentials for the target account, an authenticated gh CLI with
# admin access to the repository, and jq.
#
# Usage: bootstrap/setup.sh [owner/repo]
set -euo pipefail

REPO="${1:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
AWS_REGION="${AWS_REGION:-us-west-2}"
STACK_NAME="${STACK_NAME:-ecs-fargate-demo-bootstrap}"
NAME_PREFIX="${NAME_PREFIX:-ecs-fargate-demo}"
FALCON_CLOUD="${FALCON_CLOUD:-us-1}"
# Comma-separated Falcon sensor grouping tags applied to every sample deployment
FALCON_SENSOR_TAGS="${FALCON_SENSOR_TAGS:-}"
REVIEWER="${REVIEWER:-$(gh api user --jq .login)}"
MAIN_ENV="aws-main"
APPROVAL_ENV="aws-approval"

OWNER="${REPO%%/*}"
NAME="${REPO##*/}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Target AWS account: $(aws sts get-caller-identity --query Account --output text) (${AWS_REGION})"
echo "==> Target repository:  ${REPO}"

# Only one GitHub OIDC provider can exist per account; reuse it if it is already there.
if aws iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[].Arn' --output text |
    grep -q 'token.actions.githubusercontent.com'; then
    CREATE_OIDC=false
else
    CREATE_OIDC=true
fi
# A provider created by an earlier run of this stack must stay managed by it.
if aws cloudformation describe-stack-resource --stack-name "$STACK_NAME" --logical-resource-id GitHubOIDCProvider \
    --region "$AWS_REGION" >/dev/null 2>&1; then
    CREATE_OIDC=true
fi

echo "==> Deploying CloudFormation stack ${STACK_NAME} (CreateOIDCProvider=${CREATE_OIDC})"
aws cloudformation deploy \
    --region "$AWS_REGION" \
    --stack-name "$STACK_NAME" \
    --template-file "${SCRIPT_DIR}/bootstrap.yaml" \
    --capabilities CAPABILITY_NAMED_IAM \
    --no-fail-on-empty-changeset \
    --parameter-overrides \
    GitHubOwner="$OWNER" \
    GitHubRepository="$NAME" \
    MainEnvironmentName="$MAIN_ENV" \
    ApprovalEnvironmentName="$APPROVAL_ENV" \
    NamePrefix="$NAME_PREFIX" \
    CreateOIDCProvider="$CREATE_OIDC"

output() {
    aws cloudformation describe-stacks --region "$AWS_REGION" --stack-name "$STACK_NAME" \
        --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

echo "==> Creating GitHub environment ${MAIN_ENV} (main branch only)"
gh api -X PUT "repos/${REPO}/environments/${MAIN_ENV}" --input - >/dev/null <<EOF
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
EOF
if ! gh api "repos/${REPO}/environments/${MAIN_ENV}/deployment-branch-policies" \
    --jq '.branch_policies[] | select(.type == "branch") | .name' | grep -qx main; then
    gh api -X POST "repos/${REPO}/environments/${MAIN_ENV}/deployment-branch-policies" \
        -f name=main -f type=branch >/dev/null
fi

echo "==> Creating GitHub environment ${APPROVAL_ENV} (required reviewer: ${REVIEWER})"
REVIEWER_ID="$(gh api "users/${REVIEWER}" --jq .id)"
gh api -X PUT "repos/${REPO}/environments/${APPROVAL_ENV}" --input - >/dev/null <<EOF
{"reviewers": [{"type": "User", "id": ${REVIEWER_ID}}], "prevent_self_review": false, "deployment_branch_policy": null}
EOF

echo "==> Requiring approval before workflows run for all outside contributors"
gh api -X PUT "repos/${REPO}/actions/permissions/fork-pr-contributor-approval" \
    -f approval_policy=all_external_contributors >/dev/null || echo "    (skipped: not supported for this repository)"

echo "==> Setting repository variables"
gh variable set AWS_REGION --repo "$REPO" --body "$AWS_REGION"
gh variable set AWS_ROLE_ARN --repo "$REPO" --body "$(output GitHubDeployRoleArn)"
gh variable set TASK_EXECUTION_ROLE_ARN --repo "$REPO" --body "$(output TaskExecutionRoleArn)"
gh variable set TF_STATE_BUCKET --repo "$REPO" --body "$(output TerraformStateBucketName)"
gh variable set NAME_PREFIX --repo "$REPO" --body "$NAME_PREFIX"
gh variable set ECS_CLUSTER --repo "$REPO" --body "$(output DemoClusterName)"
gh variable set DEMO_SUBNETS --repo "$REPO" --body "$(output DemoSubnetIds)"
gh variable set DEMO_SECURITY_GROUP --repo "$REPO" --body "$(output DemoSecurityGroupId)"
gh variable set SCHEDULER_ROLE_ARN --repo "$REPO" --body "$(output StopTaskSchedulerRoleArn)"
gh variable set FALCON_CLOUD --repo "$REPO" --body "$FALCON_CLOUD"
if [[ -n "$FALCON_SENSOR_TAGS" ]]; then
    gh variable set FALCON_SENSOR_TAGS --repo "$REPO" --body "$FALCON_SENSOR_TAGS"
fi

cat <<EOF

Done. Finally, store your CrowdStrike API credentials as repository secrets:

  gh secret set FALCON_CLIENT_ID     --repo ${REPO}
  gh secret set FALCON_CLIENT_SECRET --repo ${REPO}
  gh secret set FALCON_CID           --repo ${REPO}   # CID including checksum, e.g. 1234...ABCD-12
EOF
