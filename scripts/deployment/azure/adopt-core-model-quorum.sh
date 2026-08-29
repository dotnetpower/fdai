#!/usr/bin/env bash
set -euo pipefail

environment_name="${1:?environment is required}"
region_short="${2:?region short name is required}"
terraform_dir="${3:?Terraform directory is required}"
resource_group="rg-fdai-${environment_name}-${region_short}"
account_name="oai-fdai-${environment_name}-${region_short}"

for capability in t1.judge t2.reasoner.primary; do
  address="module.llm_azure_openai[0].azurerm_cognitive_deployment.capability[\"$capability\"]"
  if terraform -chdir="$terraform_dir" state show "$address" >/dev/null 2>&1; then
    continue
  fi
  deployment_id="$(
    az cognitiveservices account deployment show \
      --resource-group "$resource_group" \
      --name "$account_name" \
      --deployment-name "$capability" \
      --query id -o tsv 2>/dev/null || true
  )"
  if [[ -n "$deployment_id" ]]; then
    terraform -chdir="$terraform_dir" import -input=false "$address" "$deployment_id"
  fi
done
