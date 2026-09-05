#!/usr/bin/env bash
set -euo pipefail

environment_name="${1:?environment is required}"
request_id="${2:?request id is required}"
output_path="${3:?output path is required}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
: "${STATE_STORAGE_ACCOUNT:?STATE_STORAGE_ACCOUNT is required}"
: "${OPS_RESOURCE_GROUP_NAME:?OPS_RESOURCE_GROUP_NAME is required}"

request_coordinates="${request_id#plan-ocr-}"
request_coordinates="${request_coordinates#apply-ocr-}"
proposal_token="${request_coordinates%%-*}"
expected_policy_digest="${request_coordinates#*-}"
[[ "$proposal_token" =~ ^[0-9a-f]{32}$ \
  && "$expected_policy_digest" =~ ^[0-9a-f]{64}$ ]] || {
  echo "document OCR plan request coordinates are invalid" >&2
  exit 1
}
proposal_id="operator-$proposal_token"

az storage container create \
  --account-name "$STATE_STORAGE_ACCOUNT" \
  --name tfstate --auth-mode login --public-access off --only-show-errors \
  --output none
cp "$repo_root/infra/backend.azurerm.tf.example" "$repo_root/infra/backend.tf"
terraform -chdir="$repo_root/infra" init -input=false \
  -backend-config="resource_group_name=$OPS_RESOURCE_GROUP_NAME" \
  -backend-config="storage_account_name=$STATE_STORAGE_ACCOUNT" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=fdai-${environment_name}.tfstate"

vault_uri="$(terraform -chdir="$repo_root/infra" output -raw key_vault_uri)"
vault_name="$(VAULT_URI="$vault_uri" python3 - <<'PY'
import os
import re
from urllib.parse import urlparse

parsed = urlparse(os.environ["VAULT_URI"])
match = re.fullmatch(r"([a-z0-9-]{3,24})[.]vault[.]azure[.]net", parsed.hostname or "")
if parsed.scheme != "https" or match is None:
    raise SystemExit("Terraform key_vault_uri is not an Azure Key Vault HTTPS URI")
print(match.group(1))
PY
)"
migration_secret_name="$(
  jq -er '.services["core-control-plane"].migration_dsn_secret_name' \
    "$repo_root/scripts/deployment/service/service-matrix.json"
)"
migration_dsn="$(
  timeout 60s az keyvault secret show \
    --vault-name "$vault_name" --name "$migration_secret_name" \
    --query value --only-show-errors --output tsv
)"
[[ -n "$migration_dsn" ]] || {
  echo "document OCR proposal database is unavailable" >&2
  exit 1
}
echo "::add-mask::$migration_dsn"
export FDAI_DATABASE_URL="$migration_dsn"
PYTHONPATH="$repo_root/packages/service-contracts/src" \
  uv run --directory "$repo_root" --frozen --package fdai-core-control-plane python \
    scripts/deployment/azure/document_ocr_proposal.py \
    --from-database \
    --proposal-id "$proposal_id" \
    --environment "$environment_name" \
    --output "$output_path"
unset FDAI_DATABASE_URL migration_dsn

actual_policy_digest="$(jq -er '.policy_digest | sub("^sha256:"; "")' "$output_path")"
[[ "$actual_policy_digest" == "$expected_policy_digest" ]] || {
  echo "document OCR plan request does not match the proposal policy digest" >&2
  exit 1
}
if [[ -n "${GITHUB_ENV:-}" ]]; then
  printf 'DOCUMENT_OCR_ACTION=%s\n' "$(jq -er '.action' "$output_path")" >> "$GITHUB_ENV"
fi
