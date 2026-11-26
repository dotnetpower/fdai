#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
resource_group="$(terraform output -raw resource_group_name)"
job="$(terraform output -raw canary_job_name)"
slot="deploy-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"

if [[ -z "$job" ]]; then
  echo "canary job is disabled; deployment verification cannot continue" >&2
  exit 1
fi

execution_name="$(timeout 30s az containerapp job start --name "$job" \
  --resource-group "$resource_group" --env-vars "FDAI_CANARY_SLOT=$slot" \
  --query name -o tsv)"
if [[ -z "$execution_name" ]]; then
  echo "$job canary publisher did not return an execution name" >&2
  exit 1
fi
completed=false
for _ in $(seq 1 20); do
  if ! status="$(timeout 30s az containerapp job execution show --name "$job" \
    --resource-group "$resource_group" --job-execution-name "$execution_name" \
    --query "properties.status" -o tsv)"; then
    echo "$job canary publisher status query failed" >&2
    exit 1
  fi
  echo "$job canary publisher status: $status"
  if [[ "$status" == "Succeeded" ]]; then
    completed=true
    break
  fi
  if [[ "$status" == "Failed" ]]; then
    echo "$job canary publisher failed" >&2
    exit 1
  fi
  sleep 6
done
if [[ "$completed" != "true" ]]; then
  echo "$job canary publisher did not complete in time" >&2
  exit 1
fi

FDAI_CANARY_POSTGRES_HOST="$(terraform output -raw postgres_fqdn)"
FDAI_CANARY_POSTGRES_DATABASE="$(terraform output -raw postgres_database)"
export FDAI_CANARY_POSTGRES_HOST FDAI_CANARY_POSTGRES_DATABASE
uv run --frozen --package fdai-core-control-plane \
  python "$repo_root/scripts/deployment/azure/verify_canary_audit.py" \
  --slot "$slot" \
  --latency-budget-ms 30000 \
  --timeout-seconds 60 \
  --output "$RUNNER_TEMP/canary-audit-receipt.json"
