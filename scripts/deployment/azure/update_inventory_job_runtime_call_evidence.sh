#!/usr/bin/env bash
set -euo pipefail

: "${ENABLE_RUNTIME_CALL_EVIDENCE:?ENABLE_RUNTIME_CALL_EVIDENCE is required}"
: "${REQUIRE_EXISTING_TARGET:=false}"
: "${TARGET_CONTAINER_NAME:?TARGET_CONTAINER_NAME is required}"
: "${TARGET_JOB_NAME:?TARGET_JOB_NAME is required}"
: "${TARGET_RESOURCE_GROUP:?TARGET_RESOURCE_GROUP is required}"
: "${TARGET_WORKSPACE_NAME:?TARGET_WORKSPACE_NAME is required}"

name_pattern='^[a-z][a-z0-9-]*[a-z0-9]$'
for value in \
  "$TARGET_CONTAINER_NAME" "$TARGET_JOB_NAME" "$TARGET_RESOURCE_GROUP" "$TARGET_WORKSPACE_NAME"; do
  if [[ ! "$value" =~ $name_pattern ]]; then
    echo "runtime-call evidence target names must be lowercase Azure resource names" >&2
    exit 2
  fi
done
for value in "$ENABLE_RUNTIME_CALL_EVIDENCE" "$REQUIRE_EXISTING_TARGET"; do
  [[ "$value" == "true" || "$value" == "false" ]] || {
    echo "runtime-call evidence boolean inputs must be true or false" >&2
    exit 2
  }
done
if [[ "$ENABLE_RUNTIME_CALL_EVIDENCE" == "false" ]]; then
  echo "Runtime-call evidence transition is disabled; declarative state remains authoritative."
  exit 0
fi

read_binding() {
  local name="$1"
  az containerapp job show \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --name "$TARGET_JOB_NAME" \
    --query "properties.template.containers[?name=='${TARGET_CONTAINER_NAME}'] | [0].env[?name=='${name}'] | [0].value" \
    --output tsv --only-show-errors
}

if ! current_value="$(read_binding FDAI_RUNTIME_CALL_EVIDENCE_ENABLED)"; then
  if [[ "$REQUIRE_EXISTING_TARGET" == "true" ]]; then
    echo "protected runtime-call evidence target is unavailable" >&2
    exit 1
  fi
  echo "Inventory Job does not exist yet; its declarative resource will create the binding."
  exit 0
fi
current_workspace="$(read_binding FDAI_MONITOR_WORKSPACE_ID)"
if [[ -n "$current_value" && "$current_value" != "1" ]]; then
  echo "current runtime-call evidence binding has an unsupported value" >&2
  exit 1
fi
workspace_id="$(
  az monitor log-analytics workspace show \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --workspace-name "$TARGET_WORKSPACE_NAME" \
    --query customerId --output tsv --only-show-errors
)"
guid_pattern='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
if [[ ! "$workspace_id" =~ $guid_pattern ]]; then
  echo "runtime-call evidence workspace identity is unavailable" >&2
  exit 1
fi
if [[ -n "$current_workspace" && "${current_workspace,,}" != "${workspace_id,,}" ]]; then
  echo "current runtime-call evidence workspace binding does not match the exact workspace" >&2
  exit 1
fi
if [[ "$current_value" == "1" && "${current_workspace,,}" == "${workspace_id,,}" ]]; then
  echo "Inventory Job runtime-call evidence bindings are already enabled."
  exit 0
fi

update_started=0
rollback() {
  local original_exit="$?"
  trap - ERR
  if (( update_started )); then
    local -a command=(
      az containerapp job update
      --resource-group "$TARGET_RESOURCE_GROUP"
      --name "$TARGET_JOB_NAME"
      --container-name "$TARGET_CONTAINER_NAME"
    )
    local -a restore=()
    local -a remove=()
    if [[ -n "$current_value" ]]; then
      restore+=("FDAI_RUNTIME_CALL_EVIDENCE_ENABLED=$current_value")
    else
      remove+=(FDAI_RUNTIME_CALL_EVIDENCE_ENABLED)
    fi
    if [[ -n "$current_workspace" ]]; then
      restore+=("FDAI_MONITOR_WORKSPACE_ID=$current_workspace")
    else
      remove+=(FDAI_MONITOR_WORKSPACE_ID)
    fi
    ((${#restore[@]} == 0)) || command+=(--set-env-vars "${restore[@]}")
    ((${#remove[@]} == 0)) || command+=(--remove-env-vars "${remove[@]}")
    command+=(--output none --only-show-errors)
    if ! "${command[@]}"; then
      echo "runtime-call evidence binding rollback failed" >&2
      exit 1
    fi
    if [[ "$(read_binding FDAI_RUNTIME_CALL_EVIDENCE_ENABLED)" != "$current_value" ]] ||
      [[ "$(read_binding FDAI_MONITOR_WORKSPACE_ID)" != "$current_workspace" ]]; then
      echo "runtime-call evidence binding rollback verification failed" >&2
      exit 1
    fi
    echo "Inventory Job runtime-call evidence binding rollback verified." >&2
  fi
  exit "$original_exit"
}
trap rollback ERR

update_started=1
az containerapp job update \
  --resource-group "$TARGET_RESOURCE_GROUP" \
  --name "$TARGET_JOB_NAME" \
  --container-name "$TARGET_CONTAINER_NAME" \
  --set-env-vars \
  FDAI_RUNTIME_CALL_EVIDENCE_ENABLED=1 \
  "FDAI_MONITOR_WORKSPACE_ID=$workspace_id" \
  --output none --only-show-errors
if [[ "$(read_binding FDAI_RUNTIME_CALL_EVIDENCE_ENABLED)" != "1" ]] ||
  [[ "${workspace_id,,}" != "$(read_binding FDAI_MONITOR_WORKSPACE_ID | tr '[:upper:]' '[:lower:]')" ]]; then
  echo "runtime-call evidence binding effect verification failed" >&2
  false
fi
update_started=0
trap - ERR
echo "Inventory Job runtime-call evidence binding effect verified."
