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

hostname="$(terraform -chdir="$terraform_dir" output -raw console_default_hostname 2>/dev/null || true)"
resource_id="$(terraform -chdir="$terraform_dir" output -raw console_static_web_app_id 2>/dev/null || true)"
hostname="${hostname:-${CONSOLE_DEFAULT_HOSTNAME:-}}"
resource_id="${resource_id:-${CONSOLE_STATIC_WEB_APP_ID:-}}"
if [[ -z "$hostname" || -z "$resource_id" ]]; then
  echo "console Static Web App binding is unavailable from protected variables and Terraform state" >&2
  exit 1
fi
if [[ ! "$hostname" =~ ^[a-z0-9-]+([.][0-9]+)?[.]azurestaticapps[.]net$ ]]; then
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

resolve_service_fqdn() {
  local service="$1"
  local service_dir="$repo_root/infra/services/$service"
  : "${FDAI_DEPLOY_ENVIRONMENT:?FDAI_DEPLOY_ENVIRONMENT is required for independent service state}"
  : "${STATE_CONTAINER:?STATE_CONTAINER is required for independent service state}"
  : "${STATE_RESOURCE_GROUP:?STATE_RESOURCE_GROUP is required for independent service state}"
  : "${STATE_STORAGE_ACCOUNT:?STATE_STORAGE_ACCOUNT is required for independent service state}"
  local state_key="services/$service/$FDAI_DEPLOY_ENVIRONMENT.tfstate"
  terraform -chdir="$service_dir" init -reconfigure -input=false \
    -backend-config="resource_group_name=$STATE_RESOURCE_GROUP" \
    -backend-config="storage_account_name=$STATE_STORAGE_ACCOUNT" \
    -backend-config="container_name=$STATE_CONTAINER" \
    -backend-config="key=$state_key" \
    -backend-config="use_azuread_auth=true" >/dev/null
  terraform -chdir="$service_dir" output -json service \
    | jq -er '.fqdn | select(type == "string" and length > 0)'
}

