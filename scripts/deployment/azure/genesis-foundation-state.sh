#!/usr/bin/env bash
# Migrate one exact Foundation state through the attested private runner.
set -euo pipefail
umask 077

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
exec /bin/bash "$root/scripts/deployment/azure/genesis-python.sh" genesis_foundation_state "$@"
