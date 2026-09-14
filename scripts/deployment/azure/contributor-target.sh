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

ensure_contributor_azd() {
  command -v azd >/dev/null 2>&1 && return 0
  local bin_dir="$HOME/.local/bin"
  local directory architecture digest command_name
  if [[ -x "$bin_dir/azd" ]]; then
    export PATH="$bin_dir:$PATH"
    return 0
  fi
  [[ ! -e "$bin_dir/azd" && ! -L "$bin_dir/azd" ]] || {
    target_log "ERROR: existing user azd is not executable; repair it before retrying"
    return 1
  }
  case "$(uname -sm)" in
    "Linux x86_64")
      architecture=amd64
      digest=ac7a6a8c47b0fae1d6ad17defd2f6b4ad8b7a97c4ef6ed52aa2cea2cee5d7144
      ;;
    "Linux aarch64" | "Linux arm64")
      architecture=arm64
      digest=a877d86ab362807df61fd8c98d2b7b7def186d7dd6f1390da3dfe25dcc8431fe
      ;;
    *)
      target_log "ERROR: automatic azd installation supports Linux x64 and ARM64; install azd manually"
      return 1
      ;;
  esac
  for command_name in curl sha256sum tar timeout mktemp install ln rm mkdir stat; do
    command -v "$command_name" >/dev/null 2>&1 || {
      target_log "ERROR: azd installation requires $command_name"
      return 1
    }
  done
  for directory in "$HOME/.local" "$bin_dir"; do
    [[ ! -L "$directory" ]] || {
      target_log "ERROR: azd installation refuses a symlinked user binary directory"
      return 1
    }
    [[ -e "$directory" ]] || mkdir -m 0755 -- "$directory" || return 1
    [[ -d "$directory" && -O "$directory" && -w "$directory" ]] \
      && (( (8#$(stat -c '%a' "$directory") & 0022) == 0 )) || {
      target_log "ERROR: azd installation requires an owned user directory without group or world write access"
      return 1
    }
  done
  target_log "installing checksum-pinned Azure Developer CLI 1.34.0 in the user binary directory"
  (
    temporary="$(mktemp -d "$bin_dir/.fdai-azd.XXXXXX")" || exit 1
    trap 'rm -rf -- "$temporary"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    archive="$temporary/azd.tar.gz"
    url="https://github.com/Azure/azure-dev/releases/download/azure-dev-cli_1.34.0/azd-linux-$architecture.tar.gz"
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
      --connect-timeout 15 --max-time 180 --output "$archive" "$url" || exit 1
    printf '%s  %s\n' "$digest" "$archive" | sha256sum --check --status || {
      target_log "ERROR: azd archive checksum verification failed"
      exit 1
    }
    tar -xzf "$archive" -C "$temporary" -- "azd-linux-$architecture" || exit 1
    install -m 0755 -- "$temporary/azd-linux-$architecture" "$temporary/azd" || exit 1
    timeout 15s "$temporary/azd" version >/dev/null || exit 1
    ln -- "$temporary/azd" "$bin_dir/azd" || exit 1
  ) || {
    target_log "ERROR: azd installation failed; deployment has not started"
    return 1
  }
  export PATH="$bin_dir:$PATH"
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
