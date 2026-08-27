#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
runtime_env="$repo_root/.fdai/local-runtime.env"

if [[ ! -f "$runtime_env" ]]; then
  echo "Local runtime environment is unavailable; run 'console: prepare full stack' first." >&2
  exit 2
fi

set -a
# Generated private environment is a trusted workspace input.
# shellcheck disable=SC1090
source "$runtime_env"
set +a

: "${FDAI_STATE_STORE_DSN:?Local runtime environment is missing FDAI_STATE_STORE_DSN}"
export FDAI_EXECUTION_VENUE=local
export FDAI_INVENTORY_DSN="${FDAI_INVENTORY_DSN:-$FDAI_STATE_STORE_DSN}"
export PYTHONPATH="$repo_root/services/core-control-plane/src:$repo_root/packages/service-contracts/src${PYTHONPATH:+:$PYTHONPATH}"

exec env -u AZURE_CONFIG_DIR \
  "$repo_root/.venv/bin/python" -m fdai.delivery.analyzer_tick_cli --loop
