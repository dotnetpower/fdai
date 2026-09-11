#!/usr/bin/env bash
# One-shot onboarding for a private-everything tenant: create the state
# account, apply the ops/hub bootstrap, and print the GitHub Actions config +
# next steps. Idempotent - safe to re-run.
#
# Usage (from repo root or infra/bootstrap):
#   OPS_RG=rg-fdai-ops-krc REGION=koreacentral ./onboard.sh
#
# Requires: az, terraform, python3, explicit AZURE_SUBSCRIPTION_ID/AZURE_TENANT_ID,
# and a bootstrap.tfvars filled in (see bootstrap.tfvars.example).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

OPS_RG="${OPS_RG:-rg-fdai-ops-krc}"
REGION="${REGION:-koreacentral}"
EXPECTED_SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:?set AZURE_SUBSCRIPTION_ID}"
EXPECTED_TENANT="${AZURE_TENANT_ID:?set AZURE_TENANT_ID}"

if [[ ! -f bootstrap.tfvars || -L bootstrap.tfvars ]]; then
  echo "ERROR: bootstrap.tfvars must be a regular file. Copy bootstrap.tfvars.example and fill it." >&2
  exit 1
fi

/bin/bash "$HERE/../../scripts/deployment/azure/verify-azure-context.sh" \
  "$EXPECTED_SUBSCRIPTION" "$EXPECTED_TENANT"

echo "== 1/3 state storage account (control plane) =="
configured_state_account_name="$(python3 - <<'PY'
import re
from pathlib import Path

path = Path("bootstrap.tfvars")
matches = re.findall(
  r'^\s*state_storage_account_name\s*=\s*"([^"]*)"\s*(?:#.*)?$',
  path.read_text(encoding="utf-8"),
  flags=re.MULTILINE,
)
if len(matches) > 1:
  raise SystemExit("bootstrap.tfvars contains duplicate state_storage_account_name values")
if matches and re.fullmatch(r"[a-z0-9]{3,24}", matches[0]):
  print(matches[0])
PY
)"
if [[ -n "$configured_state_account_name" ]]; then
  SA_LINE=$(OPS_RG="$OPS_RG" REGION="$REGION" /bin/bash ./create-state-account.sh \
  "$configured_state_account_name" | tail -1)
else
  SA_LINE=$(OPS_RG="$OPS_RG" REGION="$REGION" /bin/bash ./create-state-account.sh | tail -1)
fi
echo "$SA_LINE"
SA_NAME=$(echo "$SA_LINE" | sed -E 's/.*"([^"]+)".*/\1/')
[[ "$SA_NAME" =~ ^[a-z0-9]{3,24}$ ]] || {
  echo "ERROR: state account helper returned an invalid name." >&2
  exit 1
}
STATE_ACCOUNT_NAME="$SA_NAME" python3 - <<'PY'
import os
import re
import tempfile
from pathlib import Path

path = Path("bootstrap.tfvars")
source = path.read_text(encoding="utf-8")
replacement = f'state_storage_account_name = "{os.environ["STATE_ACCOUNT_NAME"]}"'
updated, count = re.subn(
  r'^\s*state_storage_account_name\s*=.*$',
  replacement,
  source,
  count=1,
  flags=re.MULTILINE,
)
if count == 0:
  updated = source.rstrip("\n") + "\n" + replacement + "\n"
descriptor, temporary = tempfile.mkstemp(prefix=".bootstrap.tfvars.", dir=path.parent)
try:
  os.fchmod(descriptor, 0o600)
  with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
    stream.write(updated)
    stream.flush()
    os.fsync(stream.fileno())
  os.replace(temporary, path)
finally:
  if os.path.exists(temporary):
    os.unlink(temporary)
PY

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
echo "deploy_runner_client_id = $(terraform output -raw deploy_runner_client_id)"
echo "deploy_runner_principal_id = $(terraform output -raw deploy_runner_principal_id)"
echo
echo "Next:"
echo "  1. ../../scripts/deployment/azure/set-gh-actions-config.sh   # sets repo Variables/Secrets"
echo "  2. ./register-runner.sh <owner>/<repo>      # registers the self-hosted runner"
echo "  3. gh workflow run deploy-dev.yml -f apply=true"
