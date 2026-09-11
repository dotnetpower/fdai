#!/usr/bin/env bash
#
# Resolve the local contributor deployment target from explicit automation
# inputs or the active Azure CLI account. This file is sourced by azd-up.sh.

target_log() { printf 'azd-up: %s\n' "$*" >&2; }

read_active_azure_account() {
  local payload
  command -v az >/dev/null 2>&1 || {
    target_log "ERROR: required command is unavailable: az"
    return 1
  }
  command -v timeout >/dev/null 2>&1 || {
    target_log "ERROR: required command is unavailable: timeout"
    return 1
  }
  if ! payload="$(timeout 30s az account show \
    --query '[id,tenantId]' --output tsv --only-show-errors 2>/dev/null)"; then
    target_log "ERROR: Azure CLI is not signed in; run 'az login' and retry"
    return 1
  fi

  mapfile -t ACTIVE_AZURE_ACCOUNT_FIELDS <<<"$payload"
  if ((${#ACTIVE_AZURE_ACCOUNT_FIELDS[@]} != 2)) \
    || [[ -z "${ACTIVE_AZURE_ACCOUNT_FIELDS[0]}" ]] \
    || [[ -z "${ACTIVE_AZURE_ACCOUNT_FIELDS[1]}" ]]; then
    target_log "ERROR: Azure CLI returned an incomplete active account; run 'az login' and retry"
    return 1
  fi
  [[ "${ACTIVE_AZURE_ACCOUNT_FIELDS[0]}" =~ ^[A-Za-z0-9._-]+$ ]] || {
    target_log "ERROR: Azure CLI returned an invalid active subscription id"
    return 1
  }
  [[ "${ACTIVE_AZURE_ACCOUNT_FIELDS[1]}" =~ ^[A-Za-z0-9._-]+$ ]] || {
    target_log "ERROR: Azure CLI returned an invalid active tenant id"
    return 1
  }
}

contributor_region_is_available() {
  local candidate="$1"
  local available
  if ! timeout 30s az account set \
    --subscription "$EXPECTED_SUBSCRIPTION" 2>/dev/null; then
    target_log "ERROR: could not select the reviewed Azure subscription"
    return 1
  fi
  if ! available="$(timeout 30s az account list-locations \
    --query "[?name == '$candidate'].name | [0]" \
    --output tsv --only-show-errors 2>/dev/null)"; then
    target_log "ERROR: could not verify Azure regions for the selected subscription"
    return 1
  fi
  if [[ "$available" != "$candidate" ]]; then
    target_log "Azure region '$candidate' is not available to the selected subscription"
    return 1
  fi
}

prompt_for_contributor_region() {
  local answer candidate
  local attempts=0
  while ((attempts < 3)); do
    attempts=$((attempts + 1))
    printf "azd-up: deploy public development Core in region '%s'? [y/N or enter another Azure region]: " \
      "$REGION" >&2
    if ! IFS= read -r answer; then
      target_log "ERROR: interactive confirmation ended before a decision was provided"
      return 1
    fi
    answer="${answer,,}"
    case "$answer" in
      "" | n | no)
        TARGET_STATUS=cancel
        return 0
        ;;
      y | yes)
        candidate="$REGION"
        ;;
      *)
        candidate="$answer"
        ;;
    esac
    if [[ ! "$candidate" =~ ^[a-z0-9]+$ ]]; then
      target_log "Azure region must be a lowercase region token such as koreacentral or westeurope"
      continue
    fi
    if contributor_region_is_available "$candidate"; then
      REGION="$candidate"
      CONFIRM=1
      return 0
    fi
  done
  target_log "ERROR: no valid Azure region was selected after 3 attempts"
  return 1
}

resolve_contributor_target() {
  local has_terminal="${1:-0}"
  local explicit_subscription="${AZURE_SUBSCRIPTION_ID:-}"
  local explicit_tenant="${AZURE_TENANT_ID:-}"
  local confirm_was_set=0

  [[ "$has_terminal" == "0" || "$has_terminal" == "1" ]] || {
    target_log "ERROR: contributor target terminal mode must be 0 or 1"
    return 1
  }
  if [[ -n "${FDAI_AZD_CONFIRM+x}" ]]; then
    confirm_was_set=1
  fi
  CONFIRM="${FDAI_AZD_CONFIRM:-0}"
  [[ "$CONFIRM" == "0" || "$CONFIRM" == "1" ]] || {
    target_log "ERROR: FDAI_AZD_CONFIRM must be 0 or 1"
    return 1
  }
  if { [[ -n "$explicit_subscription" ]] && [[ -z "$explicit_tenant" ]]; } \
    || { [[ -z "$explicit_subscription" ]] && [[ -n "$explicit_tenant" ]]; }; then
    target_log "ERROR: set both AZURE_SUBSCRIPTION_ID and AZURE_TENANT_ID, or leave both unset"
    return 1
  fi
  if [[ "$has_terminal" == "0" && -z "$explicit_subscription" ]]; then
    target_log "ERROR: non-interactive use requires AZURE_SUBSCRIPTION_ID and AZURE_TENANT_ID"
    return 1
  fi

  if [[ "$has_terminal" == "1" ]]; then
    read_active_azure_account || return 1
    if [[ -z "$explicit_subscription" ]]; then
      explicit_subscription="${ACTIVE_AZURE_ACCOUNT_FIELDS[0]}"
      explicit_tenant="${ACTIVE_AZURE_ACCOUNT_FIELDS[1]}"
    elif [[ "${ACTIVE_AZURE_ACCOUNT_FIELDS[1]}" != "$explicit_tenant" ]]; then
      target_log "ERROR: active Azure CLI tenant does not match AZURE_TENANT_ID"
      return 1
    fi
  fi

  EXPECTED_SUBSCRIPTION="$explicit_subscription"
  EXPECTED_TENANT="$explicit_tenant"
  REGION="${FDAI_AZURE_REGION:-${AZURE_LOCATION:-koreacentral}}"
  REGION="${REGION,,}"
  TARGET_HAS_TERMINAL="$has_terminal"
  TARGET_STATUS=run

  if [[ "$has_terminal" == "1" ]]; then
    target_log "Azure subscription: $EXPECTED_SUBSCRIPTION"
    target_log "Azure tenant: $EXPECTED_TENANT"
  fi
  if [[ "$has_terminal" == "1" && "$confirm_was_set" == "0" ]]; then
    prompt_for_contributor_region || return 1
  elif [[ "$has_terminal" == "1" && "$CONFIRM" == "1" ]]; then
    [[ "$REGION" =~ ^[a-z0-9]+$ ]] || {
      target_log "ERROR: FDAI_AZURE_REGION must be an Azure region token"
      return 1
    }
    contributor_region_is_available "$REGION" || return 1
  fi
}

ensure_contributor_azd_login() {
  local has_terminal="$1"
  local tenant="$2"
  if azd auth login --check-status >/dev/null 2>&1; then
    return 0
  fi
  if [[ "$has_terminal" != "1" ]]; then
    target_log "ERROR: Azure Developer CLI is not signed in; run 'azd auth login'"
    return 1
  fi
  target_log "Azure Developer CLI uses a separate local session; starting its sign-in now"
  azd auth login --tenant-id "$tenant" || {
    target_log "ERROR: Azure Developer CLI sign-in did not complete"
    return 1
  }
  azd auth login --check-status >/dev/null 2>&1 || {
    target_log "ERROR: Azure Developer CLI sign-in could not be verified"
    return 1
  }
}
