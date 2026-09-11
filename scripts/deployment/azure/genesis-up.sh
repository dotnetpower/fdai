#!/usr/bin/env bash
# Noninteractive policy-aware entry point for Azure subscription onboarding.

set -euo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
export PYTHONPATH="$ROOT/packages/deployment-cli/src:$HERE${PYTHONPATH:+:$PYTHONPATH}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
	exec "$ROOT/.venv/bin/python" "$HERE/genesis_orchestrator.py" "$@"
fi
exec uv run --frozen --project "$ROOT/packages/deployment-cli" \
	python "$HERE/genesis_orchestrator.py" "$@"
