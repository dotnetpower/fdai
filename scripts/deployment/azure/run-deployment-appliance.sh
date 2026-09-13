#!/usr/bin/env bash
# Start one artifact-offline Azure deployment from a signed-kit appliance image.
# FDAI_DEPLOYMENT_APPLIANCE_KIT selects the embedded signed archive.
# FDAI_DEPLOYMENT_APPLIANCE_WORK_DIR selects the private persistent state directory.
# Managed Identity mode requires an exact FDAI_DEPLOYMENT_APPLIANCE_MI_CLIENT_ID.
set -euo pipefail

kit_root="${FDAI_DEPLOYMENT_APPLIANCE_KIT:-/opt/fdai/kit.tar.gz}"
work_dir="${FDAI_DEPLOYMENT_APPLIANCE_WORK_DIR:-/var/lib/fdai/azure}"

[[ -f "$kit_root" && ! -L "$kit_root" ]] || {
  echo "fdai-appliance: embedded signed kit is unavailable" >&2
  exit 3
}
[[ "$work_dir" = /* ]] || {
  echo "fdai-appliance: work directory must be absolute" >&2
  exit 64
}
for tool in az fdaictl python3 scp ssh tar; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "fdai-appliance: required tool is unavailable: $tool" >&2
    exit 3
  }
done

if [[ "${FDAI_DEPLOYMENT_APPLIANCE_USE_MANAGED_IDENTITY:-0}" == "1" ]]; then
  : "${FDAI_DEPLOYMENT_APPLIANCE_MI_CLIENT_ID:?managed identity client ID is required}"
  az login --identity \
    --client-id "$FDAI_DEPLOYMENT_APPLIANCE_MI_CLIENT_ID" \
    --only-show-errors \
    --output none
elif ! az account show --only-show-errors --output none >/dev/null 2>&1; then
  [[ -t 0 && -t 1 ]] || {
    echo "fdai-appliance: Azure authentication is unavailable; run the image interactively" >&2
    exit 3
  }
  az login --use-device-code --only-show-errors --output none
fi

umask 077
mkdir -p -- "$work_dir"
chmod 0700 "$work_dir"
exec fdaictl provision azure \
  --offline-kit "$kit_root" \
  --work-dir "$work_dir" \
  "$@"
