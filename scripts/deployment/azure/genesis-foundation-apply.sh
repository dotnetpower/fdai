#!/usr/bin/env bash
# Apply one exact signed Foundation plan locally; never plan or approve implicitly.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
export PYTHONPATH="$root/packages/deployment-cli/src:$root/scripts/deployment/azure${PYTHONPATH:+:$PYTHONPATH}"
if [[ -x "$root/.venv/bin/python" ]]; then
	exec "$root/.venv/bin/python" "$root/scripts/deployment/azure/genesis_foundation_apply.py" "$@"
fi
exec uv run --frozen --project "$root/packages/deployment-cli" \
	python "$root/scripts/deployment/azure/genesis_foundation_apply.py" "$@"
