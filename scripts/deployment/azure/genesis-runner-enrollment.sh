#!/usr/bin/env bash
# Enroll the exact Foundation runner over Bastion; no token is accepted as an argument.
set -euo pipefail
umask 077

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
export PYTHONPATH="$root/packages/deployment-cli/src:$root/scripts/deployment/azure${PYTHONPATH:+:$PYTHONPATH}"
if [[ -x "$root/.venv/bin/python" ]]; then
	exec "$root/.venv/bin/python" "$root/scripts/deployment/azure/genesis_runner_enrollment.py" "$@"
fi
exec uv run --frozen --project "$root/packages/deployment-cli" \
	python "$root/scripts/deployment/azure/genesis_runner_enrollment.py" "$@"
