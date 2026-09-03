#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
terraform_dir="${1:-$repo_root/infra}"

: "${TF_VAR_core_image:?TF_VAR_core_image is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
: "${CATALOG_ROLLBACK_IMAGE:?CATALOG_ROLLBACK_IMAGE is required}"
: "${ARM_SUBSCRIPTION_ID:?ARM_SUBSCRIPTION_ID is required}"

resource_group="$(terraform -chdir="$terraform_dir" output -raw resource_group_name)"
catalog_job="$(terraform -chdir="$terraform_dir" output -raw operator_api_catalog_job_name)"
job_uri="https://management.azure.com/subscriptions/${ARM_SUBSCRIPTION_ID}/resourceGroups/${resource_group}/providers/Microsoft.App/jobs/${catalog_job}?api-version=2024-03-01"
previous_image="$CATALOG_ROLLBACK_IMAGE"
if [[ ! "$previous_image" =~ ^[^[:space:]@]+@sha256:[0-9a-f]{64}$ ]]; then
  echo "catalog rollback image must be digest-pinned" >&2
  exit 1
fi

update_job_image() {
  local image="$1"
  local raw_body
  local update_body
  raw_body="$(mktemp "$RUNNER_TEMP/catalog-job-current.XXXXXX.json")"
  update_body="$(mktemp "$RUNNER_TEMP/catalog-job-update.XXXXXX.json")"
  chmod 0600 "$raw_body" "$update_body"
  if ! az rest --method get --uri "$job_uri" --output json > "$raw_body"; then
    rm -f -- "$raw_body" "$update_body"
    return 1
  fi
  if ! IMAGE="$image" python3 - "$raw_body" "$update_body" <<'PY'
import json
import os
import sys

def decoded(value):
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            return decoded(json.loads(value))
        except json.JSONDecodeError:
            return value
    if isinstance(value, dict):
        return {key: decoded(child) for key, child in value.items()}
    if isinstance(value, list):
        return [decoded(child) for child in value]
    return value

def resource(value):
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict) and isinstance(properties.get("template"), dict):
            return value
        if isinstance(value.get("template"), dict) and isinstance(value.get("configuration"), dict):
            return value
        for child in value.values():
            found = resource(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = resource(child)
            if found is not None:
                return found
    return None

with open(sys.argv[1], encoding="utf-8") as stream:
    current = resource(decoded(json.load(stream)))
if current is None:
    raise SystemExit("catalog Job ARM response has no mutable resource")
properties = current.get("properties")
if not isinstance(properties, dict):
    properties = {
        key: current[key]
        for key in ("environmentId", "workloadProfileName", "configuration", "template")
        if key in current
    }
template = properties.get("template")
containers = template.get("containers") if isinstance(template, dict) else None
if not isinstance(containers, list) or len(containers) != 1:
    raise SystemExit("catalog Job must contain exactly one container")
containers[0]["image"] = os.environ["IMAGE"]
for key in ("provisioningState", "outboundIpAddresses", "eventStreamEndpoint"):
    properties.pop(key, None)
payload = {
    "location": current["location"],
    "properties": properties,
}
for key in ("identity", "tags"):
    if key in current:
        payload[key] = current[key]
with open(sys.argv[2], "w", encoding="utf-8") as stream:
    json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
PY
  then
    rm -f -- "$raw_body" "$update_body"
    return 1
  fi
  if ! az rest --method put --uri "$job_uri" \
    --headers Content-Type=application/json \
    --body "@$update_body" --output none; then
    rm -f -- "$raw_body" "$update_body"
    return 1
  fi
  rm -f -- "$raw_body" "$update_body"
}

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
    update_job_image "$previous_image"
    run_catalog_job
  fi
}
trap rollback ERR

update_job_image "$TF_VAR_core_image"

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
