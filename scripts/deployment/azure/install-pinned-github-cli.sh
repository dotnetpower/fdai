#!/usr/bin/env bash
set -euo pipefail

: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
: "${GITHUB_PATH:?GITHUB_PATH is required}"

version="2.97.0"
archive_sha256="a2c9b8497e1f85b1ad0dfcb78b5a622e098801b8e461e459e88e1ee12f018112"
archive="gh_${version}_linux_amd64.tar.gz"
target="$RUNNER_TEMP/$archive"
install_dir="$RUNNER_TEMP/gh_${version}_linux_amd64/bin"

if [[ ! -x "$install_dir/gh" ]]; then
  curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
    --retry-all-errors --retry-max-time 180 --connect-timeout 5 --max-time 120 \
    "https://github.com/cli/cli/releases/download/v${version}/${archive}" \
    --output "$target"
  printf '%s  %s\n' "$archive_sha256" "$target" | sha256sum --check --strict
  tar -xzf "$target" -C "$RUNNER_TEMP"
fi

printf '%s\n' "$install_dir" >> "$GITHUB_PATH"
