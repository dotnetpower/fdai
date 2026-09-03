#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
terraform_dir="${1:-$repo_root/infra}"

: "${TF_VAR_core_image:?TF_VAR_core_image is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
: "${ARM_SUBSCRIPTION_ID:?ARM_SUBSCRIPTION_ID is required}"

resource_group="$(terraform -chdir="$terraform_dir" output -raw resource_group_name)"
catalog_job="$(terraform -chdir="$terraform_dir" output -raw operator_api_catalog_job_name)"
job_uri="https://management.azure.com/subscriptions/${ARM_SUBSCRIPTION_ID}/resourceGroups/${resource_group}/providers/Microsoft.App/jobs/${catalog_job}?api-version=2024-03-01"

read_job_image() {
  az rest --method get --uri "$job_uri" --output json \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["properties"]["template"]["containers"][0]["image"])'
}

previous_image="$(read_job_image)"
if [[ -z "$previous_image" ]]; then
  echo "catalog Job has no current image to restore" >&2
  exit 1
fi

run_catalog_job() {
  az containerapp job start \
    --resource-group "$resource_group" \
    --name "$catalog_job" \
    --only-show-errors --output none
  local deadline=$((SECONDS + 900))
  local execution_name=""
  local status=""
  while ((SECONDS < deadline)); do
    execution_name="$(az containerapp job execution list \
      --resource-group "$resource_group" \
      --name "$catalog_job" \
      --query 'sort_by([], &properties.startTime)[-1].name' -o tsv 2>/dev/null || true)"
    if [[ -z "$execution_name" ]]; then
      sleep 10
      continue
    fi
    status="$(az containerapp job execution show \
      --resource-group "$resource_group" \
      --name "$catalog_job" \
      --job-execution-name "$execution_name" \
      --query properties.status -o tsv 2>/dev/null || true)"
    if [[ "$status" == "Succeeded" ]]; then
      return 0
    fi
    if [[ "$status" == "Failed" ]]; then
      echo "authoritative catalog materialization Job failed" >&2
      return 1
    fi
    sleep 12
  done
  echo "authoritative catalog materialization Job exceeded its 900-second deadline" >&2
  return 1
}

rollback_required=true
rollback() {
  trap - ERR
  if [[ "$rollback_required" == "true" ]]; then
    az containerapp job update \
      --resource-group "$resource_group" \
      --name "$catalog_job" \
      --image "$previous_image" \
      --only-show-errors --output none
    run_catalog_job
  fi
}
trap rollback ERR

az containerapp job update \
  --resource-group "$resource_group" \
  --name "$catalog_job" \
  --image "$TF_VAR_core_image" \
  --only-show-errors --output none
observed_image="$(read_job_image)"
if [[ "$observed_image" != "$TF_VAR_core_image" ]]; then
  echo "catalog Job image readback does not match the selected Core image" >&2
  exit 1
fi

bash "$repo_root/scripts/deployment/azure/bootstrap-service-migrations.sh" \
  "$terraform_dir" "$RUNNER_TEMP/catalog-service-migration-adoption" \
  "$(git -C "$repo_root" rev-parse HEAD)"

run_catalog_job

vault_uri="$(terraform -chdir="$terraform_dir" output -raw key_vault_uri)"
vault_name="${vault_uri#https://}"
vault_name="${vault_name%%.*}"
migration_secret_name="$(
  REPO_ROOT="$repo_root" python3 - <<'PY'
import json
import os
from pathlib import Path

matrix = Path(os.environ["REPO_ROOT"]) / "scripts/deployment/service/service-matrix.json"
services = json.loads(matrix.read_text(encoding="utf-8"))["services"]
names = {item["migration_dsn_secret_name"] for item in services.values()}
if len(names) != 1:
    raise SystemExit("integrated catalog verification requires one migration DSN secret")
print(names.pop())
PY
)"
catalog_dsn=""
for attempt in 1 2 3 4 5 6; do
  catalog_dsn="$(az keyvault secret show \
    --vault-name "$vault_name" \
    --name "$migration_secret_name" \
    --query value --only-show-errors -o tsv 2>/dev/null || true)"
  [[ -n "$catalog_dsn" ]] && break
  sleep "$((attempt * 2))"
done
if [[ -z "$catalog_dsn" ]]; then
  echo "catalog verification DSN is unavailable" >&2
  exit 1
fi
echo "::add-mask::$catalog_dsn"
FDAI_STATE_STORE_DSN="$catalog_dsn" uv run --frozen --extra dev python \
  "$repo_root/scripts/deployment/azure/verify-authoritative-catalogs.py"
unset catalog_dsn

rollback_required=false
trap - ERR
