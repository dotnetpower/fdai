#!/usr/bin/env bash
# Verify the exact image, managed identity, Azure target, and runner services.
set -euo pipefail
set +x
ulimit -c 0

subscription_id=""
tenant_id=""
client_id=""
principal_id=""
source_commit=""
toolchain_digest=""
parallelism=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --subscription-id) subscription_id="$2"; shift 2 ;;
    --tenant-id) tenant_id="$2"; shift 2 ;;
    --client-id) client_id="$2"; shift 2 ;;
    --principal-id) principal_id="$2"; shift 2 ;;
    --source-commit) source_commit="$2"; shift 2 ;;
    --toolchain-digest) toolchain_digest="$2"; shift 2 ;;
    --parallelism) parallelism="$2"; shift 2 ;;
    *) echo "fdai-attest-runner: unsupported argument" >&2; exit 64 ;;
  esac
done

guid='^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$'
[[ "$subscription_id" =~ $guid && "$tenant_id" =~ $guid && "$client_id" =~ $guid && "$principal_id" =~ $guid ]] || {
  echo "fdai-attest-runner: Azure identity input is invalid" >&2
  exit 64
}
[[ "$source_commit" =~ ^[0-9a-f]{40}$ && "$toolchain_digest" =~ ^[0-9a-f]{64}$ ]] || {
  echo "fdai-attest-runner: provenance input is invalid" >&2
  exit 64
}
[[ "$parallelism" =~ ^[1-5]$ ]] || {
  echo "fdai-attest-runner: parallelism is invalid" >&2
  exit 64
}

test "$(jq -r .source_commit /etc/fdai-runner-image.json)" = "$source_commit"
test "$(jq -r .toolchain_digest /etc/fdai-runner-image.json)" = "$toolchain_digest"
test "$(az version --query '"azure-cli"' --output tsv)" = "$(jq -r .azure_cli_version /etc/fdai-runner-image.json)"
test "$(terraform version -json | jq -r .terraform_version)" = "$(jq -r .terraform_version /etc/fdai-runner-image.json)"
printf '%s  %s\n' "$(jq -r .terraform_binary_sha256 /etc/fdai-runner-image.json)" /usr/local/bin/terraform | sha256sum -c - >/dev/null
opa version | grep -F "Version: $(jq -r .opa_version /etc/fdai-runner-image.json)" >/dev/null

azure_config="$(mktemp -d)"
trap 'rm -rf -- "$azure_config"' EXIT
export AZURE_CONFIG_DIR="$azure_config"
az login --identity --client-id "$client_id" --allow-no-subscriptions --output none --only-show-errors
az account set --subscription "$subscription_id" --only-show-errors
read -r observed_subscription observed_tenant < <(
  az account show --query '[id,tenantId]' --output tsv --only-show-errors
)
[[ "${observed_subscription,,}" = "${subscription_id,,}" && "${observed_tenant,,}" = "${tenant_id,,}" ]]
observed_principal="$({
  az account get-access-token --resource https://management.azure.com/ \
    --query accessToken --output tsv --only-show-errors
} | python3 -c '
import base64
import json
import sys

token = sys.stdin.read().strip()
parts = token.split(".")
if len(parts) != 3:
    raise SystemExit(65)
payload = parts[1] + "=" * (-len(parts[1]) % 4)
claims = json.loads(base64.urlsafe_b64decode(payload))
principal = claims.get("oid")
if not isinstance(principal, str):
    raise SystemExit(65)
print(principal)
')"
[[ "${observed_principal,,}" = "${principal_id,,}" ]]

for slot in $(seq 1 "$parallelism"); do
  runner_home="$HOME/actions-runner"
  if [[ "$slot" != "1" ]]; then
    runner_home="${runner_home}-${slot}"
  fi
  test -f "$runner_home/.runner"
  (cd "$runner_home" && sudo -n ./svc.sh status >/dev/null 2>&1)
done

printf 'attestation_complete slots=%s\n' "$parallelism"
