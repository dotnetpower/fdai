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
readiness_pid=""
terminal_event=""
readiness_seconds="${FDAI_CONSOLE_START_READINESS_SECONDS:-60}"
if [[ ! "$readiness_seconds" =~ ^[1-9][0-9]*$ ]]; then
  echo "FDAI_CONSOLE_START_READINESS_SECONDS must be a positive integer" >&2
  exit 2
fi
readiness_budget_seconds=$((readiness_seconds + 5))

emit_failed() {
  local stage="$1"
  shift
  if [[ -n "$terminal_event" ]]; then
    return
  fi
  terminal_event="failed"
  printf '%s service=console-stack event=failed stage=%s' \
    "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')" \
    "$stage" >&2
  if (( $# > 0 )); then
    printf ' %s' "$@" >&2
  fi
  printf '\n' >&2
}

# shellcheck disable=SC2329
stop_children() {
  local pid
  trap - EXIT INT TERM
  if [[ -n "$readiness_pid" ]] && kill -0 "$readiness_pid" 2>/dev/null; then
    kill -TERM "$readiness_pid" 2>/dev/null || true
  fi
  for pid in "${child_pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  for pid in "${child_pids[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
  if [[ -n "$readiness_pid" ]]; then
    wait "$readiness_pid" 2>/dev/null || true
  fi
}

# shellcheck disable=SC2329
handle_signal() {
  emit_failed signal "exit_code=130"
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
printf '%s service=console-stack event=started\n' "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')"

"$repo_root/.venv/bin/python" \
  "$repo_root/scripts/automation/run-bounded-command.py" \
  --label console-readiness \
  --timeout-seconds "$readiness_budget_seconds" \
  --no-progress-seconds "$readiness_budget_seconds" \
  -- \
  "$repo_root/.venv/bin/python" \
  "$repo_root/scripts/automation/developer-workflow.py" \
  local-services \
  --wait-seconds "$readiness_seconds" &
readiness_pid="$!"

pending_pids=("${child_pids[@]}")
while [[ -n "$readiness_pid" ]]; do
  completed_pid=""
  if wait -n -p completed_pid "$readiness_pid" "${pending_pids[@]}"; then
    exit_code=0
  else
    exit_code=$?
  fi
  if [[ "$completed_pid" == "$readiness_pid" ]]; then
    readiness_pid=""
    if (( exit_code != 0 )); then
      emit_failed readiness "exit_code=$exit_code"
      exit "$exit_code"
    fi
    break
  fi
  for index in "${!pending_pids[@]}"; do
    if [[ "${pending_pids[$index]}" != "$completed_pid" ]]; then
      continue
    fi
    if (( exit_code != 0 )); then
      printf 'service exited before readiness: %s (exit_code=%s, log=.fdai/logs/%s.log)\n' \
        "${services[$index]}" \
        "$exit_code" \
        "${services[$index]}" >&2
      emit_failed \
        service-startup \
        "service=${services[$index]}" \
        "exit_code=$exit_code"
      exit "$exit_code"
    fi
    unset 'pending_pids[index]'
    break
  done
done
if require_managed_locks; then
  :
else
  exit_code=$?
  emit_failed ownership "exit_code=$exit_code"
  exit "$exit_code"
fi
terminal_event="ready"
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
