#!/usr/bin/env bash
# Fail before any Azure mutation when the active identity cannot prove the
# deployment's exact subscription and tenant.
set -euo pipefail

expected_subscription="${1:-${AZURE_SUBSCRIPTION_ID:-}}"
expected_tenant="${2:-${AZURE_TENANT_ID:-}}"

if [[ -z "$expected_subscription" || -z "$expected_tenant" ]]; then
  echo "verify-azure-context: expected subscription and tenant are required." >&2
  exit 2
fi

account="$({
  az account show \
    --subscription "$expected_subscription" \
    --query '[id,tenantId]' \
    --output tsv \
    --only-show-errors
} 2>/dev/null)" || {
  echo "verify-azure-context: expected subscription is unavailable to this identity." >&2
  exit 1
}

IFS=$'\t' read -r actual_subscription actual_tenant <<<"$account"
if [[ "$actual_subscription" != "$expected_subscription" ]]; then
  echo "verify-azure-context: active subscription does not match the expected target." >&2
  exit 1
fi
if [[ "$actual_tenant" != "$expected_tenant" ]]; then
  echo "verify-azure-context: active tenant does not match the expected target." >&2
  exit 1
fi

az account set --subscription "$expected_subscription" --only-show-errors
echo "verify-azure-context: exact subscription and tenant verified."
