#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || "$1" != "--auth-mode" \
  || ( "$2" != "browser-entra" && "$2" != "azure-cli" ) ]]; then
  echo "Usage: $0 --auth-mode browser-entra|azure-cli" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
auth_mode="$2"
cd "$repo_root"

git_dir="$(git rev-parse --path-format=absolute --git-dir)"
common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
if [[ "$git_dir" != "$common_dir" ]]; then
  echo "Full-stack restart is available only from the primary checkout." >&2
  exit 75
fi

bash "$repo_root/scripts/deployment/local/stop-console-services.sh"
bash "$repo_root/scripts/deployment/local/prepare-console-full-stack.sh" \
  --defer-authoritative-inventory \
  --auth-mode "$auth_mode"
exec bash "$repo_root/scripts/deployment/local/start-console-services.sh" \
  --auth-mode "$auth_mode"
