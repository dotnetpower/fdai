#!/usr/bin/env bash
set -euo pipefail

: "${ENABLE_RUNTIME_CALL_EVIDENCE:?ENABLE_RUNTIME_CALL_EVIDENCE is required}"
: "${REQUIRE_EXISTING_TARGET:=false}"
: "${TARGET_CONTAINER_NAME:?TARGET_CONTAINER_NAME is required}"
: "${TARGET_JOB_NAME:?TARGET_JOB_NAME is required}"
: "${TARGET_RESOURCE_GROUP:?TARGET_RESOURCE_GROUP is required}"

name_pattern='^[a-z][a-z0-9-]*[a-z0-9]$'
for value in "$TARGET_CONTAINER_NAME" "$TARGET_JOB_NAME" "$TARGET_RESOURCE_GROUP"; do
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
  az containerapp job show \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --name "$TARGET_JOB_NAME" \
    --query "properties.template.containers[?name=='${TARGET_CONTAINER_NAME}'] | [0].env[?name=='FDAI_RUNTIME_CALL_EVIDENCE_ENABLED'] | [0].value" \
    --output tsv --only-show-errors
}

if ! current_value="$(read_binding)"; then
  if [[ "$REQUIRE_EXISTING_TARGET" == "true" ]]; then
    echo "protected runtime-call evidence target is unavailable" >&2
    exit 1
  fi
  echo "Inventory Job does not exist yet; its declarative resource will create the binding."
  exit 0
fi
if [[ -n "$current_value" && "$current_value" != "1" ]]; then
  echo "current runtime-call evidence binding has an unsupported value" >&2
  exit 1
fi
if [[ "$current_value" == "1" ]]; then
  echo "Inventory Job runtime-call evidence binding is already enabled."
  exit 0
fi

update_started=0
rollback() {
  local original_exit="$?"
  trap - ERR
  if (( update_started )); then
    if ! az containerapp job update \
      --resource-group "$TARGET_RESOURCE_GROUP" \
      --name "$TARGET_JOB_NAME" \
      --container-name "$TARGET_CONTAINER_NAME" \
      --remove-env-vars FDAI_RUNTIME_CALL_EVIDENCE_ENABLED \
      --output none --only-show-errors; then
      echo "runtime-call evidence binding rollback failed" >&2
      exit 1
    fi
    if [[ -n "$(read_binding)" ]]; then
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
  --set-env-vars FDAI_RUNTIME_CALL_EVIDENCE_ENABLED=1 \
  --output none --only-show-errors
if [[ "$(read_binding)" != "1" ]]; then
  echo "runtime-call evidence binding effect verification failed" >&2
  false
fi
update_started=0
trap - ERR
echo "Inventory Job runtime-call evidence binding effect verified."
