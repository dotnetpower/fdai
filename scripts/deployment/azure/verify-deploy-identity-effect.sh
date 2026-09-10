#!/usr/bin/env bash
set -euo pipefail

plan="${1:?plan JSON is required}"
principal_id="${2:?stable principal id is required}"
receipt="${3:?effect receipt path is required}"
storage_account="${4:?state storage account is required}"
environment="${5:?environment is required}"
plan_id="${6:?plan id is required}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../../.." && pwd)"

PYTHONPATH="$repo_root" python3 "$here/verify_deploy_identity_effect.py" \
  --plan "$plan" \
  --principal-id "$principal_id" \
  --output "$receipt"
receipt_digest="$(sha256sum "$receipt" | cut -d' ' -f1)"
echo "DEPLOY_IDENTITY_EFFECT_DIGEST=$receipt_digest" >> "${GITHUB_ENV:?GITHUB_ENV is required}"
az storage blob upload \
  --account-name "$storage_account" \
  --container-name deployment-plans \
  --name "$environment/$plan_id/deploy-identity-effect-receipt.json" \
  --file "$receipt" \
  --auth-mode login \
  --overwrite false \
  --only-show-errors \
  --content-type application/json \
  --output none
