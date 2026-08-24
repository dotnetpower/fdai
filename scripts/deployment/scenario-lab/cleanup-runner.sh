#!/usr/bin/env bash
set -euo pipefail

output_dir="${1:-}"
if [[ -z "$output_dir" || "$output_dir" != /* || "$output_dir" == "/" || ! -d "$output_dir" ]]; then
  echo "cleanup-runner: an existing absolute non-root output directory is required." >&2
  exit 2
fi

find "$output_dir" -type f -exec shred --force --remove {} +
find "$output_dir" -depth -type d -empty -delete
