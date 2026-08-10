#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 6 ]] || {
  echo "usage: capture_peer_states.sh SERVICE ENVIRONMENT TARGET_ROOT CONTROL_ROOT PHASE OUTPUT_ROOT" >&2
  exit 2
}

service="$1"
environment="$2"
target_root="$3"
control_root="$4"
phase="$5"
output_root="$6"

for name in STATE_RESOURCE_GROUP STATE_STORAGE_ACCOUNT STATE_CONTAINER; do
  [[ -n "${!name:-}" ]] || {
    echo "$name is required to capture peer state." >&2
    exit 1
  }
done

umask 077
rm -rf -- "$output_root"
raw_dir="$output_root/raw"
mkdir -p "$raw_dir"
trap 'rm -rf -- "$raw_dir"' EXIT

while IFS=$'\t' read -r peer terraform_root backend_key; do
  [[ "$peer" =~ ^[a-z0-9-]+$ && "$terraform_root" == infra/services/* ]] || {
    echo "peer state coordinate is invalid." >&2
    exit 1
  }
  peer_root="$target_root/$terraform_root"
  [[ -d "$peer_root" && "$backend_key" =~ ^[a-z0-9._/-]+$ ]] || {
    echo "peer state backend coordinate is invalid." >&2
    exit 1
  }
  timeout 60s az storage blob download \
    --account-name "$STATE_STORAGE_ACCOUNT" \
    --container-name "$STATE_CONTAINER" \
    --name "$backend_key" \
    --file "$raw_dir/$peer.json" \
    --auth-mode login \
    --only-show-errors \
    --output none
done < <(
  python3 "$control_root/peer_state.py" coordinates \
    --service "$service" \
    --environment "$environment"
)

python3 "$control_root/peer_state.py" capture \
  --service "$service" \
  --environment "$environment" \
  --phase "$phase" \
  --state-dir "$raw_dir" \
  --output "$output_root/manifest.json"
