#!/usr/bin/env bash
# One-shot onboarding for a private-everything tenant: create the state
# account, apply the ops/hub bootstrap, and print the GitHub Actions config +
# next steps. Idempotent - safe to re-run.
#
# Usage (from repo root or infra/bootstrap):
#   OPS_RG=rg-fdai-ops-krc REGION=koreacentral ./onboard.sh
#
# Requires: az (logged in to the target subscription), terraform, a
# bootstrap.tfvars filled in (see bootstrap.tfvars.example).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

OPS_RG="${OPS_RG:-rg-fdai-ops-krc}"
REGION="${REGION:-koreacentral}"

if [ ! -f bootstrap.tfvars ]; then
  echo "ERROR: bootstrap.tfvars not found. Copy bootstrap.tfvars.example and fill it." >&2
  exit 1
fi

echo "== 1/3 state storage account (control plane) =="
SA_LINE=$(OPS_RG="$OPS_RG" REGION="$REGION" ./create-state-account.sh | tail -1)
echo "$SA_LINE"
SA_NAME=$(echo "$SA_LINE" | sed -E 's/.*"([^"]+)".*/\1/')
grep -q "^state_storage_account_name" bootstrap.tfvars ||
  echo "state_storage_account_name = \"$SA_NAME\"" >> bootstrap.tfvars

echo "== 2/3 terraform apply (ops VNet + PE + runner VM + roles) =="
terraform init -input=false >/dev/null
terraform apply -input=false -auto-approve -var-file=bootstrap.tfvars

echo
echo "== 3/3 GitHub Actions config (feed these to set-gh-actions-config.sh) =="
terraform output -raw backend_config_hint
echo
echo "ops_vnet_id             = $(terraform output -raw ops_vnet_id)"
echo "ops_vnet_name           = $(terraform output -raw ops_vnet_name)"
echo "ops_resource_group_name = $(terraform output -raw ops_resource_group_name)"
echo "runner_principal_id     = $(terraform output -raw runner_principal_id)"
echo
echo "Next:"
echo "  1. ../../scripts/deployment/azure/set-gh-actions-config.sh   # sets repo Variables/Secrets"
echo "  2. ./register-runner.sh <owner>/<repo>      # registers the self-hosted runner"
echo "  3. gh workflow run deploy-dev.yml -f apply=true"
