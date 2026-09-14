#!/usr/bin/env bash
# Generate the private local environment for the standalone Operator channel edge.

set +x
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
runtime_env="$repo_root/.fdai/local-runtime.env"
provider_env="$repo_root/.fdai/local-channel-edge-input.env"
output_env="$repo_root/.fdai/local-channel-edge.env"
intake_env="$repo_root/.fdai/local-document-channel-intake.env"

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
# Both files are private workspace-generated environments.
# shellcheck disable=SC1090
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
attachments_enabled="${FDAI_CHANNEL_ATTACHMENTS_ENABLED:-0}"
if [[ "$attachments_enabled" != "0" && "$attachments_enabled" != "1" ]]; then
  echo "FDAI_CHANNEL_ATTACHMENTS_ENABLED MUST be 0 or 1" >&2
  exit 1
fi
if [[ "$attachments_enabled" == "1" ]]; then
  for name in \
    FDAI_CHANNEL_ATTACHMENT_INTAKE_AUDIENCE \
    FDAI_CHANNEL_ATTACHMENT_CLIENT_ID \
    FDAI_CHANNEL_ATTACHMENT_TENANT_ID \
    FDAI_CHANNEL_ATTACHMENT_CLIENT_SECRET \
    FDAI_ENTRA_TENANT_ID \
    FDAI_CHANNEL_ATTACHMENT_COLLECTION_ID \
    FDAI_CHANNEL_ATTACHMENT_ACCESS_DESCRIPTOR_REF \
    FDAI_CHANNEL_ATTACHMENT_READER_GROUPS \
    FDAI_CHANNEL_ATTACHMENT_RETENTION_POLICY_VERSION; do
    if [[ -z "${!name:-}" ]]; then
      echo "$name MUST be configured when channel attachments are enabled" >&2
      exit 1
    fi
  done
fi

operator_database_url="$FDAI_DATABASE_URL"
if [[ "$operator_database_url" == *\?* ]]; then
  operator_database_url+="&options=-c%20role%3Dfdai_operator"
else
  operator_database_url+="?options=-c%20role%3Dfdai_operator"
fi
intake_database_url="$FDAI_DATABASE_URL"
if [[ "$intake_database_url" == *\?* ]]; then
  intake_database_url+="&options=-c%20role%3Dfdai_ingestion_api"
else
  intake_database_url+="?options=-c%20role%3Dfdai_ingestion_api"
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
  write_value FDAI_CHANNEL_ATTACHMENTS_ENABLED "$attachments_enabled"
  if [[ "$attachments_enabled" == "1" ]]; then
    write_value FDAI_CHANNEL_ATTACHMENT_INTAKE_ORIGIN http://127.0.0.1:8015
    write_value FDAI_CHANNEL_ATTACHMENT_INTAKE_AUDIENCE "$FDAI_CHANNEL_ATTACHMENT_INTAKE_AUDIENCE"
    write_value FDAI_CHANNEL_ATTACHMENT_CLIENT_ID "$FDAI_CHANNEL_ATTACHMENT_CLIENT_ID"
    write_value FDAI_CHANNEL_ATTACHMENT_TENANT_ID "$FDAI_CHANNEL_ATTACHMENT_TENANT_ID"
    write_value FDAI_CHANNEL_ATTACHMENT_CLIENT_SECRET "$FDAI_CHANNEL_ATTACHMENT_CLIENT_SECRET"
    write_value FDAI_CHANNEL_ATTACHMENT_SCRATCH_DIR /dev/shm/fdai-channel-attachment-scratch
    write_value FDAI_CHANNEL_ATTACHMENT_SCRATCH_ENCRYPTED 1
    write_value FDAI_CHANNEL_ATTACHMENT_MAX_CONTENT_BYTES "${FDAI_CHANNEL_ATTACHMENT_MAX_CONTENT_BYTES:-26214400}"
    for name in \
      FDAI_SLACK_FILES_INFO_URL \
      FDAI_SLACK_ATTACHMENT_METADATA_HOSTS_JSON \
      FDAI_SLACK_ATTACHMENT_DOWNLOAD_HOSTS_JSON \
      FDAI_TEAMS_ATTACHMENT_URL_TEMPLATE \
      FDAI_TEAMS_ATTACHMENT_AUDIENCE \
      FDAI_TEAMS_ATTACHMENT_HOSTS_JSON \
      FDAI_TEAMS_ATTACHMENT_AUDIENCES_JSON; do
      if [[ -n "${!name:-}" ]]; then
        write_value "$name" "${!name}"
      fi
    done
  fi
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
if [[ "$attachments_enabled" == "1" ]]; then
  if [[ ! -d /dev/shm ]]; then
    echo "memory-backed /dev/shm is required for local attachment scratch" >&2
    exit 1
  fi
  mkdir -p /dev/shm/fdai-channel-attachment-scratch
  chmod 700 /dev/shm/fdai-channel-attachment-scratch
  intake_temp="$(mktemp "${intake_env}.XXXXXX")"
  trap 'rm -f "$intake_temp"' EXIT
  {
    write_value FDAI_DATABASE_URL "$intake_database_url"
    write_value FDAI_DATABASE_ROLE fdai_ingestion_api
    write_value PGOPTIONS "-c role=fdai_ingestion_api"
    write_value FDAI_INGESTION_DEPLOYMENT_ROLE channel-intake
    write_value FDAI_EXECUTION_VENUE local
    write_value RUNTIME_ENV dev
    write_value FDAI_KAFKA_BOOTSTRAP_SERVERS "$FDAI_KAFKA_BOOTSTRAP_SERVERS"
    write_value FDAI_DOCUMENT_EVENT_TOPIC fdai.pipeline.stages
    write_value FDAI_ENTRA_TENANT_ID "$FDAI_ENTRA_TENANT_ID"
    write_value FDAI_CHANNEL_ATTACHMENT_API_AUDIENCE "$FDAI_CHANNEL_ATTACHMENT_INTAKE_AUDIENCE"
    write_value FDAI_CHANNEL_EDGE_CLIENT_ID "$FDAI_CHANNEL_ATTACHMENT_CLIENT_ID"
    write_value FDAI_CHANNEL_ATTACHMENT_PRINCIPAL_SCOPES_JSON "$FDAI_CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON"
    write_value FDAI_CHANNEL_ATTACHMENT_COLLECTION_ID "$FDAI_CHANNEL_ATTACHMENT_COLLECTION_ID"
    write_value FDAI_CHANNEL_ATTACHMENT_ACCESS_DESCRIPTOR_REF "$FDAI_CHANNEL_ATTACHMENT_ACCESS_DESCRIPTOR_REF"
    write_value FDAI_CHANNEL_ATTACHMENT_READER_GROUPS "$FDAI_CHANNEL_ATTACHMENT_READER_GROUPS"
    write_value FDAI_CHANNEL_ATTACHMENT_RETENTION_POLICY_VERSION "$FDAI_CHANNEL_ATTACHMENT_RETENTION_POLICY_VERSION"
    write_value FDAI_CHANNEL_ATTACHMENT_MAX_CONTENT_BYTES "${FDAI_CHANNEL_ATTACHMENT_MAX_CONTENT_BYTES:-26214400}"
    write_value FDAI_LOCAL_DOCUMENT_STORE_DIR "$repo_root/.fdai/document-store"
  } > "$intake_temp"
  chmod 600 "$intake_temp"
  mv "$intake_temp" "$intake_env"
  trap - EXIT
else
  rm -f "$intake_env"
fi
echo "prepared local standalone Operator channel-edge environment"
