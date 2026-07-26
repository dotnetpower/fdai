#!/usr/bin/env bash
#
# azd-up.sh - guarded turnkey provisioning wrapper over `azd` + Terraform.
#
# Purpose: give operators a one-command path to stand up the FDAI minimum-set
# inventory (docs/roadmap/deployment/deploy-and-onboard.md) while making an accidental
# apply impossible. The default action is a NON-mutating preview.
#
# Behavior:
#   - Preflight: verify `azd` is installed, an azd environment is selected,
#     and the caller is logged in to Azure.
#   - Default (safe): run `azd provision --preview` - shows the Terraform plan,
#     applies nothing.
#   - Real provision: only when FDAI_AZD_CONFIRM=1 is set in the environment,
#     run `azd up`. This second gate prevents an unintended deploy.
#
# The script never stores or echoes secrets. Environment-specific values come
# from the azd environment, never from this repo.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPECTED_SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:?set AZURE_SUBSCRIPTION_ID}"
EXPECTED_TENANT="${AZURE_TENANT_ID:?set AZURE_TENANT_ID}"

log() { printf 'azd-up: %s\n' "$*" >&2; }
fail() { log "ERROR: $*"; exit 1; }

command -v azd >/dev/null 2>&1 || fail "azd (Azure Developer CLI) is not installed"

# An azd environment must be selected so subscription/region are explicit.
if ! azd env list >/dev/null 2>&1; then
  fail "no azd environment. Run: azd env new <name>"
fi

AZD_SUBSCRIPTION="$(azd env get-value AZURE_SUBSCRIPTION_ID --no-prompt 2>/dev/null || true)"
if [[ -z "$AZD_SUBSCRIPTION" || "$AZD_SUBSCRIPTION" != "$EXPECTED_SUBSCRIPTION" ]]; then
  fail "selected azd environment does not match AZURE_SUBSCRIPTION_ID"
fi

"$HERE/verify-azure-context.sh" "$EXPECTED_SUBSCRIPTION" "$EXPECTED_TENANT"

# Confirm an Azure login exists (azd uses the same auth as az).
if ! azd auth login --check-status >/dev/null 2>&1; then
  fail "not logged in. Run: azd auth login"
fi

if [[ "${FDAI_AZD_CONFIRM:-0}" == "1" ]]; then
  log "FDAI_AZD_CONFIRM=1 set - running 'azd up' (this provisions real resources)"
  exec azd up
fi

log "safe mode: running 'azd provision --preview' (no changes applied)"
log "to actually provision, re-run with FDAI_AZD_CONFIRM=1"
exec azd provision --preview
