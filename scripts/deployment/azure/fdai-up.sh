#!/usr/bin/env bash
# Run one signed-package Azure deployment after interactive az login.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
git -C "$repo_root" rev-parse --show-toplevel >/dev/null
cd "$repo_root"
if [[ ! -x "$repo_root/.venv/bin/python" ]]; then
  command -v uv >/dev/null 2>&1 || {
    echo "fdai-up: uv is required to create the locked local environment" >&2
    exit 4
  }
  uv sync --frozen
fi
source_mode=1
for argument in "$@"; do
  if [[ "$argument" == "--online" || "$argument" == "--offline-kit" || "$argument" == --offline-kit=* ]]; then
    source_mode=0
    break
  fi
done
if [[ "$source_mode" -eq 1 ]]; then
  set -- --online "$@"
fi

exec uv run --frozen --project "$repo_root/packages/deployment-cli" \
  fdaictl provision azure "$@"