resolve_service_url() {
  local gateway_output="$1"
  local gateway_environment="$2"
  local service_output="$3"
  local service="$4"
  local gateway_url service_fqdn
  gateway_url="$(terraform -chdir="$terraform_dir" output -raw "$gateway_output" 2>/dev/null || true)"
  gateway_url="${gateway_url:-${!gateway_environment:-}}"
  if [[ -n "$gateway_url" ]]; then
    if [[ ! "$gateway_url" =~ ^https://[a-z0-9]([a-z0-9.-]*[a-z0-9])?(/[a-z0-9/-]*)?$ ]]; then
      echo "$gateway_output is not a valid HTTPS base URL" >&2
      exit 2
    fi
    printf '%s\n' "${gateway_url%/}"
    return
  fi

  service_fqdn="$(terraform -chdir="$terraform_dir" output -raw "$service_output" 2>/dev/null || true)"
  service_fqdn="${service_fqdn:-$(resolve_service_fqdn "$service")}"
  if [[ ! "$service_fqdn" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?[.]azurecontainerapps[.]io$ ]]; then
    echo "independent service FQDN is invalid" >&2
    exit 2
  fi
  printf 'https://%s\n' "$service_fqdn"
}

operator_api_url="$(resolve_service_url \
  browser_gateway_operator_url BROWSER_GATEWAY_OPERATOR_URL operator_api_fqdn operator-service)"
ingestion_api_url="$(resolve_service_url \
  browser_gateway_ingestion_url BROWSER_GATEWAY_INGESTION_URL \
  ingestion_gateway_fqdn document-ingestion-api)"

verify_only="${FDAI_CONSOLE_VERIFY_ONLY:-0}"
if [[ "$verify_only" != 0 && "$verify_only" != 1 ]]; then
  echo "FDAI_CONSOLE_VERIFY_ONLY must be 0 or 1" >&2
  exit 2
fi
verify_service_contracts="${FDAI_CONSOLE_VERIFY_SERVICE_CONTRACTS:-1}"
if [[ "$verify_service_contracts" != 0 && "$verify_service_contracts" != 1 ]]; then
  echo "FDAI_CONSOLE_VERIFY_SERVICE_CONTRACTS must be 0 or 1" >&2
  exit 2
fi
deployment_token=""
if [[ "$verify_only" == 0 ]]; then
  deployment_token="$(az rest --method post \
    --url "https://management.azure.com${resource_id}/listSecrets?api-version=2023-12-01" \
    --query properties.apiKey -o tsv)"
  if [[ -z "$deployment_token" ]]; then
    echo "console deployment token is unavailable" >&2
    exit 1
  fi
  echo "::add-mask::$deployment_token"
  export SWA_CLI_DEPLOYMENT_TOKEN="$deployment_token"
fi
export VITE_OPERATOR_API_BASE_URL="$operator_api_url"
export VITE_INGESTION_API_BASE_URL="$ingestion_api_url"
export VITE_MSAL_CLIENT_ID="$ENTRA_CONSOLE_SPA_CLIENT_ID"
export VITE_MSAL_TENANT_ID="$EXPECTED_AZURE_TENANT_ID"
export VITE_MSAL_API_SCOPE="$ENTRA_CONSOLE_API_SCOPE"
export VITE_MANUAL_STUDIO_URL="https://$hostname/manuals"
trap 'unset SWA_CLI_DEPLOYMENT_TOKEN deployment_token' EXIT

console_directory="${CONSOLE_PREBUILT_DIRECTORY:-}"
prebuilt_console=0
if [[ -n "$console_directory" ]]; then
  if [[ "$console_directory" != /* || ! -d "$console_directory" || -L "$console_directory" ]]; then
    echo "CONSOLE_PREBUILT_DIRECTORY must be an absolute regular directory" >&2
    exit 2
  fi
  if [[ ! -f "$console_directory/index.html" || ! -f "$console_directory/fdai-config.js" ]]; then
    echo "prebuilt Console is incomplete" >&2
    exit 2
  fi
  if grep -Fq 'globalThis.__FDAI_CONSOLE_CONFIG__ = null' "$console_directory/fdai-config.js"; then
    echo "prebuilt Console runtime configuration is still a placeholder" >&2
    exit 2
  fi
  prebuilt_console=1
else
  if [[ "$verify_only" == 1 ]]; then
    echo "verify-only Console readback requires CONSOLE_PREBUILT_DIRECTORY" >&2
    exit 2
  fi
  npm --prefix "$repo_root/console" ci --no-audit --no-fund
  npm --prefix "$repo_root/console" run build
  python3 "$repo_root/scripts/deployment/azure/build_manual_studio_artifact.py" \
    "$repo_root/console/dist/manuals" \
    --base-url "$VITE_MANUAL_STUDIO_URL"
  console_directory="$repo_root/console/dist"
fi
if [[ "$verify_only" == 0 ]]; then
  npx --yes @azure/static-web-apps-cli@2.0.10 deploy \
    "$console_directory" --env production
fi

entry_asset="$(
  DIST_INDEX="$console_directory/index.html" python3 - <<'PY'
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
response_headers="${remote_asset}.headers"
response_body="${remote_asset}.body"
trap 'rm -f -- "$remote_asset" "$response_headers" "$response_body"; unset SWA_CLI_DEPLOYMENT_TOKEN deployment_token' EXIT
for published_file in index.html fdai-config.js "${entry_asset#/}"; do
  curl --fail --silent --show-error --retry 12 --retry-delay 5 \
    --retry-all-errors --retry-max-time 120 --connect-timeout 5 --max-time 20 \
    "https://$hostname/$published_file" --output "$remote_asset"
  echo "$(sha256sum "$console_directory/$published_file" | cut -d' ' -f1)  $remote_asset" \
    | sha256sum --check --status
done
curl --fail --silent --show-error --retry 6 --retry-delay 5 \
  --retry-all-errors --retry-max-time 60 --connect-timeout 5 --max-time 20 \
  "https://$hostname/ontology" --output "$remote_asset"
echo "$(sha256sum "$console_directory/index.html" | cut -d' ' -f1)  $remote_asset" \
  | sha256sum --check --status
if [[ "$prebuilt_console" == 0 ]]; then
  for manual_file in catalog.json library.html target-architecture.html; do
    curl --fail --silent --show-error --retry 12 --retry-delay 5 \
      --retry-all-errors --retry-max-time 120 --connect-timeout 5 --max-time 20 \
      "https://$hostname/manuals/$manual_file" --output "$remote_asset"
    echo "$(sha256sum "$console_directory/manuals/$manual_file" | cut -d' ' -f1)  $remote_asset" \
      | sha256sum --check --status
  done
fi

if [[ "$verify_service_contracts" == 0 ]]; then
  exit 0
fi

for health_url in "$operator_api_url/healthz" "$ingestion_api_url/healthz"; do
  curl --fail --silent --show-error --retry 6 --retry-delay 5 \
    --retry-all-errors --retry-max-time 60 --connect-timeout 5 --max-time 20 \
    "$health_url" --output /dev/null
done

preflight_status="$(curl --silent --show-error --connect-timeout 5 --max-time 20 \
  --request OPTIONS "$operator_api_url/audit" \
  --header "Origin: https://$hostname" \
  --header 'Access-Control-Request-Method: GET' \
  --header 'Access-Control-Request-Headers: authorization' \
  --dump-header "$response_headers" --output "$response_body" --write-out '%{http_code}')"
if [[ ! "$preflight_status" =~ ^2[0-9][0-9]$ ]]; then
  echo "Operator API browser authorization preflight failed" >&2
  exit 1
fi
if ! awk -v expected="https://$hostname" '
  BEGIN { IGNORECASE = 1 }
  {
    sub(/\r$/, "")
    if (tolower($1) == "access-control-allow-origin:" && $2 == expected) found = 1
  }
  END { exit(found ? 0 : 1) }
' "$response_headers"; then
  echo "Operator API preflight did not return the exact Console origin" >&2
  exit 1
fi

unauthenticated_status="$(curl --silent --show-error --connect-timeout 5 --max-time 20 \
  "$operator_api_url/audit" --output "$response_body" --write-out '%{http_code}')"
if [[ "$unauthenticated_status" != 401 ]]; then
  echo "Operator API did not deny an unauthenticated protected request" >&2
  exit 1
fi

entra_authorize_url="$(EXPECTED_AZURE_TENANT_ID="$EXPECTED_AZURE_TENANT_ID" \
  ENTRA_CONSOLE_SPA_CLIENT_ID="$ENTRA_CONSOLE_SPA_CLIENT_ID" \
  ENTRA_CONSOLE_API_SCOPE="$ENTRA_CONSOLE_API_SCOPE" \
  CONSOLE_ORIGIN="https://$hostname" python3 - <<'PY'
import os
from urllib.parse import urlencode

query = urlencode(
    {
        "client_id": os.environ["ENTRA_CONSOLE_SPA_CLIENT_ID"],
        "response_type": "code",
        "redirect_uri": os.environ["CONSOLE_ORIGIN"],
        "response_mode": "query",
        "scope": f"openid profile {os.environ['ENTRA_CONSOLE_API_SCOPE']}",
        "prompt": "none",
    }
)
print(f"https://login.microsoftonline.com/{os.environ['EXPECTED_AZURE_TENANT_ID']}/oauth2/v2.0/authorize?{query}")
PY
)"
entra_status="$(curl --silent --show-error --connect-timeout 5 --max-time 20 \
  "$entra_authorize_url" --dump-header "$response_headers" \
  --output "$response_body" --write-out '%{http_code}')"
if [[ "$entra_status" != 302 ]] || ! awk -v expected="https://$hostname" '
  BEGIN { IGNORECASE = 1 }
  {
    sub(/\r$/, "")
    if (tolower($1) == "location:" && index($2, expected) == 1) found = 1
  }
  END { exit(found ? 0 : 1) }
' "$response_headers"; then
  echo "Entra did not return to the configured Console redirect origin" >&2
  exit 1
fi

{
  echo "Console: https://$hostname"
  echo "Manual Studio: https://$hostname/manuals/library.html"
  echo "VITE_OPERATOR_API_BASE_URL=$operator_api_url"
  echo "VITE_INGESTION_API_BASE_URL=$ingestion_api_url"
} >> "$GITHUB_STEP_SUMMARY"
