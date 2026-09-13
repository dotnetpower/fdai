#!/usr/bin/env bash
# Enroll the exact Foundation runner over Bastion; no token is accepted as an argument.
set -euo pipefail
umask 077

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
exec /bin/bash "$root/scripts/deployment/azure/genesis-python.sh" genesis_runner_enrollment "$@"
