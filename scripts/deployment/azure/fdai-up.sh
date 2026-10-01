#!/usr/bin/env bash
# Install FDAI to Azure from this checkout with one command.
#
#   git clone https://github.com/dotnetpower/fdai.git && fdai/scripts/deployment/azure/fdai-up.sh --region <region>
#
# Without a mode argument the command deploys this checkout (source mode). A signed offline
# package uses --offline-kit <package>. The command builds and signs no kit. When this
# checkout holds secrets/integrity-signing-key.pem, the deployment CLI selects the key-holder
# entitlement; otherwise the installation runs the 30-day Trial.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
git -C "$repo_root" rev-parse --show-toplevel >/dev/null
cd "$repo_root"

for argument in "$@"; do
  case "$argument" in
    --signing-key | --signing-key=*)
      echo "fdai-up: --signing-key was removed; run without it to deploy this checkout," \
        "or build a signed offline package with" \
        "scripts/deployment/release/build-standalone-deployment-kit.sh and pass --offline-kit" >&2
      exit 64
      ;;
  esac
done

if [[ ! -x "$repo_root/.venv/bin/python" ]]; then
  command -v uv >/dev/null 2>&1 || {
    echo "fdai-up: uv is required to create the locked local environment" >&2
    exit 4
  }
  uv sync --frozen
fi

selected=0
for argument in "$@"; do
  case "$argument" in
    --online | --offline-kit | --offline-kit=* | --source | --source=*)
      selected=1
      break
      ;;
  esac
done
if [[ "$selected" -eq 0 ]]; then
  set -- --source "$repo_root" "$@"
fi

exec uv run --frozen --isolated --python "$repo_root/.venv/bin/python" \
  --project "$repo_root/packages/deployment-cli" \
  fdaictl provision azure "$@"
