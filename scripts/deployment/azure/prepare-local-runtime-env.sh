#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
REPO_ROOT="${FDAI_REPO_ROOT:-$SCRIPT_REPO_ROOT}"
AZ_BIN="${FDAI_AZ_BIN:-az}"
SOURCE_ENV="$REPO_ROOT/console/.env.local"
OUTPUT_ENV="${1:-$REPO_ROOT/.fdai/local-runtime.env}"
local_consumer_instance="${FDAI_LOCAL_CONSUMER_INSTANCE:-}"
resolved_models_override="${FDAI_LOCAL_RESOLVED_MODELS_PATH:-}"
local_vision_models_path="$REPO_ROOT/.fdai/resolved-models-vision.json"
resolved_models_path="${resolved_models_override:-$REPO_ROOT/resolved-models.json}"
local_kubernetes_lifecycle="${FDAI_LOCAL_KUBERNETES_LIFECYCLE:-0}"
local_kubernetes_bindings_override="${FDAI_LOCAL_KUBERNETES_BINDINGS_PATH:-}"
local_kubernetes_bindings_path="${local_kubernetes_bindings_override:-$REPO_ROOT/.fdai/local-kubernetes-bindings.json}"
local_teams_notification_activation="${FDAI_LOCAL_TEAMS_NOTIFICATION_ACTIVATION:-0}"
local_resource_group="${FDAI_LOCAL_RESOURCE_GROUP:-}"
kubernetes_lifecycle_keys=(
  FDAI_KUBERNETES_API_SERVER
  FDAI_KUBERNETES_AUDIENCE
  FDAI_KUBERNETES_AUTH_MODE
  FDAI_KUBERNETES_CA_PATH
  FDAI_KUBERNETES_CLUSTER_REF
)
kubernetes_lifecycle_lines=()
kubernetes_bindings_json=""

detect_monitor_workspace_customer_id() {
  local subscription_id="$1"
  local resource_group="$2"
  local workspace_count
  local workspace_customer_ids

  workspace_customer_ids="$(env -u AZURE_CONFIG_DIR "$AZ_BIN" monitor log-analytics workspace list \
    --subscription "$subscription_id" --resource-group "$resource_group" \
    --query "[].customerId" -o tsv 2>/dev/null || true)"
  workspace_count="$(printf '%s\n' "$workspace_customer_ids" | awk 'NF {count += 1} END {print count + 0}')"
  if [[ "$workspace_count" == "1" ]]; then
    printf '%s\n' "$workspace_customer_ids" | awk 'NF {print; exit}'
    echo "Log Analytics workspace detected via the selected Azure CLI read scope" >&2
  elif [[ "$workspace_count" -gt 1 ]]; then
    echo "multiple Log Analytics workspaces exist in the selected resource group" >&2
    return 1
  fi
}

if [[ ! -f "$SOURCE_ENV" ]]; then
  printf 'missing local console environment: %s\n' "$SOURCE_ENV" >&2
  exit 1
fi
if [[ "$local_kubernetes_lifecycle" != "0" && "$local_kubernetes_lifecycle" != "1" ]]; then
  echo "FDAI_LOCAL_KUBERNETES_LIFECYCLE MUST be 0 or 1" >&2
  exit 1
fi
if [[ -n "$local_kubernetes_bindings_override" && "$local_kubernetes_lifecycle" != "1" ]]; then
  echo "FDAI_LOCAL_KUBERNETES_BINDINGS_PATH requires FDAI_LOCAL_KUBERNETES_LIFECYCLE=1" >&2
  exit 1
