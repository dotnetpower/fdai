#!/usr/bin/env bash
# Create the Terraform remote-state storage account and its two private
# containers with Azure Resource Manager calls only. A private + key-disabled
# account rejects laptop data-plane calls, so bootstrap never uses `az storage
# container` or account keys.
#
# Convergent: a matching FDAI-owned account is hardened and its containers are
# reconciled; an unowned name collision fails before any account mutation.
# Prints the account name to feed into bootstrap.tfvars (state_storage_account_name)
# and the deploy workflow (STATE_STORAGE_ACCOUNT variable).
#
# Usage:
#   AZURE_SUBSCRIPTION_ID=<expected> AZURE_TENANT_ID=<expected> \
#     OPS_RG=rg-fdai-ops-krc REGION=koreacentral \
#     ./create-state-account.sh [existing-or-new-account-name]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPS_RG="${OPS_RG:?set OPS_RG (e.g. rg-fdai-ops-krc)}"
REGION="${REGION:?set REGION (e.g. koreacentral)}"
EXPECTED_SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:?set AZURE_SUBSCRIPTION_ID}"
EXPECTED_TENANT="${AZURE_TENANT_ID:?set AZURE_TENANT_ID}"
NAME="${1:-st$(openssl rand -hex 8 | cut -c1-16)}"

/bin/bash "$HERE/../../scripts/deployment/azure/verify-azure-context.sh" \
  "$EXPECTED_SUBSCRIPTION" "$EXPECTED_TENANT"

# Ensure the ops RG exists (control plane).
az group show -n "$OPS_RG" >/dev/null 2>&1 ||
  az group create -n "$OPS_RG" -l "$REGION" -o none

if az storage account show -n "$NAME" -g "$OPS_RG" >/dev/null 2>&1; then
  readarray -t ownership < <(
    az storage account show -n "$NAME" -g "$OPS_RG" \
      --query '[tags."fdai:managed",tags."fdai:layer"]' \
      --output tsv --only-show-errors
  )
  if [[ "${ownership[0]:-}" != "true" || "${ownership[1]:-}" != "ops-bootstrap" ]]; then
    echo "existing state storage account is not owned by FDAI ops bootstrap" >&2
    exit 1
  fi
  echo "exists: $NAME"
else
  az storage account create \
    -n "$NAME" -g "$OPS_RG" -l "$REGION" \
    --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 \
    --public-network-access Disabled \
    --allow-shared-key-access false \
    --allow-blob-public-access false \
    --allow-cross-tenant-replication false \
    --tags fdai:managed=true fdai:layer=ops-bootstrap fdai:managed-by=bootstrap \
    -o none
  echo "created: $NAME"
fi

readarray -t posture < <(
  az storage account show -n "$NAME" -g "$OPS_RG" \
    --query '[id,publicNetworkAccess,allowSharedKeyAccess,allowBlobPublicAccess,minimumTlsVersion]' \
    --output tsv --only-show-errors
)
account_id="${posture[0]:-}"
public_access="${posture[1]:-}"
shared_key="${posture[2]:-}"
blob_public_access="${posture[3]:-}"
minimum_tls="${posture[4]:-}"
if [[ -z "$account_id" \
  || "${public_access,,}" != "disabled" \
  || "${shared_key,,}" != "false" \
  || "${blob_public_access,,}" != "false" \
  || "$minimum_tls" != "TLS1_2" ]]; then
  echo "state storage account does not satisfy the private keyless posture" >&2
  exit 1
fi

management_endpoint="https://management.azure.com"
blob_service_url="${management_endpoint}${account_id}/blobServices/default?api-version=2023-05-01"
az rest --method patch --url "$blob_service_url" --body \
  '{"properties":{"isVersioningEnabled":true,"deleteRetentionPolicy":{"enabled":true,"days":30},"containerDeleteRetentionPolicy":{"enabled":true,"days":30}}}' \
  --output none

for container in tfstate deployment-plans; do
  container_url="${management_endpoint}${account_id}/blobServices/default/containers/${container}?api-version=2023-05-01"
  az rest --method put --url "$container_url" \
    --body '{"properties":{"publicAccess":"None"}}' --output none
  provisioned="$(az rest --method get --url "$container_url" --query id --output tsv)"
  if [[ "${provisioned,,}" != "${account_id,,}/blobservices/default/containers/${container}" ]]; then
    echo "state container '$container' failed ARM readback" >&2
    exit 1
  fi
done

echo "state_storage_account_name = \"$NAME\""
