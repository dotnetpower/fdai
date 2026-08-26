#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <service> [--wait-ready]" >&2
  exit 2
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage
fi

service="$1"
wait_ready=0
if [[ $# -eq 2 ]]; then
  if [[ "$2" != "--wait-ready" \
    || ( "$service" != "core-runtime" && "$service" != "operator-api" ) ]]; then
    usage
  fi
  wait_ready=1
fi
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root"
readiness_seconds="${FDAI_CONSOLE_START_READINESS_SECONDS:-60}"
if [[ ! "$readiness_seconds" =~ ^[1-9][0-9]*$ ]]; then
  echo "FDAI_CONSOLE_START_READINESS_SECONDS must be a positive integer" >&2
  exit 2
fi
readiness_budget_seconds=$((readiness_seconds + 5))

case "$service" in
  core-runtime|inventory-reconciliation|observation-campaign)
    env_file=".fdai/local-runtime.env"
    source_root="services/core-control-plane/src"
    project_file="services/core-control-plane/pyproject.toml"
    ;;
  operator-api)
    env_file=".fdai/local-operator-service.env"
    source_root="services/operator-service/src"
    project_file="services/operator-service/pyproject.toml"
    ;;
  operator-channel-edge)
    env_file=".fdai/local-channel-edge.env"
    source_root="services/operator-service/src"
    project_file="services/operator-service/pyproject.toml"
    ;;
  document-ingestion-api)
    env_file=".fdai/local-document-ingestion-api.env"
    source_root="services/document-ingestion-api/src"
    project_file="services/document-ingestion-api/pyproject.toml"
    ;;
  document-processing-worker)
    env_file=".fdai/local-document-processing-worker.env"
    source_root="services/document-processing-worker/src"
    project_file="services/document-processing-worker/pyproject.toml"
    ;;
  isolated-executor)
    env_file=".fdai/local-isolated-executor.env"
    source_root="services/isolated-executor/src"
    project_file="services/isolated-executor/pyproject.toml"
    ;;
  console-frontend)
    env_file=""
    source_root="console/src"
    project_file="console/package.json"
    ;;
  *)
    echo "Unsupported local Console service: $service" >&2
    exit 2
    ;;
esac

if [[ "$service" == "operator-channel-edge" ]]; then
  bash "$repo_root/scripts/deployment/local/prepare-channel-edge-env.sh"
fi

if [[ "$service" == "console-frontend" ]]; then
  digest_inputs=(
    "$source_root"
    "$project_file"
    console/.env.local
    console/package-lock.json
    console/vite.config.ts
    console/tsconfig.json
    scripts/deployment/local/run-console-service.sh
  )
else
  digest_inputs=(
    "$env_file"
    "$source_root"
    packages/service-contracts/src
    "$project_file"
    pyproject.toml
    uv.lock
    scripts/deployment/local/run-console-service.sh
  )
  if [[ "$service" == "core-runtime" ]]; then
    digest_inputs+=(rule-catalog/prompts)
  fi
fi
input_digest="$(
  "$repo_root/.venv/bin/python" \
    "$repo_root/scripts/automation/local-service-input-digest.py" \
    "${digest_inputs[@]}"
)"

if [[ -n "$env_file" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$repo_root/$env_file"
  set +a
fi

export FDAI_LOCAL_SERVICE_INPUT_DIGEST="$input_digest"
export FDAI_LOCAL_SERVICE_LOG_FORMAT=json-plain
export FDAI_LOCAL_SERVICE_RESTART_STALE=1
export FDAI_LOCAL_SERVICE_REUSE_EXISTING=1

service_pythonpath="$repo_root/$source_root:$repo_root/packages/service-contracts/src${PYTHONPATH:+:$PYTHONPATH}"
case "$service" in
  core-runtime)
    service_command=(
      env -u AZURE_CONFIG_DIR
      FDAI_PANTHEON_HEARTBEAT_SECONDS=2
      FDAI_RUNTIME_LOCK_FILE="$repo_root/.fdai/core-runtime.lock"
      PYTHONPATH="$service_pythonpath"
      "$repo_root/.venv/bin/python" -m fdai
    )
    ;;
  operator-api)
    service_command=(
      env -u AZURE_CONFIG_DIR
      PYTHONPATH="$service_pythonpath"
      "$repo_root/.venv/bin/python" -m uvicorn
      fdai_operator_service.main:create_app
      --factory --host 127.0.0.1 --port 8010 --no-access-log
    )
    ;;
  operator-channel-edge)
    service_command=(
      env -u AZURE_CONFIG_DIR
      PYTHONPATH="$service_pythonpath"
      "$repo_root/.venv/bin/fdai-operator-channel-edge"
    )
    ;;
  inventory-reconciliation)
    service_command=(
      env -u AZURE_CONFIG_DIR
      FDAI_EXECUTION_VENUE=local
      FDAI_INVENTORY_DSN="$FDAI_STATE_STORE_DSN"
      FDAI_INVENTORY_SCOPES="$AZURE_SUBSCRIPTION_ID"
      FDAI_INVENTORY_RECOVERY_DELTA=1
      PYTHONPATH="$service_pythonpath"
      "$repo_root/.venv/bin/python" -m fdai.delivery.inventory_sync_cli --loop
    )
    ;;
  observation-campaign)
    service_command=(
      env -u AZURE_CONFIG_DIR
      FDAI_EXECUTION_VENUE=local
      FDAI_OBSERVATION_DSN="$FDAI_STATE_STORE_DSN"
      FDAI_OBSERVATION_SCOPES="$AZURE_SUBSCRIPTION_ID"
      PYTHONPATH="$service_pythonpath"
      "$repo_root/.venv/bin/python" -m fdai.delivery.observation_campaign_cli --loop
    )
    ;;
  document-ingestion-api)
    service_command=(
      env -u AZURE_CONFIG_DIR
      PYTHONPATH="$service_pythonpath"
      "$repo_root/.venv/bin/python" -m uvicorn
      fdai_ingestion_api_service.main:create_app
      --factory --host 127.0.0.1 --port 8011 --no-access-log
    )
    ;;
  document-processing-worker)
    service_command=(
      env -u AZURE_CONFIG_DIR
      PYTHONPATH="$service_pythonpath"
      "$repo_root/.venv/bin/fdai-document-processing-worker"
    )
    ;;
  isolated-executor)
    service_command=(
      env -u AZURE_CONFIG_DIR
      PYTHONPATH="$service_pythonpath"
      "$repo_root/.venv/bin/fdai-isolated-executor-service"
    )
    ;;
  console-frontend)
    service_command=(
      env
      VITE_DEV_MODE=0
      VITE_LOCAL_AZURE_CLI_AUTH=0
      VITE_OPERATOR_API_BASE_URL=http://127.0.0.1:8010
      VITE_INGESTION_API_BASE_URL=http://127.0.0.1:8011
      npm --prefix "$repo_root/console" run dev -- --port 5273 --strictPort
    )
    ;;
