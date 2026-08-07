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
done

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

manifest="$services_root/state-migration.json"
jq -e '.schema_version == "1.0.0"' "$manifest" >/dev/null
test "$(jq -r '.services | keys | length' "$manifest")" -eq "${#services[@]}"
for service in "${services[@]}"; do
  module_name="${service//-/_}"
  jq -e --arg service "$service" '
    .services[$service].backend_key == ("services/" + $service + "/<environment>.tfstate") and
    (.services[$service].moves | length) > 0 and
    all(.services[$service].moves[]; (.from | length) > 0 and (.to | length) > 0)
  ' "$manifest" >/dev/null
  jq -e --arg service "$service" --arg prefix "module.$module_name.module.container_app." '
    all(.services[$service].moves[]; .to | startswith($prefix))
  ' "$manifest" >/dev/null
done

terraform fmt -recursive -check "$services_root"
