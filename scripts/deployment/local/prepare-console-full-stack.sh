#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root"

force_preparation=0
defer_authoritative_inventory=0
auth_mode="browser-entra"
while (( $# > 0 )); do
  case "$1" in
    --force)
      force_preparation=1
      shift
      ;;
    --auth-mode)
      if [[ $# -lt 2 ]]; then
        echo "Usage: $0 [--force] [--auth-mode browser-entra|azure-cli]" >&2
        exit 2
      fi
      auth_mode="$2"
      shift 2
      ;;
    --defer-authoritative-inventory)
      defer_authoritative_inventory=1
      shift
      ;;
    *)
      echo "Usage: $0 [--force] [--defer-authoritative-inventory] [--auth-mode browser-entra|azure-cli]" >&2
      exit 2
      ;;
  esac
done
if [[ "$auth_mode" != "browser-entra" && "$auth_mode" != "azure-cli" ]]; then
  echo "Usage: $0 [--force] [--defer-authoritative-inventory] [--auth-mode browser-entra|azure-cli]" >&2
  exit 2
fi
resolved_models_override="${FDAI_LOCAL_RESOLVED_MODELS_PATH:-}"
legacy_preparation_marker="$repo_root/.fdai/console-full-stack-preparation.sha256"
if [[ "$force_preparation" == "1" ]]; then
  rm -f "$legacy_preparation_marker"
fi

if [[ ! -x "$repo_root/.venv/bin/python" ]]; then
  echo "missing local Python environment: run uv sync --extra dev" >&2
  exit 1
fi
if [[ ! -f "$repo_root/console/.env.local" ]]; then
  echo "missing local Console environment: console/.env.local" >&2
  exit 1
fi

