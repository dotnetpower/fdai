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

legacy_preparation_marker="$repo_root/.fdai/console-full-stack-preparation.sha256"
stage_marker_dir="$repo_root/.fdai/console-preparation"
bounded_runner="$repo_root/scripts/automation/run-bounded-command.py"
stage_timeout_seconds="${FDAI_CONSOLE_PREPARATION_STAGE_TIMEOUT_SECONDS:-300}"
stage_no_progress_seconds="${FDAI_CONSOLE_PREPARATION_NO_PROGRESS_SECONDS:-120}"
dependency_timeout_seconds="${FDAI_CONSOLE_DEPENDENCY_TIMEOUT_SECONDS:-600}"
legacy_preparation_inputs=(
  console/.env.local
  console/package.json
  console/package-lock.json
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
  console/node_modules/.bin/vite
  .venv/bin/fdai-document-processing-worker
  .venv/bin/fdai-isolated-executor-service
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

run_bounded() {
  local label="$1"
  shift
  "$repo_root/.venv/bin/python" \
    "$bounded_runner" \
    --label "$label" \
    --timeout-seconds "$stage_timeout_seconds" \
    --no-progress-seconds "$stage_no_progress_seconds" \
    -- \
    "$@"
}

run_dependency_install() {
  "$repo_root/.venv/bin/python" \
    "$bounded_runner" \
    --label python-workspace-dependencies \
    --timeout-seconds "$dependency_timeout_seconds" \
    --no-progress-seconds "$stage_no_progress_seconds" \
    -- \
    uv sync --all-packages --extra dev --extra azure-mcp --frozen
  "$repo_root/.venv/bin/python" \
    "$bounded_runner" \
    --label console-dependencies \
    --timeout-seconds "$dependency_timeout_seconds" \
    --no-progress-seconds "$stage_no_progress_seconds" \
    -- \
    npm --prefix "$repo_root/console" ci --no-audit --no-fund
}

path_digest() {
  run_bounded input-digest \
    "$repo_root/.venv/bin/python" \
    "$repo_root/scripts/automation/local-service-input-digest.py" \
    --paths-only \
    "$@"
}

legacy_digest() {
  run_bounded input-digest \
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
  for output in "$@"; do
    if [[ ! -s "$output" ]]; then
      echo "Console preparation stage did not produce required output: $name ($output)" >&2
      return 1
    fi
  done
  write_marker "$marker" "$digest"
  printf '%s service=console-preparation stage=%s event=completed\n' \
    "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')" "$name"
}

write_database_identity() {
  local target="$stage_marker_dir/database-volumes.sha256"
  local temporary
  local volume_inventory
  mkdir -p "$stage_marker_dir"
  umask 077
  temporary="$(mktemp "${target}.XXXXXX")"
  volume_inventory="$(mktemp "${target}.inventory.XXXXXX")"
  if ! run_bounded database-volume-identity docker volume inspect \
    --format '{{.Name}} {{.CreatedAt}}' \
    fdai-pgdata fdai-validation-pgdata > "$volume_inventory"; then
    cat "$volume_inventory" >&2
    rm -f "$temporary" "$volume_inventory"
    return 1
  fi
  sha256sum "$volume_inventory" | cut -d' ' -f1 > "$temporary"
  rm -f "$volume_inventory"
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
  label="$1"
  script="$2"
  set -a
  # shellcheck source=/dev/null
  source "$repo_root/.fdai/local-runtime.env"
  set +a
  run_bounded "$label" \
    env \
    PYTHONPATH="$repo_root/services/core-control-plane/src:$repo_root/packages/service-contracts/src" \
    "$repo_root/.venv/bin/python" "$script"
)

sync_entra_redirects() (
  set -a
  # shellcheck source=/dev/null
  source "$repo_root/console/.env.local"
  set +a
  for origin in http://localhost:5273 http://127.0.0.1:5273; do
    run_bounded entra-redirects \
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
  run_bounded local-state \
    bash "$repo_root/scripts/deployment/local/prepare-console-state.sh" --dependencies-ready
}

prepare_runtime_environment() {
  require_cloud_tools
  run_bounded runtime-environment \
    env -u AZURE_CONFIG_DIR \
    bash "$repo_root/scripts/deployment/azure/prepare-local-runtime-env.sh"
}

refresh_inventory() {
  require_cloud_tools
  run_runtime_projection \
    authoritative-inventory \
    "$repo_root/scripts/deployment/local/refresh-authoritative-inventory.py"
}

materialize_settings() {
  run_runtime_projection \
    authoritative-settings \
    "$repo_root/scripts/deployment/local/materialize-authoritative-settings.py"
}

materialize_catalogs() {
  run_runtime_projection \
    authoritative-catalogs \
    "$repo_root/scripts/deployment/local/materialize-authoritative-catalogs.py"
}

prepare_service_environments() {
  run_bounded operator-service-environment \
    bash "$repo_root/scripts/deployment/local/prepare-operator-service-env.sh"
  run_bounded independent-service-environments \
    bash "$repo_root/scripts/deployment/local/prepare-independent-service-envs.sh"
}

prepare_entra_redirects() {
  require_cloud_tools
  sync_entra_redirects
}

run_bounded service-migration-preflight \
  env PYTHONPATH="$repo_root/service-migrations" \
  "$repo_root/.venv/bin/python" \
  "$repo_root/service-migrations/migrate.py" \
  all validate

run_bounded local-dependencies \
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

console_dependency_inputs=(
  console/package.json
  console/package-lock.json
  pyproject.toml
  uv.lock
  evaluation-sdk/pyproject.toml
  benchmarks/cybergym/pyproject.toml
  benchmarks/sregym/pyproject.toml
  extensions/code-assurance/pyproject.toml
  extensions/cost-governance/pyproject.toml
  packages/service-contracts/pyproject.toml
  services/core-control-plane/pyproject.toml
  services/document-ingestion-api/pyproject.toml
  services/document-processing-worker/pyproject.toml
  services/isolated-executor/pyproject.toml
  services/operator-service/pyproject.toml
)
run_stage \
  console-dependencies \
  "$(path_digest "${console_dependency_inputs[@]}")" \
  run_dependency_install \
  "$repo_root/console/node_modules/.bin/vite" \
  "$repo_root/.venv/bin/fdai-document-processing-worker" \
  "$repo_root/.venv/bin/fdai-isolated-executor-service"

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
  services/core-control-plane/src/fdai/delivery/runtime_settings.py
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
