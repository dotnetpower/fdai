#!/usr/bin/env bash
# Generate the private local environment for the standalone Operator channel edge.

set +x
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
runtime_env="$repo_root/.fdai/local-runtime.env"
provider_env="$repo_root/.fdai/local-channel-edge-input.env"
output_env="$repo_root/.fdai/local-channel-edge.env"

if [[ ! -f "$runtime_env" ]]; then
  echo "missing prepared local runtime environment: $runtime_env" >&2
  exit 1
fi
if [[ ! -f "$provider_env" ]]; then
  echo "missing private channel provider input: $provider_env" >&2
  exit 1
fi
provider_mode="$(stat -c '%a' "$provider_env")"
if (( 8#$provider_mode & 8#077 )); then
  echo "private channel provider input MUST NOT be readable by group or others" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090 - both files are private workspace-generated environments.
source "$runtime_env"
# shellcheck disable=SC1090
source "$provider_env"
set +a

: "${FDAI_DATABASE_URL:?FDAI_DATABASE_URL MUST be configured}"
: "${FDAI_KAFKA_BOOTSTRAP_SERVERS:?FDAI_KAFKA_BOOTSTRAP_SERVERS MUST be configured}"
: "${FDAI_SEMANTIC_TURN_REQUEST_TOPIC:?FDAI_SEMANTIC_TURN_REQUEST_TOPIC MUST be configured}"
: "${FDAI_SEMANTIC_TURN_PROJECTION_TOPIC:?FDAI_SEMANTIC_TURN_PROJECTION_TOPIC MUST be configured}"
: "${FDAI_CHANNEL_EDGE_ENABLED_CHANNELS:?FDAI_CHANNEL_EDGE_ENABLED_CHANNELS MUST be configured}"
: "${FDAI_CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON:?FDAI_CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON MUST be configured}"

operator_database_url="$FDAI_DATABASE_URL"
if [[ "$operator_database_url" == *\?* ]]; then
  operator_database_url+="&options=-c%20role%3Dfdai_operator"
else
  operator_database_url+="?options=-c%20role%3Dfdai_operator"
fi

write_value() {
  local name="$1"
  local value="$2"
  printf '%s=%q\n' "$name" "$value"
}

mkdir -p "$(dirname "$output_env")"
umask 077
temp_env="$(mktemp "${output_env}.XXXXXX")"
trap 'rm -f "$temp_env"' EXIT

{
  write_value FDAI_DATABASE_URL "$operator_database_url"
  write_value FDAI_DATABASE_ROLE fdai_operator
  write_value FDAI_EXECUTION_VENUE local
  write_value RUNTIME_ENV dev
  write_value FDAI_CHANNEL_EDGE_HOST 127.0.0.1
  write_value FDAI_CHANNEL_EDGE_PORT 8014
  write_value FDAI_KAFKA_BOOTSTRAP_SERVERS "$FDAI_KAFKA_BOOTSTRAP_SERVERS"
  write_value FDAI_SEMANTIC_TURN_REQUEST_TOPIC "$FDAI_SEMANTIC_TURN_REQUEST_TOPIC"
  write_value FDAI_SEMANTIC_TURN_PROJECTION_TOPIC "$FDAI_SEMANTIC_TURN_PROJECTION_TOPIC"
  if [[ -n "${FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC:-}" ]]; then
    write_value FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC "$FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC"
  fi
  write_value FDAI_CHANNEL_EDGE_ENABLED_CHANNELS "$FDAI_CHANNEL_EDGE_ENABLED_CHANNELS"
  write_value FDAI_CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON "$FDAI_CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON"
  for name in \
    FDAI_SLACK_SIGNING_SECRET \
    FDAI_SLACK_BOT_TOKEN \
    FDAI_SLACK_TEAM_ID \
    FDAI_SLACK_PRINCIPAL_MAP_JSON \
    FDAI_TEAMS_APPLICATION_ID \
    FDAI_TEAMS_TENANT_ID \
    FDAI_TEAMS_PRINCIPAL_MAP_JSON \
    FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON \
    FDAI_TEAMS_JWKS_URL \
    FDAI_TEAMS_CLIENT_SECRET; do
    if [[ -n "${!name:-}" ]]; then
      write_value "$name" "${!name}"
    fi
  done
} > "$temp_env"

mv "$temp_env" "$output_env"
trap - EXIT
echo "prepared local standalone Operator channel-edge environment"
