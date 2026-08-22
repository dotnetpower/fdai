#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root"

services=(
  core-runtime
  operator-api
  document-ingestion-api
  document-processing-worker
  isolated-executor
  inventory-reconciliation
  observation-campaign
  console-frontend
)
child_pids=()
active_pids=()

stop_children() {
  local pid
  trap - EXIT INT TERM
  for pid in "${child_pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  for pid in "${child_pids[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}

handle_signal() {
  exit 130
}

require_managed_locks() {
  local lock_file
  local service
  local status
  for service in "${services[@]}"; do
    lock_file="$repo_root/.fdai/logs/$service.log.lock"
    if flock -n -E 75 "$lock_file" true; then
      echo "Console service lock is not held: $service" >&2
      return 1
    else
      status=$?
      if (( status != 75 )); then
        echo "Console service lock check failed: $service" >&2
        return "$status"
      fi
    fi
  done
}

trap stop_children EXIT
trap handle_signal INT TERM

printf '%s service=console-stack event=starting\n' "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')"
for service in "${services[@]}"; do
  bash "$repo_root/scripts/deployment/local/run-console-service.sh" "$service" &
  child_pids+=("$!")
done

"$repo_root/.venv/bin/python" \
  "$repo_root/scripts/automation/developer-workflow.py" \
  local-services \
  --wait-seconds 15
require_managed_locks
printf '%s service=console-stack event=ready\n' "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')"

for pid in "${child_pids[@]}"; do
  if kill -0 "$pid" 2>/dev/null; then
    active_pids+=("$pid")
  fi
done
if (( ${#active_pids[@]} == 0 )); then
  exit 0
fi

set +e
wait -n "${active_pids[@]}"
exit_code=$?
set -e
if (( exit_code == 0 )); then
  exit_code=1
fi
printf '%s service=console-stack event=stopped exit_code=%s\n' \
  "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')" \
  "$exit_code" >&2
exit "$exit_code"
