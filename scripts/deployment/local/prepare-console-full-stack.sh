#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root"

force_preparation=0
if [[ $# -gt 1 ]]; then
  echo "Usage: $0 [--force]" >&2
  exit 2
fi
if [[ $# -eq 1 ]]; then
  if [[ "$1" != "--force" ]]; then
    echo "Usage: $0 [--force]" >&2
    exit 2
  fi
  force_preparation=1
fi

if [[ ! -x "$repo_root/.venv/bin/python" ]]; then
  echo "missing local Python environment: run uv sync --extra dev" >&2
  exit 1
fi
if [[ ! -f "$repo_root/console/.env.local" ]]; then
  echo "missing local Console environment: console/.env.local" >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "missing npm: install Node.js and npm before starting the Console" >&2
  exit 1
fi
if [[ ! -x "$repo_root/console/node_modules/.bin/vite" ]]; then
  echo "missing Console dependencies: run npm --prefix console install" >&2
  exit 1
fi

legacy_preparation_marker="$repo_root/.fdai/console-full-stack-preparation.sha256"
stage_marker_dir="$repo_root/.fdai/console-preparation"
legacy_preparation_inputs=(
  console/.env.local
  pyproject.toml
  uv.lock
  alembic
  service-migrations
  config
  policies
  rule-catalog
  scripts/deployment/local
  scripts/deployment/azure
)
required_outputs=(
  .fdai/local-runtime.env
  .fdai/local-operator-service.env
  .fdai/local-document-ingestion-api.env
  .fdai/local-document-processing-worker.env
  .fdai/local-isolated-executor.env
)
for optional_input in \
  resolved-models.json \
  .fdai/resolved-models-vision.json \
  infra/terraform.tfstate; do
  if [[ -f "$repo_root/$optional_input" ]]; then
    legacy_preparation_inputs+=("$optional_input")
  fi
done

path_digest() {
  "$repo_root/.venv/bin/python" \
    "$repo_root/scripts/automation/local-service-input-digest.py" \
    --paths-only \
    "$@"
}

legacy_digest() {
  "$repo_root/.venv/bin/python" \
    "$repo_root/scripts/automation/local-service-input-digest.py" \
    "$@"
}

can_reuse_legacy_preparation() {
  local current_digest="$1"
  local output
  [[ -f "$legacy_preparation_marker" ]] || return 1
  [[ "$(<"$legacy_preparation_marker")" == "$current_digest" ]] || return 1
  for output in "${required_outputs[@]}"; do
    [[ -s "$repo_root/$output" ]] || return 1
  done
  "$repo_root/.venv/bin/python" \
    "$repo_root/scripts/automation/developer-workflow.py" \
    local-services \
    --wait-seconds 0 >/dev/null
}

write_marker() {
  local marker="$1"
  local digest="$2"
  local temporary
  mkdir -p "$(dirname "$marker")"
  umask 077
  temporary="$(mktemp "${marker}.XXXXXX")"
  printf '%s\n' "$digest" > "$temporary"
  mv "$temporary" "$marker"
}

stage_reusable() {
  local name="$1"
  local digest="$2"
  shift 2
  local marker="$stage_marker_dir/$name.sha256"
  local output
  [[ "$force_preparation" == "0" ]] || return 1
  [[ -f "$marker" ]] || return 1
  [[ "$(<"$marker")" == "$digest" ]] || return 1
  for output in "$@"; do
    [[ -s "$output" ]] || return 1
  done
}

run_stage() {
  local name="$1"
  local digest="$2"
  local callback="$3"
  shift 3
  local marker="$stage_marker_dir/$name.sha256"
  if stage_reusable "$name" "$digest" "$@"; then
    printf '%s service=console-preparation stage=%s event=reused\n' \
      "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')" "$name"
    return
  fi
  rm -f "$marker"
  "$callback"
  write_marker "$marker" "$digest"
  printf '%s service=console-preparation stage=%s event=completed\n' \
    "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')" "$name"
}

write_database_identity() {
  local target="$stage_marker_dir/database-volumes.sha256"
  local temporary
  mkdir -p "$stage_marker_dir"
  umask 077
  temporary="$(mktemp "${target}.XXXXXX")"
  docker volume inspect \
    --format '{{.Name}} {{.CreatedAt}}' \
    fdai-pgdata fdai-validation-pgdata \
    | sha256sum \
    | cut -d' ' -f1 > "$temporary"
  mv "$temporary" "$target"
}

if [[ "$force_preparation" == "1" ]]; then
  rm -f "$legacy_preparation_marker"
  rm -f "$stage_marker_dir"/*.sha256
fi

terraform_bin="${FDAI_TERRAFORM_BIN:-terraform}"
az_bin="${FDAI_AZ_BIN:-az}"

require_cloud_tools() {
  if ! command -v "$terraform_bin" >/dev/null 2>&1; then
    echo "missing Terraform CLI: $terraform_bin" >&2
    return 1
  fi
  if ! command -v "$az_bin" >/dev/null 2>&1; then
    echo "missing Azure CLI: $az_bin" >&2
    return 1
  fi
}

run_runtime_projection() (
  set -a
  source "$repo_root/.fdai/local-runtime.env"
  set +a
  PYTHONPATH="$repo_root/services/core-control-plane/src:$repo_root/packages/service-contracts/src" \
    "$repo_root/.venv/bin/python" "$1"
)

sync_entra_redirects() (
  set -a
  source "$repo_root/console/.env.local"
  set +a
  for origin in http://localhost:5273 http://127.0.0.1:5273; do
    env -u AZURE_CONFIG_DIR \
      "$repo_root/.venv/bin/python" \
      "$repo_root/scripts/deployment/azure/sync-entra-spa-redirect.py" \
      --tenant-id "$VITE_MSAL_TENANT_ID" \
      --spa-client-id "$VITE_MSAL_CLIENT_ID" \
      --origin "$origin" \
      --allow-loopback-http
  done
)

prepare_local_state() {
  bash "$repo_root/scripts/deployment/local/prepare-console-state.sh" --dependencies-ready
}

prepare_runtime_environment() {
  require_cloud_tools
  env -u AZURE_CONFIG_DIR \
    bash "$repo_root/scripts/deployment/azure/prepare-local-runtime-env.sh"
}

refresh_inventory() {
  require_cloud_tools
  run_runtime_projection "$repo_root/scripts/deployment/local/refresh-authoritative-inventory.py"
}

materialize_settings() {
  run_runtime_projection "$repo_root/scripts/deployment/local/materialize-authoritative-settings.py"
}

materialize_catalogs() {
  run_runtime_projection "$repo_root/scripts/deployment/local/materialize-authoritative-catalogs.py"
}

prepare_service_environments() {
  bash "$repo_root/scripts/deployment/local/prepare-operator-service-env.sh"
  bash "$repo_root/scripts/deployment/local/prepare-independent-service-envs.sh"
}

prepare_entra_redirects() {
  require_cloud_tools
  sync_entra_redirects
}

bash "$repo_root/scripts/deployment/local/dev-up.sh"

if [[ "$force_preparation" == "0" && -f "$legacy_preparation_marker" ]]; then
  current_legacy_digest="$(legacy_digest "${legacy_preparation_inputs[@]}")"
  if can_reuse_legacy_preparation "$current_legacy_digest"; then
    printf '%s service=console-preparation event=reused\n' \
      "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')"
    exit 0
  fi
fi
rm -f "$legacy_preparation_marker"

write_database_identity
database_identity="$stage_marker_dir/database-volumes.sha256"

local_state_inputs=(
  pyproject.toml
  uv.lock
  alembic
  service-migrations
  infra/local/docker-compose.yml
  infra/local/.env.example
  scripts/deployment/local/dev-up.sh
  scripts/deployment/local/prepare-console-state.sh
  "$database_identity"
)
runtime_environment_inputs=(
  console/.env.local
  pyproject.toml
  uv.lock
  packages/service-contracts/src/fdai_service_contracts/semantic_turn.py
  scripts/deployment/azure/prepare-local-runtime-env.sh
)
for optional_input in \
  resolved-models.json \
  .fdai/resolved-models-vision.json \
  infra/terraform.tfstate; do
  if [[ -f "$repo_root/$optional_input" ]]; then
    runtime_environment_inputs+=("$optional_input")
  fi
done
inventory_inputs=(
  .fdai/local-runtime.env
  rule-catalog
  scripts/deployment/local/refresh-authoritative-inventory.py
  "$database_identity"
)
settings_inputs=(
  .fdai/local-runtime.env
  scripts/deployment/local/materialize-authoritative-settings.py
  "$database_identity"
)
catalog_inputs=(
  .fdai/local-runtime.env
  config
  policies
  rule-catalog
  scripts/deployment/local/materialize-authoritative-catalogs.py
  "$database_identity"
)
service_environment_inputs=(
  .fdai/local-runtime.env
  console/.env.local
  scripts/deployment/local/prepare-operator-service-env.sh
  scripts/deployment/local/prepare-independent-service-envs.sh
)
entra_inputs=(
  console/.env.local
  scripts/deployment/azure/sync-entra-spa-redirect.py
)

run_stage \
  local-state \
  "$(path_digest "${local_state_inputs[@]}")" \
  prepare_local_state
run_stage \
  runtime-environment \
  "$(path_digest "${runtime_environment_inputs[@]}")" \
  prepare_runtime_environment \
  "$repo_root/.fdai/local-runtime.env"
run_stage \
  authoritative-inventory \
  "$(path_digest "${inventory_inputs[@]}")" \
  refresh_inventory
run_stage \
  authoritative-settings \
  "$(path_digest "${settings_inputs[@]}")" \
  materialize_settings
run_stage \
  authoritative-catalogs \
  "$(path_digest "${catalog_inputs[@]}")" \
  materialize_catalogs
run_stage \
  service-environments \
  "$(path_digest "${service_environment_inputs[@]}")" \
  prepare_service_environments \
  "$repo_root/.fdai/local-operator-service.env" \
  "$repo_root/.fdai/local-document-ingestion-api.env" \
  "$repo_root/.fdai/local-document-processing-worker.env" \
  "$repo_root/.fdai/local-isolated-executor.env"
run_stage \
  entra-redirects \
  "$(path_digest "${entra_inputs[@]}")" \
  prepare_entra_redirects

printf '%s service=console-preparation event=completed\n' \
  "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')"
