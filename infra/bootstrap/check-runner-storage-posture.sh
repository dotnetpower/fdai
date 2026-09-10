#!/usr/bin/env bash
# Verify that the deploy runner still uses the reviewed local ephemeral OS disk.
set -euo pipefail

EXPECTED_SUBSCRIPTION="${1:?expected subscription is required}"
EXPECTED_TENANT="${2:?expected tenant is required}"
OPS_RESOURCE_GROUP="${3:?ops resource group is required}"
RUNNER_VM="${4:?runner VM name is required}"
EXPECTED_VM_SIZE="${5:?expected runner VM size is required}"
EXPECTED_PRINCIPAL_ID="${6:?expected runner principal id is required}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$HERE/../../scripts/deployment/azure/verify-azure-context.sh" \
  "$EXPECTED_SUBSCRIPTION" "$EXPECTED_TENANT"

runner_storage="$({
  az vm show \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --resource-group "$OPS_RESOURCE_GROUP" \
    --name "$RUNNER_VM" \
    --query '{vm_size:hardwareProfile.vmSize,option:storageProfile.osDisk.diffDiskSettings.option,placement:storageProfile.osDisk.diffDiskSettings.placement,managed_disk_id:storageProfile.osDisk.managedDisk.id,identity:identity}' \
    --output json \
    --only-show-errors
} 2>/dev/null)" || {
  echo "runner storage posture unavailable: Azure VM read failed." >&2
  exit 1
}

actual_vm_size="$(jq -r '.vm_size // ""' <<<"$runner_storage")"
diff_disk_option="$(jq -r '.option // ""' <<<"$runner_storage")"
diff_disk_placement="$(jq -r '.placement // ""' <<<"$runner_storage")"
managed_disk_id="$(jq -r '.managed_disk_id // ""' <<<"$runner_storage")"
identity_type="$(jq -r '.identity.type // ""' <<<"$runner_storage")"
identity_principal_ids="$(
  jq -c '[.identity.userAssignedIdentities // {} | to_entries[].value.principalId]' \
    <<<"$runner_storage"
)"

managed_disk_exists=false
if [[ -n "$managed_disk_id" ]]; then
  managed_disk_inventory="$({
    az disk list \
      --subscription "$EXPECTED_SUBSCRIPTION" \
      --resource-group "$OPS_RESOURCE_GROUP" \
      --query '[].id' \
      --output json \
      --only-show-errors
  } 2>/dev/null)" || {
    echo "runner storage posture unavailable: Azure disk inventory read failed." >&2
    exit 1
  }
  managed_disk_exists="$(
    jq -r --arg disk_id "$managed_disk_id" \
      'map(ascii_downcase) | index($disk_id | ascii_downcase) != null' \
      <<<"$managed_disk_inventory"
  )"
fi

posture_errors=()
[[ "$actual_vm_size" == "$EXPECTED_VM_SIZE" ]] || \
  posture_errors+=("VM size is not the reviewed value")
[[ "$diff_disk_option" == "Local" ]] || \
  posture_errors+=("OS disk is not ephemeral")
[[ "$diff_disk_placement" == "ResourceDisk" ]] || \
  posture_errors+=("ephemeral OS disk is not on ResourceDisk")
[[ "$managed_disk_exists" == "false" ]] || \
  posture_errors+=("a managed OS disk exists")
[[ "$identity_type" == "UserAssigned" ]] || \
  posture_errors+=("runner identity type is not UserAssigned-only")
[[ "$(jq 'length' <<<"$identity_principal_ids")" -eq 1 ]] || \
  posture_errors+=("runner does not have exactly one user-assigned identity")
[[ "$(jq -r '.[0] // "" | ascii_downcase' <<<"$identity_principal_ids")" == \
  "${EXPECTED_PRINCIPAL_ID,,}" ]] || \
  posture_errors+=("runner identity principal does not match the configured deploy principal")

if [[ "${#posture_errors[@]}" -gt 0 ]]; then
  printf 'runner storage posture drift detected: %s.\n' \
    "$(IFS='; '; echo "${posture_errors[*]}")" >&2
  echo "Recreate the runner through the reviewed blue/green bootstrap procedure; in-place disk repair is not supported." >&2
  exit 1
fi

echo "FDAI_RUNNER_STORAGE_POSTURE_OK vm_size=$actual_vm_size os_disk=ephemeral placement=$diff_disk_placement identity=stable-uami"
