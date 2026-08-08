#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
services_root="$repo_root/infra/services"

services=(
  core-control-plane
  operator-service
  document-ingestion-api
  document-processing-worker
  isolated-executor
)

declare -A service_entrypoints=(
  [core-control-plane]=fdai-core-control-plane
  [operator-service]=fdai-operator-service
  [document-ingestion-api]=fdai-document-ingestion-api
  [document-processing-worker]=fdai-document-processing-worker
  [isolated-executor]=fdai-isolated-executor-service
)

required_root_files=(
  backend.hcl.example
  main.tf
  variables.tf
  outputs.tf
  versions.tf
)

required_contract_variables=(
  image
  identity
  event_topics
  database
  health
  rollback
  platform
)

for service in "${services[@]}"; do
  root="$services_root/$service"

  for file in "${required_root_files[@]}"; do
    test -f "$root/$file" || {
      echo "$service is missing $file" >&2
      exit 1
    }
  done

  for variable in "${required_contract_variables[@]}"; do
    rg -q "variable[[:space:]]+\"$variable\"" "$root/variables.tf" || {
      echo "$service is missing the $variable contract variable" >&2
      exit 1
    }
  done

  expected_source="./modules/$service"
  actual_sources="$(rg -o 'source[[:space:]]*=[[:space:]]*"[^"]+"' "$root/main.tf" | sed -E 's/.*"([^"]+)"/\1/')"
  test "$actual_sources" = "$expected_source" || {
    echo "$service root must reference only $expected_source, got: $actual_sources" >&2
    exit 1
  }
  test -d "$root/modules/$service" || {
    echo "$service owned module directory is missing" >&2
    exit 1
  }

  rg -q 'backend[[:space:]]+"azurerm"' "$root/versions.tf" || {
    echo "$service is missing the azurerm backend declaration" >&2
    exit 1
  }
  rg -q "services/$service/<environment>\.tfstate" "$root/backend.hcl.example" || {
    echo "$service backend key is not service-scoped" >&2
    exit 1
  }

  module_main="$root/modules/$service/main.tf"
  rg -Fq "command              = [\"${service_entrypoints[$service]}\"]" "$module_main" || {
    echo "$service must start its service-owned console entry point" >&2
    exit 1
  }
done

rg -Fq '{ name = "FDAI_OPERATOR_SERVICE_PORT", value = tostring(var.health.port) }' \
  "$services_root/operator-service/modules/operator-service/main.tf"
for required_env in \
  FDAI_RBAC_READERS_GROUP_ID \
  FDAI_RBAC_CONTRIBUTORS_GROUP_ID \
  FDAI_RBAC_APPROVERS_GROUP_ID \
  FDAI_RBAC_OWNERS_GROUP_ID \
  FDAI_RBAC_BREAK_GLASS_GROUP_ID; do
  rg -Fq "{ name = \"$required_env\"" \
    "$services_root/operator-service/modules/operator-service/main.tf"
  rg -Fq "{ name = \"$required_env\"" \
    "$services_root/document-ingestion-api/modules/document-ingestion-api/main.tf"
done
for service in document-ingestion-api document-processing-worker; do
  module_main="$services_root/$service/modules/$service/main.tf"
  rg -Fq '{ name = "FDAI_EMBEDDING_ENDPOINT"' "$module_main"
  rg -Fq '{ name = "FDAI_EMBEDDING_DEPLOYMENT"' "$module_main"
done
worker_main="$services_root/document-processing-worker/modules/document-processing-worker/main.tf"
rg -Fq '{ name = "FDAI_INGESTION_WORKER_HEALTH_PORT", value = tostring(var.health.port) }' \
  "$worker_main"
rg -Fq '{ name = "FDAI_CLAMAV_HOST", value = var.clamav.host }' "$worker_main"
rg -Fq '{ name = "FDAI_CLAMAV_PORT", value = tostring(var.clamav.port) }' "$worker_main"
rg -q 'name[[:space:]]*=[[:space:]]*"clamav"' "$worker_main"
rg -q 'image[[:space:]]*=[[:space:]]*var\.clamav\.image' "$worker_main"
rg -q 'transport[[:space:]]*=[[:space:]]*"TCP"' "$worker_main"
for clamav_variables in \
  "$services_root/document-processing-worker/variables.tf" \
  "$services_root/document-processing-worker/modules/document-processing-worker/variables.tf"; do
  rg -Fq 'var.clamav.host == "127.0.0.1"' "$clamav_variables"
  rg -Fq 'var.clamav.port == 3310' "$clamav_variables"
done
! rg -Fq '{ name = "FDAI_HEALTH_PORT"' "$worker_main"
executor_main="$services_root/isolated-executor/modules/isolated-executor/main.tf"
rg -Fq '{ name = "FDAI_ISOLATED_EXECUTOR_DEPLOYED", value = "1" }' "$executor_main"
rg -Fq '{ name = "FDAI_ISOLATED_EXECUTOR_MI_CLIENT_ID"' "$executor_main"

forbidden_resource_pattern='resource[[:space:]]+"azurerm_(resource_group|virtual_network|subnet|eventhub|eventhub_namespace|postgresql_flexible_server|key_vault|container_registry)"'
if rg -n "$forbidden_resource_pattern" "$services_root" --glob '*.tf'; then
  echo "service roots must not declare shared platform resources" >&2
  exit 1
fi

container_app_declarations="$(rg -n 'resource[[:space:]]+"azurerm_container_app"' "$services_root" --glob '*.tf' | wc -l)"
test "$container_app_declarations" -eq 1 || {
  echo "expected exactly one shared Container App renderer, got $container_app_declarations" >&2
  exit 1
}

shared_container_app="$services_root/_modules/container-app"
rg -q 'variable[[:space:]]+"sidecars"' "$shared_container_app/variables.tf"
rg -q 'dynamic[[:space:]]+"container"' "$shared_container_app/main.tf"
rg -Fq 'var.health.liveness_path == null || var.health.liveness_path != var.health.readiness_path' \
  "$shared_container_app/main.tf"

rg -Fq 'liveness_path = null' "$services_root/operator-service/variables.tf"
rg -Fq 'readiness_path = "/healthz"' "$services_root/operator-service/variables.tf"
rg -Fq 'liveness_path = null' "$services_root/document-ingestion-api/variables.tf"
rg -Fq 'readiness_path = "/healthz"' "$services_root/document-ingestion-api/variables.tf"
rg -q 'variable[[:space:]]+"clamav"' \
  "$services_root/document-processing-worker/variables.tf"
rg -Fq '@sha256:' "$services_root/document-processing-worker/variables.tf"

manifest="$services_root/state-migration.json"
jq -e '.schema_version == "2.0.0"' "$manifest" >/dev/null
test "$(jq -r '.services | keys | length' "$manifest")" -eq "${#services[@]}"
for service in "${services[@]}"; do
  module_name="${service//-/_}"
  jq -e --arg service "$service" '
    .services[$service].backend_key == ("services/" + $service + "/<environment>.tfstate") and
    .services[$service].source_backend_key_template == "fdai-{environment}.tfstate" and
    (.services[$service].moves | length) > 0 and
    all(.services[$service].moves[]; (.from | length) > 0 and (.to | length) > 0)
  ' "$manifest" >/dev/null
  jq -e --arg service "$service" --arg prefix "module.$module_name.module.container_app." '
    all(.services[$service].moves[]; .to | startswith($prefix))
  ' "$manifest" >/dev/null
done

terraform fmt -recursive -check "$services_root"
