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
  terraform -chdir="$peer_root" init \
    -input=false \
    -lockfile=readonly \
    -backend-config="resource_group_name=$STATE_RESOURCE_GROUP" \
    -backend-config="storage_account_name=$STATE_STORAGE_ACCOUNT" \
    -backend-config="container_name=$STATE_CONTAINER" \
    -backend-config="key=$backend_key" \
    -backend-config="use_azuread_auth=true"
  terraform -chdir="$peer_root" state pull >"$raw_dir/$peer.json"
  rm -rf -- "$peer_root/.terraform"
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
