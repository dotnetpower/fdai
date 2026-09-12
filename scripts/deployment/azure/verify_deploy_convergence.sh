#!/usr/bin/env bash
set -euo pipefail

: "${OPERATIONAL_HISTORY_ONLY:?OPERATIONAL_HISTORY_ONLY is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
: "${TF_VAR_core_image:?TF_VAR_core_image is required}"
: "${TF_VAR_env:?TF_VAR_env is required}"
: "${TF_VAR_region_short:?TF_VAR_region_short is required}"

request_id="${1:-}"
observability_only=false
cost_governance_only=false
deploy_identity_only=false
provider_schema_only=false
runtime_call_evidence_only=false
model_binding_only=false
if [[ "$request_id" == apply-observability-* ]]; then
  observability_only=true
  export TF_CLI_ARGS_plan="-target=terraform_data.observability_analyzer_image_update"
elif [[ "$request_id" == apply-cost-* ]]; then
  cost_governance_only=true
  export TF_CLI_ARGS_plan="-target=azurerm_role_assignment.inventory_cost_reader -target=azurerm_container_app_job.cost_governance_collector[0] -target=azurerm_container_app_job.cost_governance_analyzer[0]"
elif [[ "$request_id" == apply-runtime-* ]]; then
  runtime_call_evidence_only=true
  export TF_CLI_ARGS_plan="-target=terraform_data.runtime_call_evidence_transition -target=terraform_data.inventory_runtime_image_update -target=terraform_data.runtime_workspace_binding_transition"
elif [[ "$request_id" == apply-model-* ]]; then
  model_binding_only=true
  export TF_CLI_ARGS_plan="-target=module.llm_azure_openai[0].azurerm_cognitive_deployment.capability"
elif [[ "$request_id" == apply-provider-* ]]; then
  provider_schema_only=true
  export TF_CLI_ARGS_plan="-target=azurerm_container_app_job.provider_schema[0]"
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

if [[ "$deploy_identity_only" == "true" \
  || "$runtime_call_evidence_only" == "true" \
  || "$model_binding_only" == "true" ]]; then
  exit 0
fi

resource_group="$(terraform output -raw resource_group_name)"
if [[ "$cost_governance_only" == "true" ]]; then
  : "${TF_VAR_cost_governance_image:?TF_VAR_cost_governance_image is required}"
  collector_job_name="$(terraform output -raw cost_governance_collector_job_name)"
  analyzer_job_name="$(terraform output -raw cost_governance_analyzer_job_name)"
  [[ -n "$collector_job_name" && -n "$analyzer_job_name" ]] || {
    echo "Cost Governance Job names are unavailable after apply" >&2
    exit 1
  }
  collector_evidence_path="$RUNNER_TEMP/cost-governance-collector-job.json"
  analyzer_evidence_path="$RUNNER_TEMP/cost-governance-analyzer-job.json"
  collector_image_receipt="$RUNNER_TEMP/cost-governance-collector-image.json"
  analyzer_image_receipt="$RUNNER_TEMP/cost-governance-analyzer-image.json"
  readback_path="$RUNNER_TEMP/cost-governance-job-image-readback.json"
  az containerapp job show \
    --resource-group "$resource_group" \
    --name "$collector_job_name" \
    --output json > "$collector_evidence_path"
  az containerapp job show \
    --resource-group "$resource_group" \
    --name "$analyzer_job_name" \
    --output json > "$analyzer_evidence_path"
  uv run --frozen --package fdai-core-control-plane python \
    ../scripts/deployment/azure/verify_job_image.py \
    --job "$collector_evidence_path" \
    --container "cost-governance-collector" \
    --expected-image "$TF_VAR_cost_governance_image" > "$collector_image_receipt"
  uv run --frozen --package fdai-core-control-plane python \
    ../scripts/deployment/azure/verify_job_image.py \
    --job "$analyzer_evidence_path" \
    --container "cost-governance-analyzer" \
    --expected-image "$TF_VAR_cost_governance_image" > "$analyzer_image_receipt"
  python3 ../scripts/deployment/azure/build_cost_governance_job_readback.py \
    --collector "$collector_image_receipt" \
    --analyzer "$analyzer_image_receipt" \
    --expected-image "$TF_VAR_cost_governance_image" \
    --output "$readback_path"
  exit 0
elif [[ "$provider_schema_only" == "true" ]]; then
  job_id="$(terraform output -raw provider_schema_job_id)"
  if [[ ! "$job_id" =~ ^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft[.]App/jobs/[^/]+$ ]]; then
    echo "provider-schema Job resource id is unavailable after apply" >&2
    exit 1
  fi
  container_name="provider-schema"
  evidence_path="$RUNNER_TEMP/provider-schema-job.json"
  az resource show --ids "$job_id" --api-version 2024-03-01 --output json > "$evidence_path"
elif [[ "$observability_only" == "true" ]]; then
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

if [[ "$provider_schema_only" != "true" ]]; then
  az containerapp job show \
    --resource-group "$resource_group" \
    --name "$job_name" \
    --output json > "$evidence_path"
fi
uv run --frozen --package fdai-core-control-plane python \
  ../scripts/deployment/azure/verify_job_image.py \
  --job "$evidence_path" \
  --container "$container_name" \
  --expected-image "$TF_VAR_core_image"
