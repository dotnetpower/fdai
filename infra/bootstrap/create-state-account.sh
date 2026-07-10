#!/usr/bin/env bash
# Create the terraform remote-state storage account with `az` (control plane
# only). Needed because a private + key-disabled account cannot complete
# terraform's post-create blob readiness poll from an operator laptop, so the
# account is created out of band and terraform references it via data source.
#
# Idempotent: re-running with an existing account name is a no-op (prints it).
# Prints the account name to feed into bootstrap.tfvars (state_storage_account_name)
# and the deploy workflow (STATE_STORAGE_ACCOUNT variable).
#
# Usage:
#   OPS_RG=rg-fdai-ops-krc REGION=koreacentral \
#     ./create-state-account.sh [existing-or-new-account-name]
set -euo pipefail

OPS_RG="${OPS_RG:?set OPS_RG (e.g. rg-fdai-ops-krc)}"
REGION="${REGION:?set REGION (e.g. koreacentral)}"
NAME="${1:-st$(openssl rand -hex 8 | cut -c1-16)}"

# Ensure the ops RG exists (control plane).
az group show -n "$OPS_RG" >/dev/null 2>&1 ||
  az group create -n "$OPS_RG" -l "$REGION" -o none

if az storage account show -n "$NAME" -g "$OPS_RG" >/dev/null 2>&1; then
  echo "exists: $NAME"
else
  az storage account create \
    -n "$NAME" -g "$OPS_RG" -l "$REGION" \
    --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 \
    --public-network-access Disabled \
    --allow-shared-key-access false \
    --allow-blob-public-access false \
    --allow-cross-tenant-replication false \
    -o none
  # Blob versioning so a bad state write is recoverable. Data-plane, so it
  # only works from inside the VNet (a private account rejects it from a
  # laptop); best-effort here, the runner can enable it later.
  az storage account blob-service-properties update \
    --account-name "$NAME" -g "$OPS_RG" --enable-versioning true -o none 2>/dev/null ||
    echo "note: enable blob versioning from the runner (private account)"
  echo "created: $NAME"
fi

echo "state_storage_account_name = \"$NAME\""
