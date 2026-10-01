#!/usr/bin/env bash
# Install FDAI to Azure after interactive az login.
#
# Contributor source deployment: --source <checkout> --signing-key <key> builds everything from
# the checkout, then deploys it. Offline package: --offline-kit <package>.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
git -C "$repo_root" rev-parse --show-toplevel >/dev/null
cd "$repo_root"

# Prepare the locked environment of one selected checkout, which is not always this repository.
prepare_environment() {
  local root="$1"
  [[ -x "$root/.venv/bin/python" ]] && return 0
  command -v uv >/dev/null 2>&1 || {
    echo "fdai-up: uv is required to create the locked local environment" >&2
    exit 4
  }
  (cd "$root" && uv sync --frozen)
}

prepare_environment "$repo_root"

source_checkout=""
signing_key=""
forwarded=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) source_checkout="$2"; forwarded+=("$1" "$2"); shift 2 ;;
    --source=*) source_checkout="${1#--source=}"; forwarded+=("$1"); shift ;;
    --signing-key) signing_key="$2"; shift 2 ;;
    --signing-key=*) signing_key="${1#--signing-key=}"; shift ;;
    *) forwarded+=("$1"); shift ;;
  esac
done

cli_root="$repo_root"
fdaictl() {
  exec uv run --frozen --isolated --python "$cli_root/.venv/bin/python" \
    --project "$cli_root/packages/deployment-cli" \
    fdaictl provision azure "$@"
}

if [[ -n "$signing_key" ]]; then
  [[ -n "$source_checkout" ]] || {
    echo "fdai-up: --signing-key is used with --source for contributor deployment" >&2
    exit 64
  }
  for argument in "${forwarded[@]}"; do
    case "$argument" in
      --online | --offline-kit | --offline-kit=*)
        echo "fdai-up: contributor source deployment builds its own kit; remove $argument" >&2
        exit 64
        ;;
    esac
  done
  [[ "$signing_key" = /* ]] || signing_key="$PWD/$signing_key"
  checkout="$(cd "$source_checkout" && git rev-parse --show-toplevel)"
  commit="$(git -C "$checkout" rev-parse --short=9 HEAD)"
  out="${FDAI_CONTRIBUTOR_BUILD_DIR:-$HOME/.local/state/fdai/contributor}/build-$commit-$(date -u +%Y%m%dT%H%M%SZ)"
  install -d -m 0700 "$(dirname "$out")"
  echo "fdai-up: building deployment artifacts from $commit" >&2
  prepare_environment "$checkout"
  # The build resolves its source tree from the working directory, so select the checkout here.
  (
    cd "$checkout"
    "$checkout/scripts/deployment/release/build-standalone-deployment-kit.sh" \
      --out "$out" --signing-key "$signing_key"
  ) >&2
  kit="$(find "$out" -maxdepth 1 -name 'fdai-deployment-kit-*.tar.gz' -print -quit)"
  [[ -n "$kit" ]] || {
    echo "fdai-up: the contributor build produced no deployment artifact" >&2
    exit 3
  }
  deploy=()
  skip=0
  for argument in "${forwarded[@]}"; do
    if [[ "$skip" -eq 1 ]]; then skip=0; continue; fi
    case "$argument" in
      --source) skip=1 ;;
      --source=*) ;;
      *) deploy+=("$argument") ;;
    esac
  done
  cli_root="$checkout"
  # Entitlement comes only from the working checkout's secrets/integrity-signing-key.pem.
  fdaictl --offline-kit "$kit" "${deploy[@]}"
fi

selected=0
for argument in "${forwarded[@]}"; do
  if [[ "$argument" == "--online" || "$argument" == "--offline-kit" || "$argument" == --offline-kit=* || "$argument" == "--source" || "$argument" == --source=* ]]; then
    selected=1
    break
  fi
done
if [[ "$selected" -eq 0 ]]; then
  set -- --online "${forwarded[@]}"
else
  set -- "${forwarded[@]}"
fi
fdaictl "$@"
