#!/usr/bin/env bash
# Plan or apply the exact pre-Foundation runner image without GitHub Actions.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
export PYTHONPATH="$root/packages/deployment-cli/src:$root/scripts/deployment/azure${PYTHONPATH:+:$PYTHONPATH}"
if [[ -x "$root/.venv/bin/python" ]]; then
	exec "$root/.venv/bin/python" "$root/scripts/deployment/azure/genesis_runner_image.py" "$@"
fi
exec uv run --frozen --project "$root/packages/deployment-cli" \
	python "$root/scripts/deployment/azure/genesis_runner_image.py" "$@"
