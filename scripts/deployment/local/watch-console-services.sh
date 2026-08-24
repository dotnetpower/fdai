#!/usr/bin/env bash
set -u -o pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root" || exit 1

interval_seconds="${FDAI_CONSOLE_WATCH_INTERVAL_SECONDS:-600}"
readiness_seconds="${FDAI_CONSOLE_WATCH_READINESS_SECONDS:-5}"
supervisor_pid=""

if [[ ! "$interval_seconds" =~ ^[1-9][0-9]*$ ]]; then
  echo "FDAI_CONSOLE_WATCH_INTERVAL_SECONDS must be a positive integer" >&2
  exit 2
fi
if [[ ! "$readiness_seconds" =~ ^[1-9][0-9]*$ ]]; then
  echo "FDAI_CONSOLE_WATCH_READINESS_SECONDS must be a positive integer" >&2
  exit 2
fi

stop_supervisor() {
  trap - EXIT INT TERM
  if [[ -n "$supervisor_pid" ]] && kill -0 "$supervisor_pid" 2>/dev/null; then
    kill -TERM "$supervisor_pid" 2>/dev/null || true
    wait "$supervisor_pid" 2>/dev/null || true
  fi
}

handle_signal() {
  exit 130
}

trap stop_supervisor EXIT
trap handle_signal INT TERM

printf '%s service=console-watchdog event=started interval_seconds=%s\n' \
  "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')" \
  "$interval_seconds"

while true; do
  if "$repo_root/.venv/bin/python" \
    "$repo_root/scripts/automation/developer-workflow.py" \
    local-services \
    --wait-seconds "$readiness_seconds" >/dev/null 2>&1; then
    printf '%s service=console-watchdog event=skip status=ready\n' \
      "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')"
  elif [[ -n "$supervisor_pid" ]] && kill -0 "$supervisor_pid" 2>/dev/null; then
    printf '%s service=console-watchdog event=skip status=recovery-in-progress\n' \
      "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')"
  else
    if [[ -n "$supervisor_pid" ]]; then
      wait "$supervisor_pid" 2>/dev/null || true
      supervisor_pid=""
    fi
    printf '%s service=console-watchdog event=recover status=unavailable\n' \
      "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')"
    if bash "$repo_root/scripts/deployment/local/prepare-console-full-stack.sh"; then
      bash "$repo_root/scripts/deployment/local/start-console-services.sh" &
      supervisor_pid="$!"
    else
      printf '%s service=console-watchdog event=recovery-failed stage=prepare\n' \
        "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')" >&2
    fi
  fi
  sleep "$interval_seconds"
done