fi
if [[ -n "$local_kubernetes_bindings_override" ]] && {
  [[ "$local_kubernetes_bindings_path" != /* ]] ||
    [[ ${#local_kubernetes_bindings_path} -gt 4096 ]] ||
    [[ "$local_kubernetes_bindings_path" == *$'\n'* ]] ||
    [[ "$local_kubernetes_bindings_path" == *$'\r'* ]]
}; then
  echo "FDAI_LOCAL_KUBERNETES_BINDINGS_PATH MUST be an absolute path" >&2
  exit 1
fi
if [[ "$local_teams_notification_activation" != "0" && "$local_teams_notification_activation" != "1" ]]; then
  echo "FDAI_LOCAL_TEAMS_NOTIFICATION_ACTIVATION MUST be 0 or 1" >&2
  exit 1
fi
if [[ "$local_kubernetes_lifecycle" == "1" ]]; then
  if [[ -f "$local_kubernetes_bindings_path" || -n "$local_kubernetes_bindings_override" ]]; then
    for key in "${kubernetes_lifecycle_keys[@]}"; do
      if grep -Eq "^${key}=" "$SOURCE_ENV"; then
        echo "fleet Kubernetes bindings MUST NOT be combined with legacy ${key}" >&2
        exit 1
      fi
    done
    if [[ ! -f "$local_kubernetes_bindings_path" ]]; then
      echo "FDAI_LOCAL_KUBERNETES_BINDINGS_PATH MUST name an existing file" >&2
      exit 1
    fi
    kubernetes_bindings_json="$(
      PYTHONPATH="$SCRIPT_REPO_ROOT/services/core-control-plane/src" \
        "$REPO_ROOT/.venv/bin/python" - "$local_kubernetes_bindings_path" <<'PY'
import json
import os
import stat
import sys
from pathlib import Path

from fdai.delivery.kubernetes_cluster_binding import parse_kubernetes_cluster_bindings

path = Path(sys.argv[1])
try:
    metadata = path.stat()
    if path.is_symlink() or not path.is_file():
        raise ValueError("path must be a regular file")
    if metadata.st_uid != os.getuid():
        raise ValueError("file must be owned by the current user")
    if metadata.st_size > 128 * 1024:
        raise ValueError("file exceeds 128 KiB")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("file must be owner-only")
    payload = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    parse_kubernetes_cluster_bindings(canonical)
except (OSError, ValueError, json.JSONDecodeError) as exc:
    raise SystemExit(f"invalid local Kubernetes bindings file: {exc}") from exc
print(canonical)
PY
    )"
    kubernetes_lifecycle_lines+=(
      "FDAI_KUBERNETES_CLUSTER_BINDINGS_JSON=$kubernetes_bindings_json"
    )
  else
    configured_kubernetes_values=0
    missing_kubernetes_key=""
    for key in "${kubernetes_lifecycle_keys[@]}"; do
      mapfile -t matches < <(grep -E "^${key}=" "$SOURCE_ENV" || true)
      if (( ${#matches[@]} > 1 )); then
        echo "FDAI_LOCAL_KUBERNETES_LIFECYCLE requires at most one ${key} binding" >&2
        exit 1
      fi
      if (( ${#matches[@]} == 1 )) && [[ -n "${matches[0]#*=}" ]]; then
        configured_kubernetes_values=$((configured_kubernetes_values + 1))
        kubernetes_lifecycle_lines+=("${matches[0]}")
      elif [[ -z "$missing_kubernetes_key" ]]; then
        missing_kubernetes_key="$key"
      fi
    done
    if (( configured_kubernetes_values == 0 )); then
      kubernetes_lifecycle_lines=("FDAI_KUBERNETES_SUBSCRIPTION_DISCOVERY=1")
    elif (( configured_kubernetes_values != ${#kubernetes_lifecycle_keys[@]} )); then
      echo "FDAI_LOCAL_KUBERNETES_LIFECYCLE requires one non-empty ${missing_kubernetes_key} binding" >&2
      exit 1
    fi
  fi
fi
if [[ -z "$local_consumer_instance" ]]; then
  local_consumer_instance="$(printf '%s' "${USER:-unknown}@$(hostname)" | sha256sum | cut -c1-12)"
elif [[ ! "$local_consumer_instance" =~ ^[a-z0-9][a-z0-9-]{0,19}$ ]]; then
  echo "FDAI_LOCAL_CONSUMER_INSTANCE MUST match ^[a-z0-9][a-z0-9-]{0,19}$" >&2
  exit 1
fi
if [[ -n "$resolved_models_override" ]] &&
  [[ "$resolved_models_path" != /* || "$resolved_models_path" == *$'\n'* || "$resolved_models_path" == *$'\r'* || ! -f "$resolved_models_path" ]]; then
  echo "FDAI_LOCAL_RESOLVED_MODELS_PATH MUST name an existing absolute file" >&2
  exit 1
fi
if [[ -z "$resolved_models_override" && -f "$local_vision_models_path" ]]; then
  if "$REPO_ROOT/.venv/bin/python" - "$local_vision_models_path" <<'PY'
import json
import sys
from pathlib import Path

try:
  payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
  raise SystemExit(1)

if not isinstance(payload, dict):
  raise SystemExit(1)

bindable_statuses = {"resolved", "capacity-reduced"}
capabilities = payload.get("capabilities")
if not isinstance(capabilities, list):
  raise SystemExit(1)
capability_by_name = {
  item.get("name"): item
  for item in capabilities
  if isinstance(item, dict) and isinstance(item.get("name"), str)
}

def bindable(name):
  item = capability_by_name.get(name)
  return isinstance(item, dict) and item.get("status") in bindable_statuses

if not bindable("t1.embedding"):
  raise SystemExit(1)
if (
  not (bindable("t2.reasoner.primary") and bindable("t2.reasoner.secondary"))
  and payload.get("mixed_model_mode") != "hil-only"
):
  raise SystemExit(1)

def route(value):
  if not isinstance(value, dict):
    return None
  fields = (
    value.get("endpoint"),
    value.get("deployment"),
    value.get("api_version", "2024-08-01-preview"),
    value.get("api_style", "azure-openai"),
    value.get("auth_audience", "https://cognitiveservices.azure.com/.default"),
  )
  return fields if all(isinstance(item, str) and item.strip() for item in fields) else None

narrator_raw = payload.get("narrator_candidates")
narrators = narrator_raw if isinstance(narrator_raw, list) and narrator_raw else [payload.get("narrator")]
narrator_routes = {
  candidate[1]: candidate
  for item in narrators
  if (candidate := route(item)) is not None
}
vision = payload.get("vision_candidates")
if not isinstance(vision, list) or not vision:
  raise SystemExit(1)
seen = set()
for item in vision:
  candidate = route(item)
  if candidate is None or candidate[1] in seen or narrator_routes.get(candidate[1]) != candidate:
    raise SystemExit(1)
  seen.add(candidate[1])
PY
  then
    resolved_models_path="$local_vision_models_path"
  else
    echo "ignored invalid local vision model artifact; using canonical resolved models" >&2
  fi
fi
if [[ -z "$resolved_models_override" && ! -f "$resolved_models_path" ]]; then
  resolved_models_path=""
fi

resolved_llm_endpoint=""
resolved_web_search_enabled="0"
resolved_models_sha256=""
if [[ -n "$resolved_models_path" ]]; then
  resolved_models_sha256="$(sha256sum "$resolved_models_path" | cut -d' ' -f1)"
  resolved_llm_endpoint="$("$REPO_ROOT/.venv/bin/python" - "$resolved_models_path" <<'PY'
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

path = Path(sys.argv[1])
try:
  payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
  raise SystemExit(f"resolved models artifact is unreadable: {exc}") from exc

if not isinstance(payload, dict):
  raise SystemExit("resolved models artifact MUST be a JSON object")

narrator = payload.get("narrator")
endpoint = narrator.get("endpoint") if isinstance(narrator, dict) else None
if not isinstance(endpoint, str) or not endpoint.strip():
  candidates = payload.get("narrator_candidates")
  if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
    endpoint = candidates[0].get("endpoint")

if not isinstance(endpoint, str) or not endpoint.strip():
  raise SystemExit(
    "resolved models artifact requires narrator.endpoint or "
    "narrator_candidates[0].endpoint for the core runtime"
  )

endpoint = endpoint.strip().rstrip("/")
parsed = urlsplit(endpoint)
if (
  parsed.scheme != "https"
  or not parsed.hostname
  or parsed.username is not None
  or parsed.password is not None
  or parsed.query
  or parsed.fragment
  or parsed.path not in ("", "/")
):
  raise SystemExit("resolved models narrator endpoint MUST be an HTTPS origin")

print(endpoint)
PY
)"
  resolved_web_search_enabled="$("$REPO_ROOT/.venv/bin/python" - "$resolved_models_path" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
candidates = payload.get("web_search_candidates") if isinstance(payload, dict) else None
available = isinstance(candidates, list) and any(
  isinstance(candidate, dict)
  and isinstance(candidate.get("endpoint"), str)
  and bool(candidate["endpoint"].strip())
  and isinstance(candidate.get("deployment"), str)
  and bool(candidate["deployment"].strip())
  for candidate in candidates
)
print("1" if available else "0")
PY
)"
fi

if [[ ! "$local_resource_group" =~ ^[A-Za-z0-9._()-]+$ ]]; then
  echo "FDAI_LOCAL_RESOURCE_GROUP MUST name an existing, explicitly selected read scope" >&2
  exit 1
fi
subscription_id="$(env -u AZURE_CONFIG_DIR "$AZ_BIN" account show --query id -o tsv)"
tenant_id="$(env -u AZURE_CONFIG_DIR "$AZ_BIN" account show --query tenantId -o tsv)"
echo "preparing local Docker state with an explicitly selected Azure read scope" >&2
resource_group="$local_resource_group"
region="$(env -u AZURE_CONFIG_DIR "$AZ_BIN" group show --subscription "$subscription_id" --name "$resource_group" --query location -o tsv)"
monitor_workspace_customer_id="$(
  detect_monitor_workspace_customer_id "$subscription_id" "$resource_group"
)"
dev_operations_gateway_url=""
dev_operations_gateway_audience=""
inventory_topic=""
if [[ -n "$monitor_workspace_customer_id" &&
  ! "$monitor_workspace_customer_id" =~ ^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$ ]]; then
  echo "Log Analytics workspace customer id is invalid" >&2
  exit 1
fi
gateway_candidates_json="$(env -u AZURE_CONFIG_DIR "$AZ_BIN" functionapp list \
  --subscription "$subscription_id" \
  --resource-group "$resource_group" \
  --query "[?contains(name, '-devgw-')].{id:id,host:defaultHostName}" \
  -o json 2>/dev/null || printf '[]')"
gateway_candidates_text="$(printf '%s' "$gateway_candidates_json" | \
  "$REPO_ROOT/.venv/bin/python" -c '
import json, sys
rows = json.load(sys.stdin)
if not isinstance(rows, list):
    raise SystemExit("gateway discovery response MUST be a list")
for row in rows:
    if not isinstance(row, dict):
        raise SystemExit("gateway discovery item MUST be an object")
    resource_id = row.get("id")
    host = row.get("host")
    if not isinstance(resource_id, str) or not isinstance(host, str):
        raise SystemExit("gateway discovery item is incomplete")
    print(f"{resource_id}\t{host}")
  ')"
  mapfile -t gateway_candidates < <(printf '%s' "$gateway_candidates_text")
if (( ${#gateway_candidates[@]} > 1 )); then
  echo "multiple development operations gateways exist in the selected resource group" >&2
  exit 1
fi
if (( ${#gateway_candidates[@]} == 1 )); then
  gateway_app_id="${gateway_candidates[0]%%$'\t'*}"
  gateway_host="${gateway_candidates[0]#*$'\t'}"
  mapfile -t browser_api_scopes < <(grep -E '^VITE_MSAL_API_SCOPE=' "$SOURCE_ENV" || true)
  if (( ${#browser_api_scopes[@]} != 1 )); then
    echo "one VITE_MSAL_API_SCOPE is required for the development operations gateway" >&2
    exit 1
  fi
  browser_api_scope="${browser_api_scopes[0]#*=}"
  if [[ ! "$browser_api_scope" =~ ^api://([^/]+)/[^/]+$ ]]; then
    echo "VITE_MSAL_API_SCOPE MUST use api://<audience>/<scope>" >&2
    exit 1
  fi
  gateway_audience_live="${BASH_REMATCH[1]}"
  if [[ "$gateway_host" =~ ^[A-Za-z0-9.-]+$ &&
    "$gateway_audience_live" =~ ^[A-Za-z0-9:._/-]+$ &&
    "${#gateway_audience_live}" -le 256 ]]; then
    dev_operations_gateway_url="https://${gateway_host}"
    dev_operations_gateway_audience="$gateway_audience_live"
    echo "development operations gateway detected via Azure CLI" >&2
  fi
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

grep -vE '^(AZURE_TENANT_ID|AZURE_SUBSCRIPTION_ID|AZURE_RESOURCE_GROUP|AZURE_REGION|KAFKA_BOOTSTRAP_SERVERS|KAFKA_SECURITY_PROTOCOL|KAFKA_TOPIC_EVENTS|POSTGRES_HOST|POSTGRES_DATABASE|RUNTIME_ENV|FDAI_EXECUTION_VENUE|AUTONOMY_MODE_DEFAULT|LLM_MODE|LLM_RESOLVED_MODELS_PATH|LLM_RESOLVED_MODELS_SHA256|FDAI_LLM_ENDPOINT|FDAI_WEB_SEARCH_ENABLED|FDAI_DATABASE_URL|FDAI_VALIDATION_DATABASE_URL|FDAI_STATE_STORE_DSN|FDAI_METERING_DSN|FDAI_CHAT_ASSURANCE_READINESS_RECEIPT|FDAI_KAFKA_BOOTSTRAP_SERVERS|FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS|FDAI_SEMANTIC_TURN_REQUEST_TOPIC|FDAI_SEMANTIC_TURN_PROJECTION_TOPIC|FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC|FDAI_OPERATING_MODEL_TOPIC|FDAI_READ_INVESTIGATION_REQUEST_TOPIC|FDAI_STAGE_TOPIC|FDAI_PANTHEON_OBJECT_TOPIC|FDAI_CANARY_TOPIC|FDAI_INVENTORY_RAW_TOPIC|FDAI_HIL_DECISION_TOPIC|FDAI_START_CONSUMER|FDAI_START_PANTHEON|FDAI_RUNTIME_LOCAL_AZURE_CLI|FDAI_CORE_CONSUMER_GROUP_ID|FDAI_PANTHEON_CONSUMER_GROUP_PREFIX|FDAI_OPERATOR_API_CONSUMER_INSTANCE|FDAI_AZURE_READER_SUBSCRIPTION_ID|FDAI_AZURE_READER_RESOURCE_GROUPS|FDAI_MONITOR_WORKSPACE_ID|FDAI_DEV_OPERATIONS_GATEWAY_URL|FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE|FDAI_DIRECT_API_FAKE|FDAI_LOCAL_KUBERNETES_LIFECYCLE|FDAI_LOCAL_KUBERNETES_BINDINGS_PATH|FDAI_TEAMS_NOTIFICATION_ACTIVATION|FDAI_KUBERNETES_[A-Z0-9_]+)=' "$SOURCE_ENV" > "$temp_env" || true
if [[ "$local_kubernetes_lifecycle" == "1" ]]; then
  printf '%s\n' "${kubernetes_lifecycle_lines[@]}" >> "$temp_env"
fi
{
  printf 'AZURE_TENANT_ID=%s\n' "$tenant_id"
  printf 'AZURE_SUBSCRIPTION_ID=%s\n' "$subscription_id"
  printf 'AZURE_RESOURCE_GROUP=%s\n' "$resource_group"
  printf 'AZURE_REGION=%s\n' "$region"
  printf 'FDAI_EXECUTION_VENUE=local\n'
  printf 'KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:19092\n'
  printf 'KAFKA_SECURITY_PROTOCOL=PLAINTEXT\n'
  printf 'FDAI_KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:19092\n'
  printf 'FDAI_SEMANTIC_TURN_REQUEST_TOPIC=operator.semantic-turn.requests\n'
  printf 'FDAI_SEMANTIC_TURN_PROJECTION_TOPIC=core.semantic-turn.projections\n'
  printf 'FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC=fdai.pantheon.objects\n'
  printf 'FDAI_OPERATING_MODEL_TOPIC=fdai.operating-model\n'
  printf 'FDAI_READ_INVESTIGATION_REQUEST_TOPIC=operator.read-investigation.requests\n'
  printf 'KAFKA_TOPIC_EVENTS=fdai.change.events\n'
  printf 'FDAI_STAGE_TOPIC=fdai.pipeline.stages\n'
  printf 'FDAI_PANTHEON_OBJECT_TOPIC=fdai.pantheon.objects\n'
  printf 'FDAI_HIL_DECISION_TOPIC=fdai.hil.decisions\n'
  if [[ -n "$inventory_topic" ]]; then
    printf 'FDAI_INVENTORY_RAW_TOPIC=%s\n' "$inventory_topic"
  fi
  printf 'POSTGRES_HOST=127.0.0.1\n'
  printf 'POSTGRES_DATABASE=fdai\n'
  printf 'FDAI_DATABASE_URL=postgresql+psycopg://fdai:devonly@127.0.0.1:5432/fdai\n'
  printf 'FDAI_VALIDATION_DATABASE_URL=postgresql+psycopg://fdai:devonly@127.0.0.1:5433/fdai_validation\n'
  printf 'FDAI_STATE_STORE_DSN=postgresql://fdai:devonly@127.0.0.1:5432/fdai\n'
  printf 'FDAI_CHAT_ASSURANCE_READINESS_RECEIPT=%s/.fdai/conversation-assurance/runtime-readiness.json\n' "$REPO_ROOT"
  printf 'FDAI_METERING_DSN=postgresql://fdai:devonly@127.0.0.1:5432/fdai\n'
  if [[ -n "$resolved_models_path" ]]; then
    printf 'LLM_MODE=azure\n'
    printf 'LLM_RESOLVED_MODELS_PATH=%s\n' "$resolved_models_path"
    printf 'LLM_RESOLVED_MODELS_SHA256=%s\n' "$resolved_models_sha256"
    printf 'FDAI_LLM_ENDPOINT=%s\n' "$resolved_llm_endpoint"
  fi
  printf 'FDAI_WEB_SEARCH_ENABLED=%s\n' "$resolved_web_search_enabled"
  printf 'RUNTIME_ENV=dev\n'
  printf 'AUTONOMY_MODE_DEFAULT=shadow\n'
  printf 'FDAI_START_CONSUMER=1\n'
  printf 'FDAI_START_PANTHEON=1\n'
  printf 'FDAI_TEAMS_NOTIFICATION_ACTIVATION=%s\n' "$local_teams_notification_activation"
  printf 'FDAI_STARTUP_KAFKA_PROBE_TOPIC=fdai.startup.probes\n'
  printf 'FDAI_RUNTIME_LOCAL_AZURE_CLI=1\n'
  printf 'FDAI_CORE_CONSUMER_GROUP_ID=fdai-local-%s-core\n' "$local_consumer_instance"
  printf 'FDAI_PANTHEON_CONSUMER_GROUP_PREFIX=fdai-local-%s-pantheon\n' "$local_consumer_instance"
  printf 'FDAI_OPERATOR_API_CONSUMER_INSTANCE=fdai-local-%s-operator-api\n' "$local_consumer_instance"
  printf 'FDAI_AZURE_READER_SUBSCRIPTION_ID=%s\n' "$subscription_id"
  printf 'FDAI_AZURE_READER_RESOURCE_GROUPS=%s\n' "$resource_group"
  if [[ -n "$monitor_workspace_customer_id" ]]; then
    printf 'FDAI_MONITOR_WORKSPACE_ID=%s\n' "$monitor_workspace_customer_id"
  fi
  if [[ -n "$dev_operations_gateway_url" ]]; then
    printf 'FDAI_DEV_OPERATIONS_GATEWAY_URL=%s\n' "$dev_operations_gateway_url"
    printf 'FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE=%s\n' "$dev_operations_gateway_audience"
  fi
} >> "$temp_env"

# The bootstrap login owns migrations; running services must exercise the Core SQL boundary.
sed -i '/^FDAI_STATE_STORE_DSN=/s|$|?options=-c%20role%3Dfdai_core|' "$temp_env"

mv "$temp_env" "$OUTPUT_ENV"
trap - EXIT
if [[ -z "$inventory_topic" ]]; then
  echo "inventory raw topic is not provisioned; local cache invalidation uses TTL refresh" >&2
fi
if [[ -z "$dev_operations_gateway_url" ]]; then
  echo "development operations gateway is not configured; managed-resource execution remains unavailable" >&2
fi
if [[ -z "$resolved_models_path" ]]; then
  echo "resolved-models.json is absent; local LLM calls and metering remain unavailable" >&2
fi
if [[ "$local_kubernetes_lifecycle" == "0" ]]; then
  echo "local Kubernetes lifecycle collection is disabled; set FDAI_LOCAL_KUBERNETES_LIFECYCLE=1 with complete bindings to enable it" >&2
fi
echo "prepared local runtime environment from explicit Azure read scope"
