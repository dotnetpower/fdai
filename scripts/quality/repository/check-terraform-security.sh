#!/usr/bin/env bash
# Run the Terraform checks CI enforces so an infrastructure change fails locally, not after a
# 10-15 minute workflow round trip: fmt, Trivy misconfiguration, and Checkov.
#
# The commands and versions mirror the "Terraform fmt + validate + config tests" job in
# .github/workflows/ci.yml. A missing scanner is reported as skipped (never as passed) because
# CI remains the authoritative enforcement.
set -uo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root" || exit 1
workflow=".github/workflows/ci.yml"
status=0

pinned() {
  sed -n "s/^ *$1: \"\\([^\"]*\\)\".*/\\1/p" "$workflow" | head -n 1
}

note_version() {
  local tool="$1" actual="$2" expected="$3"
  if [[ -n "$expected" && "$actual" != *"$expected"* ]]; then
    printf 'terraform-security: NOTE %s is %s locally but CI pins %s\n' "$tool" "$actual" "$expected"
  fi
}

if command -v terraform >/dev/null 2>&1; then
  terraform fmt -check -recursive infra || status=1
else
  echo "terraform-security: SKIPPED terraform fmt (terraform not installed; CI enforces it)"
fi

if command -v trivy >/dev/null 2>&1; then
  note_version trivy "$(trivy --version | head -n 1)" "$(pinned TRIVY_VERSION)"
  trivy config --exit-code 1 --severity MEDIUM,HIGH,CRITICAL \
    --ignorefile infra/trivy-config-ignore.yaml infra >/dev/null || {
    trivy config --exit-code 1 --severity MEDIUM,HIGH,CRITICAL \
      --ignorefile infra/trivy-config-ignore.yaml infra
    status=1
  }
else
  echo "terraform-security: SKIPPED trivy config (trivy not installed; CI enforces it)"
fi

if command -v checkov >/dev/null 2>&1; then
  note_version checkov "$(checkov --version | head -n 1)" "$(pinned CHECKOV_VERSION)"
  checkov -d infra --quiet --compact --framework terraform || status=1
else
  echo "terraform-security: SKIPPED checkov (checkov not installed; CI enforces it)"
fi

exit "$status"
