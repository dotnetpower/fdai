#!/usr/bin/env bash
set -euo pipefail

: "${DESIRED_IMAGE:?DESIRED_IMAGE is required}"
: "${REQUIRE_EXISTING_TARGET:=false}"
: "${TARGET_CONTAINER_NAME:?TARGET_CONTAINER_NAME is required}"
: "${TARGET_JOB_NAME:?TARGET_JOB_NAME is required}"
: "${TARGET_RESOURCE_GROUP:?TARGET_RESOURCE_GROUP is required}"

image_pattern='^[a-z0-9]+[.]azurecr[.]io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$'
name_pattern='^[a-z][a-z0-9-]*[a-z0-9]$'
for value in "$TARGET_CONTAINER_NAME" "$TARGET_JOB_NAME" "$TARGET_RESOURCE_GROUP"; do
  if [[ ! "$value" =~ $name_pattern ]]; then
    echo "analyzer target names must be lowercase Azure resource names" >&2
    exit 2
  fi
done
if [[ "$REQUIRE_EXISTING_TARGET" != "true" && "$REQUIRE_EXISTING_TARGET" != "false" ]]; then
  echo "REQUIRE_EXISTING_TARGET must be true or false" >&2
  exit 2
fi

read_image() {
  az containerapp job show \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --name "$TARGET_JOB_NAME" \
    --query "properties.template.containers[?name=='${TARGET_CONTAINER_NAME}'].image | [0]" \
    --output tsv
}

if ! current_image="$(read_image)"; then
  if [[ "$REQUIRE_EXISTING_TARGET" == "true" ]]; then
    echo "protected analyzer image target is unavailable" >&2
    exit 1
  fi
  echo "Analyzer Job does not exist yet; its declarative resource will create the protected image."
  exit 0
fi
if [[ ! "$DESIRED_IMAGE" =~ $image_pattern ]]; then
  echo "desired analyzer image must be an ACR reference pinned by sha256 digest" >&2
  exit 2
fi
if [[ ! "$current_image" =~ $image_pattern ]]; then
  echo "current analyzer image is not one digest-pinned ACR reference" >&2
  exit 1
fi
if [[ "$current_image" == "$DESIRED_IMAGE" ]]; then
  echo "Analyzer Job image already matches the protected digest."
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
      --image "$current_image" \
      --output none; then
      echo "analyzer image rollback failed" >&2
      exit 1
    fi
    if [[ "$(read_image)" != "$current_image" ]]; then
      echo "analyzer image rollback verification failed" >&2
      exit 1
    fi
    echo "Analyzer Job image rollback verified." >&2
  fi
  exit "$original_exit"
}
trap rollback ERR

update_started=1
az containerapp job update \
  --resource-group "$TARGET_RESOURCE_GROUP" \
  --name "$TARGET_JOB_NAME" \
  --container-name "$TARGET_CONTAINER_NAME" \
  --image "$DESIRED_IMAGE" \
  --output none
if [[ "$(read_image)" != "$DESIRED_IMAGE" ]]; then
  echo "analyzer image effect verification failed" >&2
  false
fi
update_started=0
trap - ERR
echo "Analyzer Job image effect verified at the protected digest."
