#!/usr/bin/env bash
# Select and verify the stable deploy UAMI before privileged workflow work.
set -euo pipefail

expected_subscription="${1:-}"
expected_tenant="${2:-}"
expected_client_id="${3:-}"
expected_principal_id="${4:-}"

guid_pattern='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
for coordinate in \
  "$expected_subscription" \
  "$expected_tenant" \
  "$expected_client_id" \
  "$expected_principal_id"; do
  if [[ ! "$coordinate" =~ $guid_pattern ]]; then
    echo "login-deploy-identity: subscription, tenant, client id, and principal id must be configured GUIDs." >&2
    exit 2
  fi
done

if [[ -z "${RUNNER_TEMP:-}" ]]; then
  echo "login-deploy-identity: RUNNER_TEMP is required." >&2
  exit 2
fi

for command_name in az base64 jq tr; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "login-deploy-identity: required command is unavailable: $command_name" >&2
    exit 2
  }
done

azure_config_dir="$RUNNER_TEMP/fdai-deploy-azure"
rm -rf -- "$azure_config_dir"
install -d -m 0700 "$azure_config_dir"
export AZURE_CONFIG_DIR="$azure_config_dir"
if [[ -n "${GITHUB_ENV:-}" ]]; then
  printf 'AZURE_CONFIG_DIR=%s\n' "$AZURE_CONFIG_DIR" >>"$GITHUB_ENV"
fi

az account clear >/dev/null 2>&1 || true
az login \
  --identity \
  --client-id "$expected_client_id" \
  --allow-no-subscriptions \
  --output none \
  --only-show-errors

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bash "$script_dir/verify-azure-context.sh" "$expected_subscription" "$expected_tenant"

access_token="$(az account get-access-token \
  --resource-type arm \
  --query accessToken \
  --output tsv \
  --only-show-errors)"
token_payload="${access_token#*.}"
token_payload="${token_payload%%.*}"
case "$((${#token_payload} % 4))" in
  0) ;;
  2) token_payload="${token_payload}==" ;;
  3) token_payload="${token_payload}=" ;;
  *)
    echo "login-deploy-identity: ARM token payload is invalid." >&2
    exit 1
    ;;
esac
active_principal_id="$(
  printf '%s' "$token_payload" |
    tr '_-' '/+' |
    base64 --decode 2>/dev/null |
    jq -er '.oid | select(type == "string")'
)" || {
  echo "login-deploy-identity: ARM token has no valid oid claim." >&2
  exit 1
}
unset access_token token_payload

if [[ "${active_principal_id,,}" != "${expected_principal_id,,}" ]]; then
  echo "login-deploy-identity: active token oid does not match the configured deploy principal." >&2
  exit 1
fi

echo "login-deploy-identity: exact deploy identity and Azure context verified."
