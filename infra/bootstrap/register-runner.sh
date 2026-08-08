#!/usr/bin/env bash
# Register the ops/hub runner VM as a GitHub Actions self-hosted runner, using
# a short-lived registration token minted via the gh CLI and applied over
# `az vm run-command` (the VM has no public IP). Idempotent (--replace).
#
# Usage: AZURE_SUBSCRIPTION_ID=<expected> AZURE_TENANT_ID=<expected> \
#   ./register-runner.sh <owner>/<repo> [ops_rg] [vm_name] [runner_user] [parallelism]
set -euo pipefail

REPO="${1:?usage: register-runner.sh <owner>/<repo> [ops_rg] [vm_name] [runner_user] [parallelism]}"
OPS_RG="${2:-rg-fdai-ops-krc}"
VM="${3:-vm-runner-fdai-dev-krc}"
RUNNER_USER="${4:-fdairunner}"
PARALLELISM="${5:-1}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPECTED_SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:?set AZURE_SUBSCRIPTION_ID}"
EXPECTED_TENANT="${AZURE_TENANT_ID:?set AZURE_TENANT_ID}"

if [[ ! "$PARALLELISM" =~ ^[1-5]$ ]]; then
  echo "parallelism must be an integer from 1 through 5" >&2
  exit 2
fi

"$HERE/../../scripts/deployment/azure/verify-azure-context.sh" \
  "$EXPECTED_SUBSCRIPTION" "$EXPECTED_TENANT"

echo "== minting registration token =="
TOKEN=$(gh api -X POST "repos/${REPO}/actions/runners/registration-token" --jq .token)
REMOVE_TOKEN=$(gh api -X POST "repos/${REPO}/actions/runners/remove-token" --jq .token)

echo "== registering ${PARALLELISM} runner slot(s) on ${VM} (via run-command) =="
REMOTE_SCRIPT_B64=$(base64 -w0 "$HERE/register-runner-remote.sh")
REPO_B64=$(printf '%s' "$REPO" | base64 -w0)
RUNNER_USER_B64=$(printf '%s' "$RUNNER_USER" | base64 -w0)
TOKEN_B64=$(printf '%s' "$TOKEN" | base64 -w0)
REMOVE_TOKEN_B64=$(printf '%s' "$REMOVE_TOKEN" | base64 -w0)
remote_output=$(
  az vm run-command invoke -g "$OPS_RG" -n "$VM" --command-id RunShellScript \
    --scripts "printf '%s' '$REMOTE_SCRIPT_B64' | base64 -d | bash -s -- '$REPO_B64' '$RUNNER_USER_B64' '$PARALLELISM' '$TOKEN_B64' '$REMOVE_TOKEN_B64'" \
    --query "value[0].message" -o tsv
)
printf '%s\n' "$remote_output" | tail -20
grep -Fq "FDAI_RUNNER_REGISTRATION_OK slots=${PARALLELISM}" <<<"$remote_output" || {
  echo "remote runner registration did not emit its success marker" >&2
  exit 1
}

echo "== runner status on GitHub =="
gh api "repos/${REPO}/actions/runners" --jq '.runners[] | {name, status, labels: [.labels[].name]}'
