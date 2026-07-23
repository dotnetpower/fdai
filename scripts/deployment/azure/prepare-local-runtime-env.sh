#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${FDAI_REPO_ROOT:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
TERRAFORM_BIN="${FDAI_TERRAFORM_BIN:-terraform}"
AZ_BIN="${FDAI_AZ_BIN:-az}"
SOURCE_ENV="$REPO_ROOT/console/.env.local"
OUTPUT_ENV="${1:-$REPO_ROOT/.fdai/local-runtime.env}"
local_consumer_instance="${FDAI_LOCAL_CONSUMER_INSTANCE:-}"

if [[ ! -f "$SOURCE_ENV" ]]; then
  printf 'missing local console environment: %s\n' "$SOURCE_ENV" >&2
  exit 1
fi
if [[ -z "$local_consumer_instance" ]]; then
  local_consumer_instance="$(printf '%s' "${USER:-unknown}@$(hostname)" | sha256sum | cut -c1-12)"
elif [[ ! "$local_consumer_instance" =~ ^[a-z0-9][a-z0-9-]{0,19}$ ]]; then
  echo "FDAI_LOCAL_CONSUMER_INSTANCE MUST match ^[a-z0-9][a-z0-9-]{0,19}$" >&2
  exit 1
fi

bootstrap="$($TERRAFORM_BIN -chdir="$REPO_ROOT/infra" output -raw event_bus_kafka_bootstrap)"
operational_bootstrap="$($TERRAFORM_BIN -chdir="$REPO_ROOT/infra" output -raw event_bus_operational_kafka_bootstrap 2>/dev/null || true)"
topics_json="$($TERRAFORM_BIN -chdir="$REPO_ROOT/infra" output -json event_bus_topics)"
operational_topics_json="$($TERRAFORM_BIN -chdir="$REPO_ROOT/infra" output -json event_bus_operational_topics 2>/dev/null || printf '[]')"
resource_group="$($TERRAFORM_BIN -chdir="$REPO_ROOT/infra" output -raw resource_group_name)"
dev_operations_gateway_url="$($TERRAFORM_BIN -chdir="$REPO_ROOT/infra" output -raw dev_operations_gateway_url 2>/dev/null || true)"
dev_operations_gateway_audience="$($TERRAFORM_BIN -chdir="$REPO_ROOT/infra" output -raw dev_operations_gateway_audience 2>/dev/null || true)"
executor_identity_resource_id="$($TERRAFORM_BIN -chdir="$REPO_ROOT/infra" output -raw executor_identity_resource_id)"
subscription_id="$(env -u AZURE_CONFIG_DIR "$AZ_BIN" account show --query id -o tsv)"
tenant_id="$(env -u AZURE_CONFIG_DIR "$AZ_BIN" account show --query tenantId -o tsv)"
if [[ ! "$executor_identity_resource_id" =~ ^/subscriptions/([^/]+)/resourceGroups/ ]]; then
  echo "executor_identity_resource_id is not a valid Azure resource ID" >&2
  exit 1
fi
deployment_subscription_id="${BASH_REMATCH[1]}"
if [[ "${subscription_id,,}" != "${deployment_subscription_id,,}" ]]; then
  echo "active Azure CLI subscription does not match the applied Terraform deployment" >&2
  exit 1
fi
region="$(env -u AZURE_CONFIG_DIR "$AZ_BIN" group show --name "$resource_group" --query location -o tsv)"
event_topic="$(printf '%s' "$topics_json" | "$REPO_ROOT/.venv/bin/python" -c '
import json, sys
topics = json.load(sys.stdin)
if not isinstance(topics, list) or not topics or not all(isinstance(item, str) for item in topics):
    raise SystemExit("event_bus_topics MUST be a non-empty string array")
preferred = "aw.change.events"
print(preferred if preferred in topics else topics[0])
')"
inventory_topic="$(printf '%s' "$operational_topics_json" | "$REPO_ROOT/.venv/bin/python" -c '
import json, sys
topics = json.load(sys.stdin)
required = "aw.inventory.raw"
print(required if isinstance(topics, list) and required in topics else "")
')"

if [[ ! "$bootstrap" =~ ^[a-z0-9.-]+\.servicebus\.windows\.net:9093$ ]]; then
  echo "event_bus_kafka_bootstrap is not an Event Hubs Kafka endpoint" >&2
  exit 1
