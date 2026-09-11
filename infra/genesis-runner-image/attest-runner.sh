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
transport=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --subscription-id) subscription_id="$2"; shift 2 ;;
    --tenant-id) tenant_id="$2"; shift 2 ;;
    --client-id) client_id="$2"; shift 2 ;;
    --principal-id) principal_id="$2"; shift 2 ;;
    --source-commit) source_commit="$2"; shift 2 ;;
    --toolchain-digest) toolchain_digest="$2"; shift 2 ;;
    --parallelism) parallelism="$2"; shift 2 ;;
    --transport) transport="$2"; shift 2 ;;
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
[[ "$transport" == "manual" || "$transport" == "github-actions" ]] || {
  echo "fdai-attest-runner: transport is invalid" >&2
  exit 64
}

test "$(/usr/bin/jq -r .source_commit /etc/fdai-runner-image.json)" = "$source_commit"
test "$(/usr/bin/jq -r .toolchain_digest /etc/fdai-runner-image.json)" = "$toolchain_digest"
test "$(/usr/bin/az version --query '"azure-cli"' --output tsv)" = "$(/usr/bin/jq -r .azure_cli_version /etc/fdai-runner-image.json)"
test "$(/usr/local/bin/terraform version -json | /usr/bin/jq -r .terraform_version)" = "$(/usr/bin/jq -r .terraform_version /etc/fdai-runner-image.json)"
printf '%s  %s\n' "$(/usr/bin/jq -r .terraform_binary_sha256 /etc/fdai-runner-image.json)" /usr/local/bin/terraform | /usr/bin/sha256sum -c - >/dev/null
/usr/local/bin/opa version | /usr/bin/grep -F "Version: $(/usr/bin/jq -r .opa_version /etc/fdai-runner-image.json)" >/dev/null
test "$(/usr/bin/jq -r .execution_transport /etc/fdai-runner-image.json)" = "$transport"
printf '%s  %s\n' "$(/usr/bin/jq -r .oras_binary_sha256 /etc/fdai-runner-image.json)" /usr/local/bin/oras | /usr/bin/sha256sum -c - >/dev/null

azure_config="$(/usr/bin/mktemp -d)"
trap '/usr/bin/rm -rf -- "$azure_config"' EXIT
export AZURE_CONFIG_DIR="$azure_config"
/usr/bin/az login --identity --client-id "$client_id" --allow-no-subscriptions --output none --only-show-errors
mapfile -t observed_account < <(
  /usr/bin/az account show --subscription "$subscription_id" \
    --query '[id,tenantId]' --output tsv --only-show-errors
)
observed_subscription="${observed_account[0]:-}"
observed_tenant="${observed_account[1]:-}"
[[ "${observed_subscription,,}" = "${subscription_id,,}" && "${observed_tenant,,}" = "${tenant_id,,}" ]]
observed_principal="$({
  /usr/bin/az account get-access-token --subscription "$subscription_id" \
    --resource https://management.azure.com/ \
    --query accessToken --output tsv --only-show-errors
} | /usr/bin/python3 -c '
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

if [[ "$transport" == "github-actions" ]]; then
  for slot in $(/usr/bin/seq 1 "$parallelism"); do
    runner_home="$HOME/actions-runner"
    if [[ "$slot" != "1" ]]; then
      runner_home="${runner_home}-${slot}"
    fi
    test -f "$runner_home/.runner"
    (cd "$runner_home" && /usr/bin/sudo -n ./svc.sh status >/dev/null 2>&1)
  done
else
  test ! -e "$HOME/actions-runner"
fi

printf 'attestation_complete transport=%s slots=%s\n' "$transport" "$parallelism"
