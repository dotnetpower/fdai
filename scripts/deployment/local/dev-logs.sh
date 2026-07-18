#!/usr/bin/env bash
#
# dev-logs.sh - tail both services.
#
# Optional arg: a service name (`postgres` or `redpanda`) to filter.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "${repo_root}/infra/local"

if [[ $# -eq 0 ]]; then
  docker compose logs -f --tail=200
else
  docker compose logs -f --tail=200 "$@"
fi