load_optional_console_setting() {
  local key="$1"
  local value
  local -a matches

  [[ ! -v "$key" ]] || return 0
  mapfile -t matches < <(grep -E "^${key}=" "$repo_root/console/.env.local" || true)
  if (( ${#matches[@]} > 1 )); then
    echo "duplicate local Console setting: $key" >&2
    return 1
  fi
  if (( ${#matches[@]} == 1 )); then
    value="${matches[0]#*=}"
    case "$key" in
      FDAI_LOCAL_NO_AZURE_DEPLOYMENT)
        export FDAI_LOCAL_NO_AZURE_DEPLOYMENT="$value"
        ;;
      FDAI_LOCAL_RESOURCE_GROUP)
        export FDAI_LOCAL_RESOURCE_GROUP="$value"
        ;;
      FDAI_LOCAL_KUBERNETES_LIFECYCLE)
        export FDAI_LOCAL_KUBERNETES_LIFECYCLE="$value"
        ;;
      FDAI_LOCAL_KUBERNETES_BINDINGS_PATH)
        export FDAI_LOCAL_KUBERNETES_BINDINGS_PATH="$value"
        ;;
      *)
        echo "unsupported local Console setting: $key" >&2
        return 1
        ;;
    esac
  fi
}

load_optional_console_setting FDAI_LOCAL_NO_AZURE_DEPLOYMENT
load_optional_console_setting FDAI_LOCAL_RESOURCE_GROUP
load_optional_console_setting FDAI_LOCAL_KUBERNETES_LIFECYCLE
load_optional_console_setting FDAI_LOCAL_KUBERNETES_BINDINGS_PATH
local_kubernetes_bindings_path="${FDAI_LOCAL_KUBERNETES_BINDINGS_PATH:-$repo_root/.fdai/local-kubernetes-bindings.json}"
if [[ -v FDAI_LOCAL_KUBERNETES_BINDINGS_PATH ]] && {
  [[ "$local_kubernetes_bindings_path" != /* ]] ||
    [[ ${#local_kubernetes_bindings_path} -gt 4096 ]] ||
    [[ "$local_kubernetes_bindings_path" == *$'\n'* ]] ||
    [[ "$local_kubernetes_bindings_path" == *$'\r'* ]]
}; then
  echo "FDAI_LOCAL_KUBERNETES_BINDINGS_PATH MUST be an absolute path" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "missing npm: install Node.js and npm before starting the Console" >&2
  exit 1
fi
if ! command -v opa >/dev/null 2>&1; then
  echo "missing OPA: install the Core image's OPA version on PATH before starting the Console" >&2
  exit 1
fi

stage_marker_dir="$repo_root/.fdai/console-preparation"
auth_mode_file="$repo_root/.fdai/local-console-auth-mode"
operator_env="$repo_root/.fdai/local-operator-service.env"
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
  .venv/bin/fdai-document-channel-intake
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
if [[ -n "$resolved_models_override" && -f "$resolved_models_override" ]]; then
  legacy_preparation_inputs+=("$resolved_models_override")
fi
if [[ -f "$local_kubernetes_bindings_path" ]]; then
  legacy_preparation_inputs+=("$local_kubernetes_bindings_path")
fi

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
  local label="$1"
  shift
  local digest
  local duration_ms
  local started_at_ns
  started_at_ns="$(date +%s%N)"
  digest="$(
    run_bounded "input-digest-$label" \
      "$repo_root/.venv/bin/python" \
      "$repo_root/scripts/automation/local-service-input-digest.py" \
      --paths-only \
      "$@"
  )"
  duration_ms=$((($(date +%s%N) - started_at_ns) / 1000000))
  printf 'service=local-input-digest stage=%s event=completed duration_ms=%s\n' \
    "$label" "$duration_ms" >&2
  printf '%s\n' "$digest"
}

configuration_digest() {
  local paths_digest="$1"
  shift
  {
    printf '%s\n' "$paths_digest"
    printf '%s\n' "$@"
  } | sha256sum | cut -d' ' -f1
}

legacy_digest() {
  local digest
  local duration_ms
  local started_at_ns
  started_at_ns="$(date +%s%N)"
  digest="$(
    run_bounded input-digest-legacy-preparation \
      "$repo_root/.venv/bin/python" \
      "$repo_root/scripts/automation/local-service-input-digest.py" \
      "$@"
  )"
  duration_ms=$((($(date +%s%N) - started_at_ns) / 1000000))
  printf 'service=local-input-digest stage=legacy-preparation event=completed duration_ms=%s\n' \
    "$duration_ms" >&2
  printf '%s\n' "$digest"
}

auth_mode_outputs_match() {
  local expected_flag
  if [[ "$auth_mode" == "azure-cli" ]]; then
    expected_flag=1
  else
    expected_flag=0
  fi
  [[ -f "$auth_mode_file" ]] || return 1
  [[ "$(<"$auth_mode_file")" == "$auth_mode" ]] || return 1
  [[ -f "$operator_env" ]] || return 1
  [[ "$(grep -Ec '^FDAI_OPERATOR_API_LOCAL_AZURE_CLI=' "$operator_env" || true)" == "1" ]] \
    || return 1
  [[ "$(grep -Fxc "FDAI_OPERATOR_API_LOCAL_AZURE_CLI=$expected_flag" "$operator_env" || true)" == "1" ]] \
    || return 1
  [[ "$(grep -Ec '^FDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM=' "$operator_env" || true)" == "1" ]] \
    || return 1
  [[ "$(grep -Fxc "FDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM=$expected_flag" "$operator_env" || true)" == "1" ]] \
    || return 1
}

can_reuse_legacy_preparation() {
  local current_digest="$1"
  local output
  [[ -s "${resolved_models_override:-$repo_root/resolved-models.json}" || -s "$repo_root/.fdai/resolved-models-vision.json" ]] || return 1
  [[ -f "$legacy_preparation_marker" ]] || return 1
  [[ "$(<"$legacy_preparation_marker")" == "$current_digest" ]] || return 1
  for output in "${required_outputs[@]}"; do
    [[ -s "$repo_root/$output" ]] || return 1
  done
  auth_mode_outputs_match || return 1
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
  if [[ "$name" == "service-environments" ]] && ! auth_mode_outputs_match; then
    return 1
  fi
  if [[ "$name" == "authoritative-inventory" ]] && ! \
    "$repo_root/.venv/bin/python" \
      "$repo_root/scripts/automation/developer-workflow.py" \
      local-services \
      --wait-seconds 0 \
      --only inventory-coverage >/dev/null; then
    return 1
  fi
  if [[ "$name" == "local-state" ]] && ! \
    run_bounded local-state-readiness \
      bash "$repo_root/scripts/deployment/local/prepare-console-state.sh" \
      --check >/dev/null 2>&1; then
    return 1
  fi
  for output in "$@"; do
    [[ -s "$output" ]] || return 1
  done
}

run_stage() {
  local name="$1"
  local digest="$2"
  local callback="$3"
  shift 3
  local duration_ms
  local marker="$stage_marker_dir/$name.sha256"
  local started_at_ns
  started_at_ns="$(date +%s%N)"
  if stage_reusable "$name" "$digest" "$@"; then
    duration_ms=$((($(date +%s%N) - started_at_ns) / 1000000))
    printf '%s service=console-preparation stage=%s event=reused duration_ms=%s\n' \
      "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')" "$name" "$duration_ms"
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
  duration_ms=$((($(date +%s%N) - started_at_ns) / 1000000))
  printf '%s service=console-preparation stage=%s event=completed duration_ms=%s\n' \
    "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')" "$name" "$duration_ms"
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
  if [[ "${FDAI_LOCAL_NO_AZURE_DEPLOYMENT:-0}" != "1" ]] && ! command -v "$terraform_bin" >/dev/null 2>&1; then
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
    bash "$repo_root/scripts/deployment/local/prepare-operator-service-env.sh" \
    --auth-mode "$auth_mode"
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
  current_legacy_digest="$(
    configuration_digest \
      "$(legacy_digest "${legacy_preparation_inputs[@]}")" \
      "auth-mode=$auth_mode" \
      "resolved-models-override=$resolved_models_override"
  )"
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
  "$(path_digest console-dependencies "${console_dependency_inputs[@]}")" \
  run_dependency_install \
  "$repo_root/console/node_modules/.bin/vite" \
  "$repo_root/.venv/bin/fdai-document-processing-worker" \
  "$repo_root/.venv/bin/fdai-isolated-executor-service"

require_cloud_tools
run_bounded local-model-settings \
  env -u AZURE_CONFIG_DIR \
  "$repo_root/.venv/bin/python" \
  "$repo_root/scripts/deployment/local/ensure-local-models.py" \
  --repo-root "$repo_root" \
  --resource-group "${FDAI_LOCAL_RESOURCE_GROUP:-}"

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
  scripts/deployment/local/cleanup-local-broker.py
  scripts/deployment/local/prepare-console-state.sh
  "$database_identity"
)
runtime_environment_inputs=(
  console/.env.local
  pyproject.toml
  uv.lock
  packages/service-contracts/src/fdai_service_contracts/semantic_turn.py
  scripts/deployment/azure/prepare-local-runtime-env.sh
  scripts/deployment/local/ensure-local-models.py
)
for optional_input in \
  resolved-models.json \
  .fdai/resolved-models-vision.json \
  infra/terraform.tfstate; do
  if [[ -f "$repo_root/$optional_input" ]]; then
    runtime_environment_inputs+=("$optional_input")
  fi
done
if [[ -n "$resolved_models_override" && -f "$resolved_models_override" ]]; then
  runtime_environment_inputs+=("$resolved_models_override")
fi
if [[ -f "$local_kubernetes_bindings_path" ]]; then
  runtime_environment_inputs+=("$local_kubernetes_bindings_path")
fi
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
  "$(path_digest local-state "${local_state_inputs[@]}")" \
  prepare_local_state
run_stage \
  runtime-environment \
  "$(configuration_digest \
    "$(path_digest runtime-environment "${runtime_environment_inputs[@]}")" \
    "kubernetes=${FDAI_LOCAL_KUBERNETES_LIFECYCLE:-0}" \
    "kubernetes-bindings-path=$local_kubernetes_bindings_path" \
    "teams-notifications=${FDAI_LOCAL_TEAMS_NOTIFICATION_ACTIVATION:-0}" \
    "no-azure-deployment=${FDAI_LOCAL_NO_AZURE_DEPLOYMENT:-0}" \
    "local-resource-group=${FDAI_LOCAL_RESOURCE_GROUP:-}" \
    "resolved-models-override=$resolved_models_override")" \
  prepare_runtime_environment \
  "$repo_root/.fdai/local-runtime.env"
if [[ "$defer_authoritative_inventory" == "1" ]]; then
  printf '%s service=console-preparation stage=authoritative-inventory event=deferred owner=inventory-reconciliation\n' \
    "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')"
else
  run_stage \
    authoritative-inventory \
    "$(path_digest authoritative-inventory "${inventory_inputs[@]}")" \
    refresh_inventory
fi
run_stage \
  authoritative-settings \
  "$(path_digest authoritative-settings "${settings_inputs[@]}")" \
  materialize_settings
run_stage \
  authoritative-catalogs \
  "$(path_digest authoritative-catalogs "${catalog_inputs[@]}")" \
  materialize_catalogs
run_stage \
  service-environments \
  "$(configuration_digest \
    "$(path_digest service-environments "${service_environment_inputs[@]}")" \
    "auth-mode=$auth_mode")" \
  prepare_service_environments \
  "$repo_root/.fdai/local-operator-service.env" \
  "$repo_root/.fdai/local-document-ingestion-api.env" \
  "$repo_root/.fdai/local-document-processing-worker.env" \
  "$repo_root/.fdai/local-isolated-executor.env"
run_stage \
  entra-redirects \
  "$(path_digest entra-redirects "${entra_inputs[@]}")" \
  prepare_entra_redirects

printf '%s service=console-preparation event=completed\n' \
  "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')"