fi
if [[ -n "$inventory_topic" && ! "$operational_bootstrap" =~ ^[a-z0-9.-]+\.servicebus\.windows\.net:9093$ ]]; then
  echo "event_bus_operational_kafka_bootstrap is required for raw inventory" >&2
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
if [[ -n "$dev_operations_gateway_url" && -z "$dev_operations_gateway_audience" ]] ||
  [[ -z "$dev_operations_gateway_url" && -n "$dev_operations_gateway_audience" ]]; then
  echo "development operations gateway URL and audience must be provisioned together" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT_ENV")"
umask 077
temp_env="$(mktemp "${OUTPUT_ENV}.XXXXXX")"
trap 'rm -f "$temp_env"' EXIT

grep -vE '^(AZURE_TENANT_ID|AZURE_SUBSCRIPTION_ID|AZURE_RESOURCE_GROUP|AZURE_REGION|KAFKA_BOOTSTRAP_SERVERS|KAFKA_TOPIC_EVENTS|POSTGRES_HOST|POSTGRES_DATABASE|RUNTIME_ENV|AUTONOMY_MODE_DEFAULT|FDAI_DATABASE_URL|FDAI_STATE_STORE_DSN|FDAI_KAFKA_BOOTSTRAP_SERVERS|FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS|FDAI_STAGE_TOPIC|FDAI_PANTHEON_OBJECT_TOPIC|FDAI_CANARY_TOPIC|FDAI_INVENTORY_RAW_TOPIC|FDAI_HIL_DECISION_TOPIC|FDAI_START_CONSUMER|FDAI_START_PANTHEON|FDAI_RUNTIME_LOCAL_AZURE_CLI|FDAI_CORE_CONSUMER_GROUP_ID|FDAI_PANTHEON_CONSUMER_GROUP_PREFIX|FDAI_READ_API_CONSUMER_INSTANCE|FDAI_AZURE_READER_SUBSCRIPTION_ID|FDAI_AZURE_READER_RESOURCE_GROUPS|FDAI_DEV_OPERATIONS_GATEWAY_URL|FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE|FDAI_DIRECT_API_FAKE)=' "$SOURCE_ENV" > "$temp_env" || true
{
  printf 'AZURE_TENANT_ID=%s\n' "$tenant_id"
  printf 'AZURE_SUBSCRIPTION_ID=%s\n' "$subscription_id"
  printf 'AZURE_RESOURCE_GROUP=%s\n' "$resource_group"
  printf 'AZURE_REGION=%s\n' "$region"
  printf 'KAFKA_BOOTSTRAP_SERVERS=%s\n' "$bootstrap"
  printf 'FDAI_KAFKA_BOOTSTRAP_SERVERS=%s\n' "$bootstrap"
  if [[ -n "$operational_bootstrap" ]]; then
    printf 'FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS=%s\n' "$operational_bootstrap"
  fi
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
  printf 'FDAI_CORE_CONSUMER_GROUP_ID=fdai-local-%s-core\n' "$local_consumer_instance"
  printf 'FDAI_PANTHEON_CONSUMER_GROUP_PREFIX=fdai-local-%s-pantheon\n' "$local_consumer_instance"
  printf 'FDAI_READ_API_CONSUMER_INSTANCE=fdai-local-%s-read-api\n' "$local_consumer_instance"
  printf 'FDAI_AZURE_READER_SUBSCRIPTION_ID=%s\n' "$subscription_id"
  printf 'FDAI_AZURE_READER_RESOURCE_GROUPS=%s\n' "$resource_group"
  if [[ -n "$dev_operations_gateway_url" ]]; then
    printf 'FDAI_DEV_OPERATIONS_GATEWAY_URL=%s\n' "$dev_operations_gateway_url"
    printf 'FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE=%s\n' "$dev_operations_gateway_audience"
  else
    # No operations gateway is provisioned in this deployment, so the
    # governed direct-API executor has no live backend. Auto-wire the
    # in-memory shadow fake (RecordingDirectApiExecutor) so the local dev
    # runtime still exercises the ``execution_path: direct_api`` dispatch
    # end-to-end. The fake performs no real mutation, and the runtime
    # forbids it alongside a gateway URL - the two are mutually exclusive.
    printf 'FDAI_DIRECT_API_FAKE=1\n'
  fi
} >> "$temp_env"

mv "$temp_env" "$OUTPUT_ENV"
trap - EXIT
if [[ -z "$inventory_topic" ]]; then
  echo "inventory raw topic is not provisioned; local cache invalidation uses TTL refresh" >&2
fi
if [[ -z "$dev_operations_gateway_url" ]]; then
  echo "development operations gateway is not provisioned; direct-API executor uses the in-memory shadow fake (FDAI_DIRECT_API_FAKE=1)" >&2
fi
echo "prepared local runtime environment from applied Terraform outputs"
