#!/usr/bin/env bash
# Run the Terraform checks CI enforces so an infrastructure change fails locally, not after a
# 10-15 minute workflow round trip: fmt, Trivy misconfiguration, and Checkov.
#
# The commands and versions mirror the "Terraform fmt + validate + config tests" job in
# .github/workflows/ci.yml. Missing or incompatible tools are environment faults (exit 125),
# never a successful security check.
set -uo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root" || exit 1
workflow=".github/workflows/ci.yml"
status=0

pinned() {
  sed -n "s/^ *$1: \"\\([^\"]*\\)\".*/\\1/p" "$workflow" | head -n 1
}

require_version() {
  local tool="$1" expected="$2" output actual
  if [[ ! "$expected" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    printf 'terraform-security: ENVIRONMENT_FAULT missing or invalid CI version pin for %s\n' "$tool" >&2
    return 125
  fi
  if ! output="$("$tool" --version 2>&1)"; then
    printf 'terraform-security: ENVIRONMENT_FAULT cannot determine %s version\n' "$tool" >&2
    return 125
  fi
  actual="${output%%$'\n'*}"
  if [[ "$tool" == trivy ]]; then
    actual="${actual#Version: }"
  fi
  if [[ ! "$actual" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ || "$actual" != "$expected" ]]; then
    printf 'terraform-security: ENVIRONMENT_FAULT %s must match CI version %s\n' "$tool" "$expected" >&2
    return 125
  fi
}

for tool in terraform trivy checkov; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'terraform-security: ENVIRONMENT_FAULT %s is not installed; install the CI toolchain\n' "$tool" >&2
    status=125
  fi
done
((status == 0)) || exit "$status"
require_version trivy "$(pinned TRIVY_VERSION)" || exit 125
require_version checkov "$(pinned CHECKOV_VERSION)" || exit 125

terraform fmt -check -recursive infra || status=1

if trivy_output="$(trivy config --exit-code 1 --severity MEDIUM,HIGH,CRITICAL \
  --ignorefile infra/trivy-config-ignore.yaml infra 2>&1)"; then
  :
else
  printf '%s\n' "$trivy_output" >&2
  status=1
fi

checkov -d infra --quiet --compact --framework terraform || status=1

exit "$status"
