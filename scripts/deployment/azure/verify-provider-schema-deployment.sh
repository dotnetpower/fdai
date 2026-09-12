#!/usr/bin/env bash
set -euo pipefail

application_source_commit="${1:-}"
runtime_image_revision="${2:-}"
plan_id="${3:-}"
output_path="${4:-}"
storage_account="${5:-}"
environment="${6:-}"
resume_verification="${7:-}"

[[ "$application_source_commit" =~ ^[0-9a-f]{40}$ ]] || {
  echo "provider-schema application source commit is invalid" >&2
  exit 2
}
[[ "$runtime_image_revision" =~ ^[0-9a-f]{40}$ ]] || {
  echo "provider-schema runtime image revision is invalid" >&2
  exit 2
}
[[ "$plan_id" =~ ^plan-[1-9][0-9]*-[1-9][0-9]*$ ]] || {
  echo "provider-schema plan id is invalid" >&2
  exit 2
}
[[ -n "$output_path" && ! -L "$output_path" ]] || {
  echo "provider-schema evidence output path is invalid" >&2
  exit 2
}
[[ "$storage_account" =~ ^[a-z0-9]{3,24}$ ]] || {
  echo "provider-schema evidence storage account is invalid" >&2
  exit 2
}
[[ "$environment" == "dev" ]] || {
  echo "provider-schema evidence environment is invalid" >&2
  exit 2
}
[[ "$resume_verification" == "true" || "$resume_verification" == "false" ]] || {
  echo "provider-schema resume flag is invalid" >&2
  exit 2
}

blob_name="$environment/$plan_id/provider-schema-deployment-evidence.json"
evidence_exists=false
if [[ "$resume_verification" == "true" ]]; then
  evidence_exists="$(
    az storage blob exists \
      --account-name "$storage_account" \
      --container-name deployment-plans \
      --name "$blob_name" \
      --auth-mode login --only-show-errors --query exists --output tsv
  )"
  [[ "$evidence_exists" == "true" || "$evidence_exists" == "false" ]] || {
    echo "provider-schema evidence existence readback is invalid" >&2
    exit 1
  }
fi

if [[ "$evidence_exists" == "true" ]]; then
  az storage blob download \
    --account-name "$storage_account" \
    --container-name deployment-plans \
    --name "$blob_name" \
    --file "$output_path" \
    --auth-mode login --overwrite --only-show-errors --output none
  jq -e \
    --arg source "$application_source_commit" \
    --arg image "$runtime_image_revision" \
    --arg plan "$plan_id" '
      type == "object"
      and .schema_version == "fdai.provider-schema-deployment-evidence.v1"
      and .application_source_commit == $source
      and .runtime_image_revision == $image
      and .plan_id == $plan
      and .grants_authority == false
    ' "$output_path" >/dev/null || {
      echo "stored provider-schema evidence does not match the exact plan" >&2
      exit 1
    }
  exit 0
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bash "$script_dir/verify-provider-schema-job.sh" \
  "$application_source_commit" \
  "$runtime_image_revision" \
  "$plan_id" \
  "$output_path"
az storage blob upload \
  --account-name "$storage_account" \
  --container-name deployment-plans \
  --name "$blob_name" \
  --file "$output_path" \
  --auth-mode login --overwrite false --only-show-errors \
  --content-type application/json --output none