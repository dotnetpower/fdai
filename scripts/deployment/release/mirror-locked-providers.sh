#!/usr/bin/env bash
# Mirror all deployment roots into one provider directory without changing the bundle.
# Called by stage-offline-kit.sh inside its verified, sentinel-owned output directory.
# Usage: bash mirror-locked-providers.sh BUNDLE OUT TERRAFORM_BIN PLATFORM
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "provider-mirror: expected BUNDLE OUT TERRAFORM_BIN PLATFORM." >&2
  exit 2
fi
bundle="$1"
out="$2"
terraform_bin="$3"
platform="$4"
scratch="$out/mirror-src"
mirror="$out/mirror"
deadline=$((SECONDS + 3600))

run_terraform() {
  local budget="$1"
  shift
  local remaining=$((deadline - SECONDS))
  if (( remaining <= 0 )); then
    echo "provider-mirror: total deadline exceeded." >&2
    return 124
  fi
  if (( remaining < budget )); then
    budget="$remaining"
  fi
  timeout --signal=TERM --kill-after=15 "$budget" "$terraform_bin" "$@"
}

# Child modules use their caller's lock, not their standalone test locks.
roots=(
  infra
  infra/bootstrap
  infra/genesis-foundation
  infra/scenario-lab
  infra/services/core-control-plane
  infra/services/operator-service
  infra/services/document-ingestion-api
  infra/services/document-processing-worker
  infra/services/isolated-executor
)

# Check every root before invoking Terraform; never resolve an unlocked root.
for root in "${roots[@]}"; do
  lock="$bundle/$root/.terraform.lock.hcl"
  if [[ ! -f "$lock" || ! -s "$lock" || -L "$lock" ]]; then
    echo "provider-mirror: missing or unsafe dependency lock for $root." >&2
    exit 1
  fi
done

if [[ -e "$scratch" || -L "$scratch" || -e "$mirror" || -L "$mirror" ]]; then
  echo "provider-mirror: scratch and mirror directories must not already exist." >&2
  exit 1
fi
mkdir "$scratch"
trap 'rm -rf -- "$scratch"' EXIT
# Preserve the complete infra layout so local module references keep resolving.
cp -R "$bundle/infra" "$scratch/infra"
mkdir "$mirror"
for root in "${roots[@]}"; do
  echo "-- locked providers: $root"
  (
    cd "$scratch/$root"
    export TF_DATA_DIR="$PWD/.terraform"
    run_terraform 300 init -backend=false -input=false -lockfile=readonly >/dev/null
    run_terraform 600 providers mirror -lock-file=true -platform="$platform" "$mirror" >/dev/null
  )
done
