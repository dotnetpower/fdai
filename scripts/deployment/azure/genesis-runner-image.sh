#!/usr/bin/env bash
# Plan or apply the exact pre-Foundation runner image without GitHub Actions.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
exec /bin/bash "$root/scripts/deployment/azure/genesis-python.sh" genesis_runner_image "$@"
