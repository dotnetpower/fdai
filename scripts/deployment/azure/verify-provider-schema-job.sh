#!/usr/bin/env bash
set -euo pipefail

application_source_commit="${1:-}"
runtime_image_revision="${2:-}"
plan_id="${3:-}"
output_path="${4:-}"

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
[[ -n "$output_path" ]] || {
  echo "provider-schema evidence output path is required" >&2
  exit 2
}
: "${TF_VAR_core_image:?TF_VAR_core_image is required}"

job_id="$(terraform output -raw provider_schema_job_id)"
job_pattern='^/subscriptions/[^/]+/resourceGroups/([^/]+)/providers/Microsoft[.]App/jobs/([^/]+)$'
if [[ ! "$job_id" =~ $job_pattern ]]; then
  echo "provider-schema Job resource id is unavailable" >&2
  exit 1
fi
resource_group="${BASH_REMATCH[1]}"
job_name="${BASH_REMATCH[2]}"
started_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
start_result="$(az containerapp job start \
  --resource-group "$resource_group" \
  --name "$job_name" \
  --only-show-errors --output json)"
execution_name="$(jq -er '.name | select(type == "string" and length > 0)' <<<"$start_result")" || {
  echo "provider-schema Job start did not return an execution identity" >&2
  exit 1
}

execution_status=""
deadline=$((SECONDS + 1800))
while ((SECONDS < deadline)); do
  execution_status="$(
    az containerapp job execution show \
      --resource-group "$resource_group" \
      --name "$job_name" \
      --job-execution-name "$execution_name" \
      --query properties.status --output tsv --only-show-errors 2>/dev/null || true
  )"
  if [[ "$execution_status" == "Succeeded" ]]; then
    break
  fi
  if [[ "$execution_status" == "Failed" ]]; then
    echo "provider-schema Job execution failed" >&2
    exit 1
  fi
  sleep 12
done
[[ "$execution_status" == "Succeeded" ]] || {
  echo "provider-schema Job execution did not complete within 1800 seconds" >&2
  exit 1
}

execution_image="$(
  az containerapp job execution show \
    --resource-group "$resource_group" \
    --name "$job_name" \
    --job-execution-name "$execution_name" \
    --query "properties.template.containers[?name=='provider-schema'].image | [0]" \
    --output tsv --only-show-errors
)"
[[ "$execution_image" == "$TF_VAR_core_image" ]] || {
  echo "provider-schema Job execution image does not match the protected digest" >&2
  exit 1
}

vault_uri="$(terraform output -raw key_vault_uri)"
vault_pattern='^https://([a-zA-Z0-9-]+)[.]vault[.]azure[.]net/?$'
if [[ ! "$vault_uri" =~ $vault_pattern ]]; then
  echo "provider-schema Key Vault URI is invalid" >&2
  exit 1
fi
vault_name="${BASH_REMATCH[1]}"
provider_schema_dsn=""
for attempt in 1 2 3 4 5 6; do
  provider_schema_dsn="$(
    az keyvault secret show \
      --vault-name "$vault_name" \
      --name fdai-state-store-dsn \
      --query value --output tsv --only-show-errors 2>/dev/null || true
  )"
  [[ -n "$provider_schema_dsn" ]] && break
  sleep "$((attempt * 2))"
done
[[ -n "$provider_schema_dsn" ]] || {
  echo "provider-schema verification DSN is unavailable" >&2
  exit 1
}
echo "::add-mask::$provider_schema_dsn"
FDAI_PROVIDER_SCHEMA_DSN="$provider_schema_dsn" \
  uv run --frozen --package fdai-core-control-plane python \
  -m fdai.delivery.provider_schema_deployment_evidence \
  --application-source-commit "$application_source_commit" \
  --runtime-image-revision "$runtime_image_revision" \
  --plan-id "$plan_id" \
  --execution-name "$execution_name" \
  --execution-status "$execution_status" \
  --started-at "$started_at" \
  --output "$output_path"
unset provider_schema_dsn

echo "Provider-schema Job execution and durable evidence verified." >> "$GITHUB_STEP_SUMMARY"