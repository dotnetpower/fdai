#!/usr/bin/env bash
# Migrate one exact Foundation state through the attested private runner.
set -euo pipefail
umask 077

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
export PYTHONPATH="$root/packages/deployment-cli/src:$root/scripts/deployment/azure${PYTHONPATH:+:$PYTHONPATH}"
if [[ -x "$root/.venv/bin/python" ]]; then
	exec "$root/.venv/bin/python" "$root/scripts/deployment/azure/genesis_foundation_state.py" "$@"
fi
exec uv run --frozen --project "$root/packages/deployment-cli" \
	python "$root/scripts/deployment/azure/genesis_foundation_state.py" "$@"
