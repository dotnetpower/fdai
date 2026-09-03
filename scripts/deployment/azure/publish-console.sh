#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
terraform_dir="${1:-$repo_root/infra}"

: "${EXPECTED_AZURE_TENANT_ID:?EXPECTED_AZURE_TENANT_ID is required}"
: "${ENTRA_CONSOLE_SPA_CLIENT_ID:?ENTRA_CONSOLE_SPA_CLIENT_ID is required}"
: "${ENTRA_CONSOLE_API_SCOPE:?ENTRA_CONSOLE_API_SCOPE is required}"
: "${GITHUB_STEP_SUMMARY:?GITHUB_STEP_SUMMARY is required}"

if [[ ! "$ENTRA_CONSOLE_API_SCOPE" =~ ^api://[^/]+/[^/]+$ ]]; then
  echo "ENTRA_CONSOLE_API_SCOPE must use api://<audience>/<scope>" >&2
  exit 2
fi

hostname="${CONSOLE_DEFAULT_HOSTNAME:-}"
resource_id="${CONSOLE_STATIC_WEB_APP_ID:-}"
if [[ -z "$hostname" || -z "$resource_id" ]]; then
  hostname="$(terraform -chdir="$terraform_dir" output -raw console_default_hostname)"
  resource_id="$(terraform -chdir="$terraform_dir" output -raw console_static_web_app_id)"
fi
if [[ -z "$hostname" || -z "$resource_id" ]]; then
  echo "console Static Web App binding is unavailable from protected variables and Terraform state" >&2
  exit 1
fi
if [[ ! "$hostname" =~ ^[A-Za-z0-9.-]+\.azurestaticapps\.net$ ]]; then
  echo "console default hostname is invalid" >&2
  exit 2
fi
if [[ ! "$resource_id" =~ ^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.Web/staticSites/[^/]+$ ]]; then
  echo "console Static Web App resource id is invalid" >&2
  exit 2
fi
if [[ -n "${ARM_SUBSCRIPTION_ID:-}" ]]; then
  resource_subscription="$(cut -d/ -f3 <<<"$resource_id")"
  if [[ "${resource_subscription,,}" != "${ARM_SUBSCRIPTION_ID,,}" ]]; then
    echo "console Static Web App belongs to a different subscription" >&2
    exit 2
  fi
fi
observed_hostname="$(az rest --method get \
  --url "https://management.azure.com${resource_id}?api-version=2023-12-01" \
  --query properties.defaultHostname -o tsv)"
if [[ -z "$observed_hostname" || "${observed_hostname,,}" != "${hostname,,}" ]]; then
  echo "console Static Web App hostname does not match its resource id" >&2
  exit 2
fi

operator_api="$(terraform -chdir="$terraform_dir" output -raw operator_api_fqdn)"
ingestion_api="$(terraform -chdir="$terraform_dir" output -raw ingestion_gateway_fqdn)"

deployment_token="$(az rest --method post \
  --url "https://management.azure.com${resource_id}/listSecrets?api-version=2023-12-01" \
  --query properties.apiKey -o tsv)"
if [[ -z "$deployment_token" ]]; then
  echo "console deployment token is unavailable" >&2
  exit 1
fi
echo "::add-mask::$deployment_token"

export SWA_CLI_DEPLOYMENT_TOKEN="$deployment_token"
export VITE_OPERATOR_API_BASE_URL="${operator_api:+https://$operator_api}"
export VITE_INGESTION_API_BASE_URL="${ingestion_api:+https://$ingestion_api}"
export VITE_MSAL_CLIENT_ID="$ENTRA_CONSOLE_SPA_CLIENT_ID"
export VITE_MSAL_TENANT_ID="$EXPECTED_AZURE_TENANT_ID"
export VITE_MSAL_API_SCOPE="$ENTRA_CONSOLE_API_SCOPE"
export VITE_MANUAL_STUDIO_URL="https://$hostname/manuals"
trap 'unset SWA_CLI_DEPLOYMENT_TOKEN deployment_token' EXIT

npm --prefix "$repo_root/console" ci --no-audit --no-fund
npm --prefix "$repo_root/console" run build
python3 "$repo_root/scripts/deployment/azure/build_manual_studio_artifact.py" \
  "$repo_root/console/dist/manuals"
npx --yes @azure/static-web-apps-cli@2.0.10 deploy \
  "$repo_root/console/dist" --env production

entry_asset="$(
  DIST_INDEX="$repo_root/console/dist/index.html" python3 - <<'PY'
import os
import re
from pathlib import Path

body = Path(os.environ["DIST_INDEX"]).read_text(encoding="utf-8")
match = re.search(r'(?:src|href)="(/assets/[^"]+\.(?:js|css))"', body)
if match is None:
    raise SystemExit("console build has no hashed entry asset")
print(match.group(1))
PY
)"
remote_asset="$(mktemp)"
trap 'rm -f -- "$remote_asset"; unset SWA_CLI_DEPLOYMENT_TOKEN deployment_token' EXIT
curl --fail --silent --show-error --retry 12 --retry-delay 5 \
  --retry-all-errors --retry-max-time 120 --connect-timeout 5 --max-time 20 \
  "https://$hostname$entry_asset" --output "$remote_asset"
echo "$(sha256sum "$repo_root/console/dist${entry_asset}" | cut -d' ' -f1)  $remote_asset" \
  | sha256sum --check --status
for manual_file in catalog.json library.html; do
  curl --fail --silent --show-error --retry 12 --retry-delay 5 \
    --retry-all-errors --retry-max-time 120 --connect-timeout 5 --max-time 20 \
    "https://$hostname/manuals/$manual_file" --output "$remote_asset"
  echo "$(sha256sum "$repo_root/console/dist/manuals/$manual_file" | cut -d' ' -f1)  $remote_asset" \
    | sha256sum --check --status
done
curl --fail --silent --show-error --retry 6 --retry-delay 5 \
  --retry-all-errors --retry-max-time 60 --connect-timeout 5 --max-time 20 \
  "https://$hostname/ontology" --output /dev/null

{
  echo "Console: https://$hostname"
  echo "Manual Studio: https://$hostname/manuals/library.html"
  echo "VITE_OPERATOR_API_BASE_URL=${operator_api:+https://$operator_api}"
  echo "VITE_INGESTION_API_BASE_URL=${ingestion_api:+https://$ingestion_api}"
} >> "$GITHUB_STEP_SUMMARY"
