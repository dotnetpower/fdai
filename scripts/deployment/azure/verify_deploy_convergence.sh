#!/usr/bin/env bash
set -euo pipefail

: "${OPERATIONAL_HISTORY_ONLY:?OPERATIONAL_HISTORY_ONLY is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
: "${TF_VAR_core_image:?TF_VAR_core_image is required}"
: "${TF_VAR_env:?TF_VAR_env is required}"
: "${TF_VAR_region_short:?TF_VAR_region_short is required}"

request_id="${1:-}"
observability_only=false
deploy_identity_only=false
runtime_call_evidence_only=false
if [[ "$request_id" == apply-observability-* ]]; then
  observability_only=true
  export TF_CLI_ARGS_plan="-target=terraform_data.observability_analyzer_image_update"
elif [[ "$request_id" == apply-runtime-* ]]; then
  runtime_call_evidence_only=true
  export TF_CLI_ARGS_plan="-target=terraform_data.runtime_call_evidence_transition"
elif [[ "$request_id" == apply-identity-* ]]; then
  deploy_identity_only=true
fi

set +e
terraform plan -input=false -lock-timeout=300s -detailed-exitcode -out=post-apply.plan
plan_exit=$?
set -e
rm -f post-apply.plan
if (( plan_exit == 1 )); then
  echo "post-apply Terraform convergence check failed" >&2
  exit 1
fi
if (( plan_exit == 2 )); then
  echo "post-apply Terraform state is not converged" >&2
  exit 1
fi

if [[ "$deploy_identity_only" == "true" || "$runtime_call_evidence_only" == "true" ]]; then
  exit 0
fi

resource_group="$(terraform output -raw resource_group_name)"
if [[ "$observability_only" == "true" ]]; then
  job_name="ca-fdai-${TF_VAR_env}-${TF_VAR_region_short}-core-analyzer"
  container_name="analyzer-tick"
  evidence_path="$RUNNER_TEMP/analyzer-job.json"
elif [[ "$OPERATIONAL_HISTORY_ONLY" != "true" ]]; then
  job_name="ca-fdai-${TF_VAR_env}-${TF_VAR_region_short}-core-inventory"
  container_name="inventory"
  evidence_path="$RUNNER_TEMP/inventory-job.json"
else
  exit 0
fi

az containerapp job show \
  --resource-group "$resource_group" \
  --name "$job_name" \
  --output json > "$evidence_path"
uv run --frozen --package fdai-core-control-plane python \
  ../scripts/deployment/azure/verify_job_image.py \
  --job "$evidence_path" \
  --container "$container_name" \
  --expected-image "$TF_VAR_core_image"
