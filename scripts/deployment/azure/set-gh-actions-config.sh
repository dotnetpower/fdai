#!/usr/bin/env bash
# Set the GitHub Actions repo Variables + Secrets the deploy-dev workflow needs,
# reading the non-secret values from the applied infra/bootstrap outputs. The
# postgres password is generated here and piped via stdin so it never prints.
#
# Usage:  ./scripts/deployment/azure/set-gh-actions-config.sh <owner>/<repo> [subscription_id] [tenant_id] [region] [region_short]
set -euo pipefail

REPO="${1:?usage: set-gh-actions-config.sh <owner>/<repo> [sub_id] [tenant_id] [region] [region_short]}"
SUB="${2:-$(az account show --query id -o tsv)}"
TENANT="${3:-$(az account show --query tenantId -o tsv)}"
REGION="${4:-koreacentral}"
REGION_SHORT="${5:-krc}"

BS="infra/bootstrap"
out() { terraform -chdir="$BS" output -raw "$1"; }

echo "== repo Variables =="
gh variable set ARM_SUBSCRIPTION_ID     -R "$REPO" -b "$SUB"
gh variable set AZURE_TENANT_ID         -R "$REPO" -b "$TENANT"
gh variable set AZURE_REGION            -R "$REPO" -b "$REGION"
gh variable set AZURE_REGION_SHORT      -R "$REPO" -b "$REGION_SHORT"
gh variable set OPS_RESOURCE_GROUP_NAME -R "$REPO" -b "$(out ops_resource_group_name)"
gh variable set OPS_VNET_ID             -R "$REPO" -b "$(out ops_vnet_id)"
gh variable set OPS_VNET_NAME           -R "$REPO" -b "$(out ops_vnet_name)"
gh variable set STATE_STORAGE_ACCOUNT   -R "$REPO" -b "$(out state_storage_account_name)"

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

echo "done. A subsequent 'gh workflow run deploy-dev.yml -f apply=true' rotates"
echo "postgres to the new secret value on its first apply."
