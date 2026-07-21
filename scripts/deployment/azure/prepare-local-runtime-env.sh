#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${FDAI_REPO_ROOT:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
TERRAFORM_BIN="${FDAI_TERRAFORM_BIN:-terraform}"
AZ_BIN="${FDAI_AZ_BIN:-az}"
SOURCE_ENV="$REPO_ROOT/console/.env.local"
OUTPUT_ENV="${1:-$REPO_ROOT/.fdai/local-runtime.env}"

if [[ ! -f "$SOURCE_ENV" ]]; then
  printf 'missing local console environment: %s\n' "$SOURCE_ENV" >&2
  exit 1
fi

bootstrap="$($TERRAFORM_BIN -chdir="$REPO_ROOT/infra" output -raw event_bus_kafka_bootstrap)"
topics_json="$($TERRAFORM_BIN -chdir="$REPO_ROOT/infra" output -json event_bus_topics)"
auxiliary_topics_json="$($TERRAFORM_BIN -chdir="$REPO_ROOT/infra" output -json event_bus_auxiliary_topics 2>/dev/null || printf '[]')"
resource_group="$($TERRAFORM_BIN -chdir="$REPO_ROOT/infra" output -raw resource_group_name)"
subscription_id="$(env -u AZURE_CONFIG_DIR "$AZ_BIN" account show --query id -o tsv)"
tenant_id="$(env -u AZURE_CONFIG_DIR "$AZ_BIN" account show --query tenantId -o tsv)"
region="$(env -u AZURE_CONFIG_DIR "$AZ_BIN" group show --name "$resource_group" --query location -o tsv)"
event_topic="$(printf '%s' "$topics_json" | "$REPO_ROOT/.venv/bin/python" -c '
import json, sys
topics = json.load(sys.stdin)
if not isinstance(topics, list) or not topics or not all(isinstance(item, str) for item in topics):
    raise SystemExit("event_bus_topics MUST be a non-empty string array")
preferred = "aw.change.events"
print(preferred if preferred in topics else topics[0])
')"
inventory_topic="$(printf '%s' "$auxiliary_topics_json" | "$REPO_ROOT/.venv/bin/python" -c '
import json, sys
topics = json.load(sys.stdin)
required = "aw.inventory.raw"
print(required if isinstance(topics, list) and required in topics else "")
')"

if [[ ! "$bootstrap" =~ ^[a-z0-9.-]+\.servicebus\.windows\.net:9093$ ]]; then
  echo "event_bus_kafka_bootstrap is not an Event Hubs Kafka endpoint" >&2
  exit 1
fi
if [[ ! "$event_topic" =~ ^[a-z0-9._-]+$ ]]; then
  echo "event_bus_topics returned an invalid primary topic" >&2
  exit 1
fi
if [[ -z "$subscription_id" || -z "$tenant_id" || ! "$resource_group" =~ ^[A-Za-z0-9._()/-]+$ || ! "$region" =~ ^[a-z0-9-]+$ ]]; then
  echo "Azure account or deployed resource-group metadata is incomplete" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT_ENV")"
umask 077
temp_env="$(mktemp "${OUTPUT_ENV}.XXXXXX")"
trap 'rm -f "$temp_env"' EXIT

grep -vE '^(AZURE_TENANT_ID|AZURE_SUBSCRIPTION_ID|AZURE_RESOURCE_GROUP|AZURE_REGION|KAFKA_BOOTSTRAP_SERVERS|KAFKA_TOPIC_EVENTS|POSTGRES_HOST|POSTGRES_DATABASE|RUNTIME_ENV|AUTONOMY_MODE_DEFAULT|FDAI_DATABASE_URL|FDAI_STATE_STORE_DSN|FDAI_KAFKA_BOOTSTRAP_SERVERS|FDAI_STAGE_TOPIC|FDAI_PANTHEON_OBJECT_TOPIC|FDAI_CANARY_TOPIC|FDAI_INVENTORY_RAW_TOPIC|FDAI_HIL_DECISION_TOPIC|FDAI_START_CONSUMER|FDAI_START_PANTHEON|FDAI_RUNTIME_LOCAL_AZURE_CLI|FDAI_CORE_CONSUMER_GROUP_ID|FDAI_PANTHEON_CONSUMER_GROUP_PREFIX)=' "$SOURCE_ENV" > "$temp_env" || true
{
  printf 'AZURE_TENANT_ID=%s\n' "$tenant_id"
  printf 'AZURE_SUBSCRIPTION_ID=%s\n' "$subscription_id"
  printf 'AZURE_RESOURCE_GROUP=%s\n' "$resource_group"
  printf 'AZURE_REGION=%s\n' "$region"
  printf 'KAFKA_BOOTSTRAP_SERVERS=%s\n' "$bootstrap"
  printf 'FDAI_KAFKA_BOOTSTRAP_SERVERS=%s\n' "$bootstrap"
  printf 'KAFKA_TOPIC_EVENTS=%s\n' "$event_topic"
  printf 'FDAI_STAGE_TOPIC=aw.pipeline.stages\n'
  printf 'FDAI_PANTHEON_OBJECT_TOPIC=aw.pantheon.objects\n'
  if [[ -n "$inventory_topic" ]]; then
    printf 'FDAI_INVENTORY_RAW_TOPIC=%s\n' "$inventory_topic"
  fi
  printf 'POSTGRES_HOST=127.0.0.1\n'
  printf 'POSTGRES_DATABASE=fdai\n'
  printf 'FDAI_DATABASE_URL=postgresql+psycopg://fdai:devonly@127.0.0.1:5432/fdai\n'
  printf 'FDAI_STATE_STORE_DSN=postgresql://fdai:devonly@127.0.0.1:5432/fdai\n'
  printf 'RUNTIME_ENV=dev\n'
  printf 'AUTONOMY_MODE_DEFAULT=shadow\n'
  printf 'FDAI_START_CONSUMER=1\n'
  printf 'FDAI_START_PANTHEON=1\n'
  printf 'FDAI_RUNTIME_LOCAL_AZURE_CLI=1\n'
  printf 'FDAI_CORE_CONSUMER_GROUP_ID=fdai-local-core\n'
  printf 'FDAI_PANTHEON_CONSUMER_GROUP_PREFIX=fdai-local-core-pantheon\n'
} >> "$temp_env"

mv "$temp_env" "$OUTPUT_ENV"
trap - EXIT
if [[ -z "$inventory_topic" ]]; then
  echo "inventory raw topic is not provisioned; local cache invalidation uses TTL refresh" >&2
fi
echo "prepared local runtime environment from applied Terraform outputs"
