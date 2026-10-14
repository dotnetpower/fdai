#!/usr/bin/env bash
# Run the Lifecycle Hub apply demo from the repository's development environment.
# Usage: lifecycle/demo/demo.sh [--work DIR] {prepare|publish RELEASE|run [options]}
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$root:$root/lifecycle/hub/src:$root/lifecycle/agent/src:$root/packages/deployment-cli/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$root"
exec uv run --no-sync python -m lifecycle.demo "$@"
