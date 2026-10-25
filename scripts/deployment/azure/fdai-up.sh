#!/usr/bin/env bash
# Install FDAI to Azure from this checkout with one command.
#
#   git clone https://github.com/dotnetpower/fdai.git && fdai/scripts/deployment/azure/fdai-up.sh --region <region>
#
# Without a mode argument the command imports signed Hub images for this checkout.
# Explicit --source keeps source builds; --offline-kit keeps the signed offline path. When this
# checkout holds secrets/integrity-signing-key.pem, the deployment CLI selects the key-holder
# entitlement; otherwise the installation runs the 30-day Trial.
set -euo pipefail

caller_root="$PWD"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# Keep a caller-relative public key path meaningful after entering the checkout.
arguments=()
key_argument=0
for argument in "$@"; do
  if [[ "$key_argument" -eq 1 ]]; then
    [[ "$argument" = /* ]] || argument="$caller_root/$argument"
    key_argument=0
  elif [[ "$argument" = --hub-public-key ]]; then
    key_argument=1
  elif [[ "$argument" = --hub-public-key=* ]]; then
    key_path="${argument#*=}"
    [[ "$key_path" = /* ]] || key_path="$caller_root/$key_path"
    argument="--hub-public-key=$key_path"
  fi
  arguments+=("$argument")
done
set -- "${arguments[@]}"
if [[ -n "${FDAI_HUB_PUBLIC_KEY:-}" && "$FDAI_HUB_PUBLIC_KEY" != /* ]]; then
  export FDAI_HUB_PUBLIC_KEY="$caller_root/$FDAI_HUB_PUBLIC_KEY"
fi
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
    --online | --offline-kit | --offline-kit=* | --source | --source=* | --hub | --hub=*)
      selected=1
      break
      ;;
  esac
done
if [[ "$selected" -eq 0 ]]; then
  set -- --hub "$repo_root" "$@"
fi

exec uv run --frozen --isolated --python "$repo_root/.venv/bin/python" \
  --project "$repo_root/packages/deployment-cli" \
  fdaictl provision azure "$@"
