#!/usr/bin/env bash
# Set the GitHub Actions repo Variables + Secrets the deploy-dev workflow needs,
# reading the non-secret values from the applied infra/bootstrap outputs. The
# postgres password is generated here and piped via stdin so it never prints.
#
# Usage: ./scripts/deployment/azure/set-gh-actions-config.sh \
#   <owner>/<repo> <subscription_id> <tenant_id> [region] [region_short] [core_image]
set -euo pipefail

REPO="${1:?usage: set-gh-actions-config.sh <owner>/<repo> [sub_id] [tenant_id] [region] [region_short] [core_image]}"
SUB="${2:-${AZURE_SUBSCRIPTION_ID:-}}"
TENANT="${3:-${AZURE_TENANT_ID:-}}"
REGION="${4:-}"
REGION_SHORT="${5:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"
BS="$REPO_ROOT/infra/bootstrap"
SOURCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
IMAGE_REPOSITORY="${FDAI_IMAGE_REPOSITORY:-ghcr.io/${REPO,,}}"
CORE_IMAGE="${6:-${FDAI_CORE_IMAGE:-$IMAGE_REPOSITORY/fdai-core-control-plane:sha-$SOURCE_COMMIT}}"
DEV_APPROVALS="${FDAI_DEV_DEPLOY_REQUIRED_APPROVALS:-0}"

if [[ ! "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "repository must use owner/name format" >&2
  exit 2
fi
if [[ ! "$CORE_IMAGE" =~ ^[a-z0-9.-]+(:[0-9]+)?/[a-z0-9._/-]+(@sha256:[0-9a-f]{64}|:sha-[0-9a-f]{40})$ ]]; then
  echo "core image must be pinned by digest or a full source-revision tag" >&2
  exit 2
fi
if [[ "$DEV_APPROVALS" != "0" && "$DEV_APPROVALS" != "1" ]]; then
  echo "FDAI_DEV_DEPLOY_REQUIRED_APPROVALS must be 0 or 1" >&2
  exit 2
fi

/bin/bash "$HERE/verify-azure-context.sh" "$SUB" "$TENANT"

out() { terraform -chdir="$BS" output -raw "$1"; }

state_resource_group="$(out ops_resource_group_name)"
state_container="$(out state_container_name)"
app_resource_group="$(out app_resource_group_name)"
REGION="${REGION:-$(out region)}"
REGION_SHORT="${REGION_SHORT:-$(out region_short)}"
deploy_runner_principal_id="$(out deploy_runner_principal_id)"
[[ "$REGION" =~ ^[a-z0-9]+$ && "$REGION_SHORT" =~ ^[a-z0-9]{2,6}$ ]] || {
  echo "region and region_short must be lowercase Azure naming tokens" >&2
  exit 2
}
foundation_context="$({
  az group show --name "$app_resource_group" --subscription "$SUB" \
    --query 'tags."fdai:foundation-context"' --output tsv --only-show-errors
} 2>/dev/null || true)"
if [[ -n "$foundation_context" && ! "$foundation_context" =~ ^[0-9a-f]{64}$ ]]; then
  echo "application resource group has an invalid foundation context tag" >&2
  exit 1
fi

if command -v docker >/dev/null 2>&1; then
  docker manifest inspect "$CORE_IMAGE" >/dev/null 2>&1 || {
    echo "core image is unavailable: build it first or pass an accessible immutable image" >&2
    exit 1
  }
fi

echo "== repo Variables =="
gh variable set ARM_SUBSCRIPTION_ID     -R "$REPO" -b "$SUB"
gh variable set AZURE_TENANT_ID         -R "$REPO" -b "$TENANT"
gh variable set AZURE_REGION            -R "$REPO" -b "$REGION"
gh variable set AZURE_REGION_SHORT      -R "$REPO" -b "$REGION_SHORT"
gh variable set OPS_RESOURCE_GROUP_NAME -R "$REPO" -b "$state_resource_group"
gh variable set OPS_VNET_ID             -R "$REPO" -b "$(out ops_vnet_id)"
gh variable set OPS_VNET_NAME           -R "$REPO" -b "$(out ops_vnet_name)"
gh variable set STATE_STORAGE_ACCOUNT   -R "$REPO" -b "$(out state_storage_account_name)"
gh variable set STATE_RESOURCE_GROUP    -R "$REPO" -b "$state_resource_group"
gh variable set STATE_CONTAINER         -R "$REPO" -b "$state_container"
gh variable set DEPLOY_RUNNER_CLIENT_ID -R "$REPO" -b "$(out deploy_runner_client_id)"
gh variable set DEPLOY_RUNNER_PRINCIPAL_ID \
  -R "$REPO" -b "$deploy_runner_principal_id"
gh variable set MODEL_RESOLVER_DEPLOYER_OBJECT_ID -R "$REPO" -b "$deploy_runner_principal_id"
gh variable set CORE_IMAGE               -R "$REPO" -b "$CORE_IMAGE"
gh variable set DEV_DEPLOY_REQUIRED_APPROVALS -R "$REPO" -b "$DEV_APPROVALS"
if [[ -n "$foundation_context" ]]; then
  gh variable set FOUNDATION_RESOURCE_GROUP_CONTEXT_DIGEST \
    -R "$REPO" -b "$foundation_context"
else
  gh variable delete FOUNDATION_RESOURCE_GROUP_CONTEXT_DIGEST -R "$REPO" >/dev/null 2>&1 || true
fi

echo "== repo Secrets =="
printf 'fdaiadmin' | gh secret set POSTGRES_ADMIN_LOGIN -R "$REPO"
# Idempotent: only generate + set a password if one is not already configured,
# so re-running onboarding does not silently rotate the live postgres password
# (which would drift from state until the next apply).
if gh secret list -R "$REPO" --json name --jq '.[].name' | grep -qx POSTGRES_ADMIN_PASSWORD; then
  echo "POSTGRES_ADMIN_PASSWORD already set - leaving it (delete it first to rotate)."
else
  openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 24 | gh secret set POSTGRES_ADMIN_PASSWORD -R "$REPO"
fi

echo "done. Create a protected plan with fdaictl; apply only its returned plan id and digest."
