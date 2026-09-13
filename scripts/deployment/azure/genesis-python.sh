#!/usr/bin/env bash
# Launch fixed Genesis modules with the coordinator's installed interpreter or a real checkout.
set -euo pipefail
umask 077

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
module="${1:-}"
case "$module" in
  genesis_foundation_apply|genesis_foundation_state|genesis_runner_image|genesis_runner_enrollment) ;;
  *) echo "genesis-launch: unsupported module" >&2; exit 64 ;;
esac
shift
export PYTHONPATH="$root/packages/deployment-cli/src:$root/scripts/deployment/azure${PYTHONPATH:+:$PYTHONPATH}"
if [[ -n "${FDAI_GENESIS_PYTHON:-}" ]]; then
  [[ "$FDAI_GENESIS_PYTHON" = /* && -x "$FDAI_GENESIS_PYTHON" ]] || {
    echo "genesis-launch: selected installed interpreter is unavailable" >&2
    exit 3
  }
  exec "$FDAI_GENESIS_PYTHON" "$root/scripts/deployment/azure/$module.py" "$@"
fi
if [[ -x "$root/.venv/bin/python" ]]; then
  exec "$root/.venv/bin/python" "$root/scripts/deployment/azure/$module.py" "$@"
fi
if [[ -f "$root/packages/deployment-cli/pyproject.toml" ]]; then
  exec uv run --frozen --project "$root/packages/deployment-cli" \
    python "$root/scripts/deployment/azure/$module.py" "$@"
fi
echo "genesis-launch: run packaged stages through the installed fdaictl coordinator" >&2
exit 3
