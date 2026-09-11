#!/usr/bin/env bash
# Prepare the stable Azure CLI extensions used by connected Genesis access.

set -euo pipefail
umask 077

readonly BASTION_EXTENSION_VERSION="1.4.3"
readonly SSH_EXTENSION_VERSION="2.0.9"

fail() {
  printf 'prepare-genesis-access-tools: %s\n' "$1" >&2
  exit 4
}

run_quiet() {
  if ! "$@" >/dev/null 2>&1; then
    fail "azure_cli_prerequisite_failed"
  fi
}

ensure_extension() {
  local installed name version
  name="$1"
  version="$2"
  installed="$(
    az extension show --name "$name" --query version --output tsv \
      --only-show-errors 2>/dev/null || true
  )"
  if [[ "$installed" != "$version" ]]; then
    printf '         installing %s %s' "$name" "$version" >&2
    run_quiet az extension add \
      --name "$name" \
      --version "$version" \
      --upgrade \
      --yes \
      --only-show-errors
    printf ' done\n' >&2
  else
    printf '         %s %s already installed\n' "$name" "$version" >&2
  fi
  installed="$(
    az extension show --name "$name" --query version --output tsv \
      --only-show-errors 2>/dev/null || true
  )"
  [[ "$installed" == "$version" ]] || fail "azure_cli_extension_version_mismatch"
}

command -v az >/dev/null 2>&1 || fail "azure_cli_unavailable"

printf 'FDAI Genesis access-tool preparation\n' >&2
printf '[1/4] Disable implicit and preview extension installation\n' >&2
run_quiet az config set \
  extension.use_dynamic_install=no \
  extension.dynamic_install_allow_preview=false
dynamic_install="$(
  az config get extension.use_dynamic_install --query value --output tsv 2>/dev/null || true
)"
preview_install="$(
  az config get extension.dynamic_install_allow_preview \
    --query value --output tsv 2>/dev/null || true
)"
[[ "$dynamic_install" == "no" && "$preview_install" == "false" ]] || \
  fail "azure_cli_extension_policy_not_applied"

printf '[2/4] Prepare Azure Bastion commands\n' >&2
ensure_extension bastion "$BASTION_EXTENSION_VERSION"

printf '[3/4] Prepare Microsoft Entra SSH commands\n' >&2
ensure_extension ssh "$SSH_EXTENSION_VERSION"

printf '[4/4] Verify command parsers\n' >&2
run_quiet az network bastion create --help
run_quiet az network bastion ssh --help
run_quiet az ssh vm --help

printf 'ready: bastion=%s ssh=%s dynamic-install=no preview=false\n' \
  "$BASTION_EXTENSION_VERSION" "$SSH_EXTENSION_VERSION"
