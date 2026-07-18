#!/usr/bin/env bash
#
# dev-down.sh - stop the local dev stack, preserving volumes.
#
# To wipe volumes as well, run `make dev-nuke`.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "${repo_root}/infra/local"

docker compose down
echo "dev-down: stopped (volumes preserved)"
