#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root"

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
