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

preparation_marker="$repo_root/.fdai/console-full-stack-preparation.sha256"
preparation_inputs=(
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
    preparation_inputs+=("$optional_input")
  fi
done

preparation_digest() {
  "$repo_root/.venv/bin/python" \
    "$repo_root/scripts/automation/local-service-input-digest.py" \
    "${preparation_inputs[@]}"
}

can_reuse_preparation() {
  local current_digest="$1"
  local output
  [[ -f "$preparation_marker" ]] || return 1
  [[ "$(<"$preparation_marker")" == "$current_digest" ]] || return 1
  for output in "${required_outputs[@]}"; do
    [[ -s "$repo_root/$output" ]] || return 1
  done
  "$repo_root/.venv/bin/python" \
    "$repo_root/scripts/automation/developer-workflow.py" \
    local-services \
    --wait-seconds 0 >/dev/null
}

write_preparation_marker() {
  local digest="$1"
  local temporary
  mkdir -p "$(dirname "$preparation_marker")"
  umask 077
  temporary="$(mktemp "${preparation_marker}.XXXXXX")"
  trap 'rm -f "$temporary"' EXIT
  printf '%s\n' "$digest" > "$temporary"
  mv "$temporary" "$preparation_marker"
  trap - EXIT
}

current_digest="$(preparation_digest)"
if [[ "$force_preparation" == "0" ]] && can_reuse_preparation "$current_digest"; then
  printf '%s service=console-preparation event=reused\n' \
    "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')"
  exit 0
fi

rm -f "$preparation_marker"
terraform_bin="${FDAI_TERRAFORM_BIN:-terraform}"
az_bin="${FDAI_AZ_BIN:-az}"
if ! command -v "$terraform_bin" >/dev/null 2>&1; then
  echo "missing Terraform CLI: $terraform_bin" >&2
  exit 1
fi
if ! command -v "$az_bin" >/dev/null 2>&1; then
  echo "missing Azure CLI: $az_bin" >&2
  exit 1
fi

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

bash "$repo_root/scripts/deployment/local/prepare-console-state.sh"
env -u AZURE_CONFIG_DIR \
  bash "$repo_root/scripts/deployment/azure/prepare-local-runtime-env.sh"
run_runtime_projection "$repo_root/scripts/deployment/local/refresh-authoritative-inventory.py"
run_runtime_projection "$repo_root/scripts/deployment/local/materialize-authoritative-settings.py"
run_runtime_projection "$repo_root/scripts/deployment/local/materialize-authoritative-catalogs.py"
bash "$repo_root/scripts/deployment/local/prepare-operator-service-env.sh"
bash "$repo_root/scripts/deployment/local/prepare-independent-service-envs.sh"
sync_entra_redirects
write_preparation_marker "$(preparation_digest)"
