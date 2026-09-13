#!/usr/bin/env bash
# Apply one exact signed Foundation plan locally; never plan or approve implicitly.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
exec /bin/bash "$root/scripts/deployment/azure/genesis-python.sh" genesis_foundation_apply "$@"
