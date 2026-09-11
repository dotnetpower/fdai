#!/usr/bin/env bash
# Supervise one exact-source private Azure deployment after interactive az login.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
git -C "$repo_root" rev-parse --show-toplevel >/dev/null
cd "$repo_root"
python="$repo_root/.venv/bin/python"
if [[ ! -x "$python" ]]; then
  command -v uv >/dev/null 2>&1 || {
    echo "fdai-up: uv is required to create the locked local environment" >&2
    exit 4
  }
  uv sync --frozen
fi
remote="$(git remote get-url origin)"
repository="${remote%.git}"
repository="${repository#https://github.com/}"
repository="${repository#ssh://git@github.com/}"
repository="${repository#git@github.com:}"
[[ "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || {
  echo "fdai-up: origin is not a supported GitHub repository" >&2
  exit 64
}

export PYTHONPATH="$repo_root/packages/deployment-cli/src:$repo_root/scripts/deployment/azure${PYTHONPATH:+:$PYTHONPATH}"
exec "$python" "$repo_root/scripts/deployment/azure/genesis_supervisor.py" \
  --repository "$repository" "$@"
