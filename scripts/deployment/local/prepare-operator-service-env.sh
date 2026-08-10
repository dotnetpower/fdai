#!/usr/bin/env bash
# Generate the private local environment consumed by the independent Operator Service.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
runtime_env="$repo_root/.fdai/local-runtime.env"
console_env="$repo_root/console/.env.local"
output_env="$repo_root/.fdai/local-operator-service.env"

if [[ ! -f "$runtime_env" ]]; then
  echo "missing prepared local runtime environment: $runtime_env" >&2
  exit 1
fi
if [[ ! -f "$console_env" ]]; then
  echo "missing local console environment: $console_env" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090 - both files are private workspace-generated environments.
source "$runtime_env"
# shellcheck disable=SC1090
source "$console_env"
set +a

: "${AZURE_TENANT_ID:?AZURE_TENANT_ID MUST be configured}"
: "${VITE_MSAL_TENANT_ID:?VITE_MSAL_TENANT_ID MUST be configured}"
: "${VITE_MSAL_API_SCOPE:?VITE_MSAL_API_SCOPE MUST be configured}"
: "${FDAI_DATABASE_URL:?FDAI_DATABASE_URL MUST be configured}"

if [[ "$AZURE_TENANT_ID" != "$VITE_MSAL_TENANT_ID" ]]; then
  echo "browser Entra tenant MUST match the prepared Azure tenant" >&2
  exit 1
fi
if [[ ! "$VITE_MSAL_API_SCOPE" =~ ^api://([^/]+)/[^/]+$ ]]; then
  echo "VITE_MSAL_API_SCOPE MUST use api://<audience>/<scope>" >&2
  exit 1
fi

api_audience="${BASH_REMATCH[1]}"
operator_database_url="$FDAI_DATABASE_URL"
if [[ "$operator_database_url" == *\?* ]]; then
  operator_database_url+="&options=-c%20role%3Dfdai_operator"
else
  operator_database_url+="?options=-c%20role%3Dfdai_operator"
fi

mkdir -p "$(dirname "$output_env")"
umask 077
temp_env="$(mktemp "${output_env}.XXXXXX")"
trap 'rm -f "$temp_env"' EXIT

grep -vE '^(FDAI_DATABASE_URL|FDAI_DATABASE_ROLE|FDAI_ENTRA_TENANT_ID|FDAI_API_AUDIENCE|FDAI_RBAC_(READERS|CONTRIBUTORS|APPROVERS|OWNERS|BREAK_GLASS)_GROUP_ID|FDAI_OPERATOR_SERVICE_(HOST|PORT|LOCAL_AZURE_NARRATOR)|FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS)=' \
  "$runtime_env" > "$temp_env" || true
{
  printf 'FDAI_DATABASE_URL=%s\n' "$operator_database_url"
  printf 'FDAI_DATABASE_ROLE=fdai_operator\n'
  printf 'FDAI_ENTRA_TENANT_ID=%s\n' "$VITE_MSAL_TENANT_ID"
  printf 'FDAI_API_AUDIENCE=%s\n' "$api_audience"
  # Browser App Roles are authoritative. Unmatchable, unique fallback slots keep
  # raw group claims from granting a local role when no App Role is present.
  printf 'FDAI_RBAC_READERS_GROUP_ID=local-app-role-reader\n'
  printf 'FDAI_RBAC_CONTRIBUTORS_GROUP_ID=local-app-role-contributor\n'
  printf 'FDAI_RBAC_APPROVERS_GROUP_ID=local-app-role-approver\n'
  printf 'FDAI_RBAC_OWNERS_GROUP_ID=local-app-role-owner\n'
  printf 'FDAI_RBAC_BREAK_GLASS_GROUP_ID=local-app-role-break-glass\n'
  printf 'FDAI_OPERATOR_SERVICE_HOST=127.0.0.1\n'
  printf 'FDAI_OPERATOR_SERVICE_PORT=8010\n'
  printf 'FDAI_OPERATOR_SERVICE_LOCAL_AZURE_NARRATOR=1\n'
  printf 'FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS=http://127.0.0.1:5273,http://localhost:5273\n'
} >> "$temp_env"

mv "$temp_env" "$output_env"
trap - EXIT
echo "prepared local independent Operator Service environment"