esac

runner=(
  bash "$repo_root/scripts/automation/run-local-service.sh"
  "$service"
  "$repo_root/.fdai/logs/$service.log"
  --
  "${service_command[@]}"
)

write_task_marker() {
  local event="$1"
  local detail="${2:-}"
  local marker
  marker="$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z') service=$service event=$event"
  if [[ -n "$detail" ]]; then
    marker+=" $detail"
  fi
  if [[ "$event" == "failed" ]]; then
    printf '%s\n' "$marker" >&2
  else
    printf '%s\n' "$marker"
  fi
}

if [[ "$wait_ready" == "0" ]]; then
  exec "${runner[@]}"
fi

launch_marker="$repo_root/.fdai/logs/.$service.launch.$$"
rm -f -- "$launch_marker"
cleanup_launch_marker() {
  rm -f -- "$launch_marker"
}
trap cleanup_launch_marker EXIT

FDAI_LOCAL_SERVICE_LAUNCH_MARKER="$launch_marker" "${runner[@]}" &
runner_pid="$!"
launch_deadline=$((SECONDS + readiness_budget_seconds))
while [[ ! -s "$launch_marker" ]]; do
  if ! kill -0 "$runner_pid" 2>/dev/null; then
    if wait "$runner_pid"; then
      runner_status=0
    else
      runner_status=$?
    fi
    write_task_marker "failed" "stage=runner exit_code=$runner_status"
    exit "$runner_status"
  fi
  if (( SECONDS >= launch_deadline )); then
    kill -TERM "$runner_pid" 2>/dev/null || true
    wait "$runner_pid" 2>/dev/null || true
    write_task_marker "failed" "stage=launch exit_code=124"
    exit 124
  fi
  sleep 0.05
done
launch_event="$(< "$launch_marker")"
rm -f -- "$launch_marker"
if [[ "$launch_event" != "starting" && "$launch_event" != "reused" ]]; then
  kill -TERM "$runner_pid" 2>/dev/null || true
  wait "$runner_pid" 2>/dev/null || true
  write_task_marker "failed" "stage=launch exit_code=1"
  exit 1
fi
remaining_budget_seconds=$((launch_deadline - SECONDS))
if (( remaining_budget_seconds <= 1 )); then
  kill -TERM "$runner_pid" 2>/dev/null || true
  wait "$runner_pid" 2>/dev/null || true
  write_task_marker "failed" "stage=launch exit_code=124"
  exit 124
fi
probe_wait_seconds=$((remaining_budget_seconds - 1))
"$repo_root/.venv/bin/python" \
  "$repo_root/scripts/automation/run-bounded-command.py" \
  --label "$service-readiness" \
  --timeout-seconds "$remaining_budget_seconds" \
  --no-progress-seconds "$remaining_budget_seconds" \
  -- \
  "$repo_root/.venv/bin/python" \
  "$repo_root/scripts/automation/developer-workflow.py" \
  local-services \
  --wait-seconds "$probe_wait_seconds" \
  --only "$service" >/dev/null &
readiness_pid="$!"

completed_pid=""
if wait -n -p completed_pid "$runner_pid" "$readiness_pid"; then
  completed_status=0
else
  completed_status=$?
fi
if [[ "$completed_pid" == "$runner_pid" ]]; then
  if (( completed_status != 0 )); then
    kill -TERM "$readiness_pid" 2>/dev/null || true
    wait "$readiness_pid" 2>/dev/null || true
    write_task_marker "failed" "stage=runner exit_code=$completed_status"
    exit "$completed_status"
  fi
  if [[ "$launch_event" != "reused" ]]; then
    kill -TERM "$readiness_pid" 2>/dev/null || true
    wait "$readiness_pid" 2>/dev/null || true
    write_task_marker "failed" "stage=runner exit_code=1"
    exit 1
  fi
  if wait "$readiness_pid"; then
    readiness_status=0
  else
    readiness_status=$?
    write_task_marker "failed" "stage=readiness exit_code=$readiness_status"
    exit "$readiness_status"
  fi
elif (( completed_status != 0 )); then
  kill -TERM "$runner_pid" 2>/dev/null || true
  wait "$runner_pid" 2>/dev/null || true
  write_task_marker "failed" "stage=readiness exit_code=$completed_status"
  exit "$completed_status"
fi
write_task_marker "ready"
if kill -0 "$runner_pid" 2>/dev/null; then
  wait "$runner_pid"
fi
