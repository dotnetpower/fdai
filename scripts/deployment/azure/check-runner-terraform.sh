#!/usr/bin/env bash
# Refuse a protected deploy runner whose Terraform predates the validated toolchain.
#
# Genesis-image runners pin an older Terraform whose azurerm backend rejects the managed-identity
# Azure CLI session that protected workflows use. Stop before any Azure, state, or provider work.
set -euo pipefail

readonly minimum_version="1.16.1"
readonly semver_pattern='^([0-9]+)\.([0-9]+)\.([0-9]+)(-[0-9A-Za-z.-]+)?$'

if ! command -v terraform >/dev/null 2>&1; then
  echo "check-runner-terraform: Terraform is not installed; this job can run no Terraform step."
  exit 0
fi
command -v jq >/dev/null 2>&1 || {
  echo "check-runner-terraform: required command is unavailable: jq" >&2
  exit 2
}

version="$(terraform version -json 2>/dev/null | jq -er '.terraform_version | select(type == "string")' 2>/dev/null)" || {
  echo "check-runner-terraform: the installed Terraform version cannot be read." >&2
  exit 1
}
[[ "$version" =~ $semver_pattern ]] || {
  echo "check-runner-terraform: the installed Terraform version is not a semantic version." >&2
  exit 1
}
actual=("${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "${BASH_REMATCH[3]}")
prerelease="${BASH_REMATCH[4]}"
[[ "$minimum_version" =~ $semver_pattern ]]
required=("${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "${BASH_REMATCH[3]}")

older=0
for index in 0 1 2; do
  if ((10#${actual[index]} < 10#${required[index]})); then
    older=1
    break
  fi
  if ((10#${actual[index]} > 10#${required[index]})); then
    break
  fi
  # A pre-release of the minimum version precedes that release.
  if ((index == 2)) && [[ -n "$prerelease" ]]; then
    older=1
  fi
done

if ((older)); then
  echo "check-runner-terraform: this runner has Terraform $version; protected workflows require $minimum_version or later." >&2
  echo "check-runner-terraform: Genesis-image runners pin an older toolchain. Run this job on a deploy runner built from the validated image, or raise the runner toolchain first." >&2
  exit 1
fi
echo "check-runner-terraform: Terraform $version meets the protected-workflow minimum $minimum_version."
