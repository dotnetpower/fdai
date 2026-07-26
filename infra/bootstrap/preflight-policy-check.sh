#!/usr/bin/env bash
# Preflight: detect whether the target tenant forces "private-everything" on
# Key Vault + storage (the policy posture that mandates the ops/hub runner
# path). Creates two throwaway probes, reads their effective network posture,
# deletes them, and prints a verdict. Read-only to your real resources.
#
# Usage: AZURE_SUBSCRIPTION_ID=<expected> AZURE_TENANT_ID=<expected> \
#   RG=rg-fdai-preflight REGION=koreacentral ./preflight-policy-check.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPECTED_SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:?set AZURE_SUBSCRIPTION_ID}"
EXPECTED_TENANT="${AZURE_TENANT_ID:?set AZURE_TENANT_ID}"

"$HERE/../../scripts/deployment/azure/verify-azure-context.sh" \
  "$EXPECTED_SUBSCRIPTION" "$EXPECTED_TENANT"

RG="${RG:-rg-fdai-preflight}"
REGION="${REGION:-koreacentral}"
KV="kvpre$(openssl rand -hex 4)"
SA="stpre$(openssl rand -hex 6 | cut -c1-16)"

cleanup() {
  az keyvault delete -n "$KV" -g "$RG" 2>/dev/null || true
  az keyvault purge -n "$KV" 2>/dev/null || true
  az storage account delete -n "$SA" -g "$RG" --yes 2>/dev/null || true
  az group delete -n "$RG" --yes --no-wait 2>/dev/null || true
}
trap cleanup EXIT

echo "== creating probe RG + resources (throwaway) =="
az group create -n "$RG" -l "$REGION" -o none

KV_PNA=$(az keyvault create -n "$KV" -g "$RG" -l "$REGION" \
  --query "properties.publicNetworkAccess" -o tsv 2>/dev/null || echo "CREATE_DENIED")

SA_JSON=$(az storage account create -n "$SA" -g "$RG" -l "$REGION" \
  --sku Standard_LRS --kind StorageV2 \
  --query "{pna:publicNetworkAccess, key:allowSharedKeyAccess}" -o json 2>/dev/null || echo '{}')
SA_PNA=$(echo "$SA_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin).get('pna','?'))" 2>/dev/null || echo "?")
SA_KEY=$(echo "$SA_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin).get('key','?'))" 2>/dev/null || echo "?")

echo
echo "== verdict =="
echo "Key Vault publicNetworkAccess : $KV_PNA"
echo "Storage publicNetworkAccess   : $SA_PNA"
echo "Storage allowSharedKeyAccess  : $SA_KEY"
echo
if [ "$KV_PNA" = "Disabled" ] || [ "$SA_PNA" = "Disabled" ] || [ "$SA_KEY" = "False" ]; then
  echo ">> PRIVATE-EVERYTHING tenant: you MUST deploy via the ops/hub runner"
  echo "   (infra/bootstrap + deploy-dev workflow). A laptop apply cannot write"
  echo "   KV secrets or reach a remote-state backend."
else
  echo ">> Unrestricted tenant: a direct laptop apply of infra/ works"
  echo "   (enable_private_networking can stay false)."
fi
