#!/usr/bin/env bash
# Detect policy-forced private data services with bounded throwaway resources.
# This helper mutates only its tagged probe resource group and verifies cleanup.

set -euo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPECTED_SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:?set AZURE_SUBSCRIPTION_ID}"
EXPECTED_TENANT="${AZURE_TENANT_ID:?set AZURE_TENANT_ID}"
REGION="${REGION:-koreacentral}"
RUN_ID=""
OUTPUT_FILE=""
GROUP_CLEANUP_REQUIRED=0
KEY_VAULT_PURGE_REQUIRED=0
PROBE_COMPLETE=0
ACTIVE_PIDS=()
TEMPORARY_FILES=()

remember_child() {
  ACTIVE_PIDS+=("$1")
}

forget_child() {
  local completed="$1" retained=() pid
  for pid in "${ACTIVE_PIDS[@]}"; do
    [[ "$pid" == "$completed" ]] || retained+=("$pid")
  done
  ACTIVE_PIDS=("${retained[@]}")
}

wait_child() {
  local pid="$1" status=0
  wait "$pid" || status=$?
  forget_child "$pid"
  return "$status"
}

stop_children() {
  local pid
  ((${#ACTIVE_PIDS[@]} > 0)) || return 0
  for pid in "${ACTIVE_PIDS[@]}"; do
    kill -TERM -- "-$pid" >/dev/null 2>&1 || true
  done
  for pid in "${ACTIVE_PIDS[@]}"; do
    wait "$pid" >/dev/null 2>&1 || true
  done
  ACTIVE_PIDS=()
}

usage() {
  cat >&2 <<'EOF'
usage: preflight-policy-check.sh --run-id <12-32 lowercase hex> --output-file <absolute path>

Set FDAI_POLICY_PROBE_APPROVED=1 to authorize creation and verified cleanup of
the tagged throwaway resource group. Output contains no target identifiers.
EOF
}

while (($# > 0)); do
  case "$1" in
    --run-id)
      RUN_ID="${2:-}"
      shift 2
      ;;
    --output-file)
      OUTPUT_FILE="${2:-}"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 64
      ;;
  esac
done

[[ "${FDAI_POLICY_PROBE_APPROVED:-0}" == "1" ]] || {
  echo "policy probe requires FDAI_POLICY_PROBE_APPROVED=1" >&2
  exit 64
}
[[ "$RUN_ID" =~ ^[0-9a-f]{12,32}$ ]] || {
  echo "policy probe run id must be 12-32 lowercase hex characters" >&2
  exit 64
}
[[ "$REGION" =~ ^[a-z][a-z0-9]+$ ]] || {
  echo "policy probe region must be a lowercase Azure location token" >&2
  exit 64
}
[[ "$OUTPUT_FILE" == /* && ! -e "$OUTPUT_FILE" && ! -L "$OUTPUT_FILE" ]] || {
  echo "policy probe output must be a new absolute path" >&2
  exit 64
}
command -v setsid >/dev/null 2>&1 || {
  echo "policy probe requires setsid for bounded parallel process cleanup" >&2
  exit 4
}

/bin/bash "$HERE/../../scripts/deployment/azure/verify-azure-context.sh" \
  "$EXPECTED_SUBSCRIPTION" "$EXPECTED_TENANT" >/dev/null

suffix="${RUN_ID:0:12}"
resource_group="rg-fdai-policy-probe-$suffix"
key_vault="kvfdpr$suffix"
storage_account="stfdpr$suffix"

group_state() {
  local exists ownership
  if ! exists="$(timeout 30s az group exists \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --name "$resource_group" \
    --output tsv --only-show-errors 2>/dev/null)"; then
    printf 'unknown\n'
    return
  fi
  if [[ "${exists,,}" == "false" ]]; then
    printf 'absent\n'
    return
  fi
  if [[ "${exists,,}" != "true" ]]; then
    printf 'unknown\n'
    return
  fi
  if ! ownership="$(timeout 30s az group show \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --name "$resource_group" \
    --query "tags.\"fdai:managed\" == 'true' && tags.\"fdai:layer\" == 'policy-probe' && tags.\"fdai:run-id\" == '$RUN_ID' && location == '$REGION'" \
    --output tsv --only-show-errors 2>/dev/null)"; then
    printf 'unknown\n'
    return
  fi
  if [[ "${ownership,,}" == "true" ]]; then
    printf 'owned\n'
  else
    printf 'foreign\n'
  fi
}

cleanup_group() {
  local deadline state
  ((GROUP_CLEANUP_REQUIRED == 1)) || return 0
  deadline=$((SECONDS + 300))
  while ((SECONDS < deadline)); do
    state="$(group_state)"
    case "$state" in
      absent)
        GROUP_CLEANUP_REQUIRED=0
        return 0
        ;;
      owned)
        timeout 60s az group delete \
          --subscription "$EXPECTED_SUBSCRIPTION" \
          --name "$resource_group" \
          --yes --no-wait --only-show-errors >/dev/null 2>&1 || true
        if [[ "$(group_state)" == "absent" ]]; then
          GROUP_CLEANUP_REQUIRED=0
          return 0
        fi
        ;;
      foreign)
        echo "policy probe refused cleanup of a resource group without exact ownership tags" >&2
        return 1
        ;;
      unknown) ;;
    esac
    sleep 5
  done
  return 1
}

deleted_key_vault_state() {
  local counts expected_id output query
  expected_id="/subscriptions/$EXPECTED_SUBSCRIPTION/resourceGroups/$resource_group/providers/Microsoft.KeyVault/vaults/$key_vault"
  query="[length([?name == '$key_vault']), length([?name == '$key_vault'"
  query+=" && properties.location == '$REGION'"
  query+=" && properties.vaultId == '$expected_id'"
  query+=" && properties.tags.\"fdai:managed\" == 'true'"
  query+=" && properties.tags.\"fdai:layer\" == 'policy-probe'"
  query+=" && properties.tags.\"fdai:run-id\" == '$RUN_ID'])]"
  if ! output="$(timeout 30s az keyvault list-deleted \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --query "$query" \
    --output tsv --only-show-errors 2>/dev/null)"; then
    printf 'unknown\n'
    return
  fi
  readarray -t counts <<<"$output"
  case "${counts[0]:-}:${counts[1]:-}" in
    0:0) printf 'absent\n' ;;
    1:1) printf 'owned\n' ;;
    1:0) printf 'foreign\n' ;;
    *) printf 'unknown\n' ;;
  esac
}

live_key_vault_state() {
  local counts output query
  query="[?name == '$key_vault'] | [length(@), length([?"
  query+="location == '$REGION'"
  query+=" && tags.\"fdai:managed\" == 'true'"
  query+=" && tags.\"fdai:layer\" == 'policy-probe'"
  query+=" && tags.\"fdai:run-id\" == '$RUN_ID'])]"
  if ! output="$(timeout 30s az resource list \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --resource-group "$resource_group" \
    --resource-type Microsoft.KeyVault/vaults \
    --query "$query" \
    --output tsv --only-show-errors 2>/dev/null)"; then
    printf 'unknown\n'
    return
  fi
  readarray -t counts <<<"$output"
  case "${counts[0]:-}:${counts[1]:-}" in
    0:0) printf 'absent\n' ;;
    1:1) printf 'owned\n' ;;
    1:0) printf 'foreign\n' ;;
    *) printf 'unknown\n' ;;
  esac
}

cleanup_deleted_key_vault() {
  local deadline purge_requested=0 state
  ((KEY_VAULT_PURGE_REQUIRED == 1)) || return 0
  deadline=$((SECONDS + 300))
  while ((SECONDS < deadline)); do
    state="$(deleted_key_vault_state)"
    case "$state" in
      absent)
        if ((purge_requested == 1)); then
          KEY_VAULT_PURGE_REQUIRED=0
          return 0
        fi
        ;;
      owned)
        if ((purge_requested == 0)); then
          if ! timeout 60s az keyvault purge \
            --subscription "$EXPECTED_SUBSCRIPTION" \
            --name "$key_vault" \
            --location "$REGION" \
            --only-show-errors >/dev/null 2>&1; then
            return 1
          fi
          purge_requested=1
          continue
        fi
        ;;
      foreign)
        echo "policy probe refused purge of a Key Vault without exact ownership evidence" >&2
        return 1
        ;;
      unknown) ;;
    esac
    sleep 5
  done
  return 1
}

cleanup_probe() {
  local live_state
  if ((GROUP_CLEANUP_REQUIRED == 1 && KEY_VAULT_PURGE_REQUIRED == 0)); then
    live_state="$(live_key_vault_state)"
    case "$live_state" in
      owned) KEY_VAULT_PURGE_REQUIRED=1 ;;
      absent) ;;
      foreign)
        echo "policy probe refused cleanup of a Key Vault without exact ownership tags" >&2
        return 1
        ;;
      *) return 1 ;;
    esac
  fi
  cleanup_group || return 1
  cleanup_deleted_key_vault
}

on_exit() {
  local status=$?
  trap - EXIT
  stop_children
  if ((PROBE_COMPLETE == 0)) && ! cleanup_probe; then
    echo "policy probe cleanup did not converge" >&2
    status=4
  fi
  ((${#TEMPORARY_FILES[@]} == 0)) || rm -f -- "${TEMPORARY_FILES[@]}"
  exit "$status"
}
trap on_exit EXIT
trap 'stop_children; exit 130' INT
trap 'stop_children; exit 143' TERM

case "$(group_state)" in
  absent)
    case "$(deleted_key_vault_state)" in
      absent) ;;
      owned)
        KEY_VAULT_PURGE_REQUIRED=1
        if ! cleanup_deleted_key_vault; then
          echo "policy probe could not purge its exact prior Key Vault" >&2
          exit 4
        fi
        ;;
      foreign)
        echo "policy probe Key Vault name is held by an unrelated deleted resource" >&2
        exit 4
        ;;
      *)
        echo "policy probe could not verify that its Key Vault name is reusable" >&2
        exit 4
        ;;
    esac
    ;;
  owned)
    GROUP_CLEANUP_REQUIRED=1
    if ! cleanup_probe; then
      echo "policy probe could not clean its exact prior resource group" >&2
      exit 4
    fi
    ;;
  foreign)
    echo "policy probe resource group already exists; use a new run id" >&2
    exit 4
    ;;
  *)
    echo "policy probe could not verify that its resource group name is unused" >&2
    exit 4
    ;;
esac

GROUP_CLEANUP_REQUIRED=1
if ! timeout 60s az group create \
  --subscription "$EXPECTED_SUBSCRIPTION" \
  --name "$resource_group" \
  --location "$REGION" \
  --tags fdai:managed=true fdai:layer=policy-probe fdai:run-id="$RUN_ID" \
  --output none --only-show-errors >/dev/null; then
  echo "policy probe resource group creation did not complete" >&2
  exit 4
fi
if [[ "$(group_state)" != "owned" ]]; then
  echo "policy probe resource group ownership readback did not converge" >&2
  exit 4
fi

key_vault_created=false
storage_created=false
setsid timeout 120s az keyvault create \
  --subscription "$EXPECTED_SUBSCRIPTION" \
  --name "$key_vault" \
  --resource-group "$resource_group" \
  --location "$REGION" \
  --enable-rbac-authorization true \
  --public-network-access Enabled \
  --tags fdai:managed=true fdai:layer=policy-probe fdai:run-id="$RUN_ID" \
  --output none --only-show-errors >/dev/null 2>&1 &
key_vault_create_pid=$!
remember_child "$key_vault_create_pid"
setsid timeout 120s az storage account create \
  --subscription "$EXPECTED_SUBSCRIPTION" \
  --name "$storage_account" \
  --resource-group "$resource_group" \
  --location "$REGION" \
  --sku Standard_LRS \
  --kind StorageV2 \
  --public-network-access Enabled \
  --allow-shared-key-access true \
  --allow-blob-public-access false \
  --output none --only-show-errors >/dev/null 2>&1 &
storage_create_pid=$!
remember_child "$storage_create_pid"
if wait_child "$key_vault_create_pid"; then
  key_vault_created=true
  KEY_VAULT_PURGE_REQUIRED=1
fi
if wait_child "$storage_create_pid"; then
  storage_created=true
fi

route="incomplete"
reason_codes=()
key_vault_access="unknown"
storage_access="unknown"
storage_shared_key="unknown"
if [[ "$key_vault_created" != "true" ]]; then
  reason_codes+=(key_vault_probe_create_failed)
fi
if [[ "$storage_created" != "true" ]]; then
  reason_codes+=(storage_probe_create_failed)
fi
if [[ "$key_vault_created" == "true" && "$storage_created" == "true" ]]; then
  key_vault_posture_file="$(mktemp "$(dirname "$OUTPUT_FILE")/.policy-kv-XXXXXX")"
  storage_posture_file="$(mktemp "$(dirname "$OUTPUT_FILE")/.policy-storage-XXXXXX")"
  TEMPORARY_FILES+=("$key_vault_posture_file" "$storage_posture_file")
  setsid timeout 30s az keyvault show \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --name "$key_vault" \
    --resource-group "$resource_group" \
    --query properties.publicNetworkAccess \
    --output tsv --only-show-errors >"$key_vault_posture_file" 2>/dev/null &
  key_vault_posture_pid=$!
  remember_child "$key_vault_posture_pid"
  setsid timeout 30s az storage account show \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --name "$storage_account" \
    --resource-group "$resource_group" \
    --query '[publicNetworkAccess,allowSharedKeyAccess]' \
    --output tsv --only-show-errors >"$storage_posture_file" 2>/dev/null &
  storage_posture_pid=$!
  remember_child "$storage_posture_pid"
  if ! wait_child "$key_vault_posture_pid"; then
    printf 'unknown\n' >"$key_vault_posture_file"
  fi
  if ! wait_child "$storage_posture_pid"; then
    printf 'unknown\nunknown\n' >"$storage_posture_file"
  fi
  key_vault_access="$(<"$key_vault_posture_file")"
  readarray -t storage_posture <"$storage_posture_file"
  rm -f -- "$key_vault_posture_file" "$storage_posture_file"
  TEMPORARY_FILES=()
  storage_access="${storage_posture[0]:-unknown}"
  storage_shared_key="${storage_posture[1]:-unknown}"
  if [[ "${key_vault_access,,}" == "disabled" ]]; then
    reason_codes+=(key_vault_public_access_forced_disabled)
  fi
  if [[ "${storage_access,,}" == "disabled" ]]; then
    reason_codes+=(storage_public_access_forced_disabled)
  fi
  if [[ "${storage_shared_key,,}" == "false" ]]; then
    reason_codes+=(storage_shared_key_forced_disabled)
  fi
  if ((${#reason_codes[@]} > 0)); then
    route="private-runner"
  elif [[ "${key_vault_access,,}" == "enabled" \
    && "${storage_access,,}" == "enabled" \
    && "${storage_shared_key,,}" == "true" ]]; then
    route="public-dev"
  else
    reason_codes+=(policy_probe_readback_indeterminate)
  fi
fi

cleanup_complete=false
if cleanup_probe; then
  cleanup_complete=true
else
  reason_codes+=(policy_probe_cleanup_failed)
  route="incomplete"
fi
PROBE_COMPLETE=1

reasons="$(printf '%s\n' "${reason_codes[@]:-}")"
ROUTE="$route" REASONS="$reasons" OUTPUT_FILE="$OUTPUT_FILE" \
KEY_VAULT_CREATED="$key_vault_created" STORAGE_CREATED="$storage_created" \
CLEANUP_COMPLETE="$cleanup_complete" python3 - <<'PY'
import json
import os
import stat
from pathlib import Path

destination = Path(os.environ["OUTPUT_FILE"])
parent = destination.parent
details = parent.lstat()
if (
  not stat.S_ISDIR(details.st_mode)
  or stat.S_IMODE(details.st_mode) != 0o700
  or details.st_uid != os.geteuid()
):
    raise SystemExit("policy probe output directory must use mode 0700")
reasons = [value for value in os.environ["REASONS"].splitlines() if value]
payload = {
    "schema_version": "fdai.azure-policy-route.v1",
    "state": "ready" if os.environ["ROUTE"] != "incomplete" else "incomplete",
    "route": os.environ["ROUTE"],
    "reason_codes": reasons,
    "key_vault_probe_created": os.environ["KEY_VAULT_CREATED"] == "true",
    "storage_probe_created": os.environ["STORAGE_CREATED"] == "true",
    "cleanup_complete": os.environ["CLEANUP_COMPLETE"] == "true",
    "mutation_performed": True,
    "subscription_ready": False,
}
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
descriptor = os.open(destination, flags, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
    json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
    stream.write("\n")
    stream.flush()
    os.fsync(stream.fileno())
PY

printf 'policy route: %s; cleanup: %s\n' "$route" "$cleanup_complete"
[[ "$route" != "incomplete" ]] || exit 4
