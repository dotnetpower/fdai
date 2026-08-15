#!/usr/bin/env bash
set -uo pipefail

usage() {
  echo "Usage: $0 <service> <log-file> -- <command> [args...]" >&2
  exit 2
}

if [[ $# -lt 4 || "$3" != "--" ]]; then
  usage
fi

service="$1"
log_file="$2"
shift 3

if [[ ! "$service" =~ ^[a-zA-Z0-9._-]+$ ]]; then
  echo "service name contains unsupported characters: $service" >&2
  exit 2
fi

max_bytes="${FDAI_LOCAL_SERVICE_LOG_MAX_BYTES:-1048576}"
if [[ ! "$max_bytes" =~ ^[1-9][0-9]*$ ]]; then
  echo "FDAI_LOCAL_SERVICE_LOG_MAX_BYTES MUST be a positive integer" >&2
  exit 2
fi
backup_count=3
log_format="${FDAI_LOCAL_SERVICE_LOG_FORMAT:-raw}"
if [[ "$log_format" != "raw" && "$log_format" != "json-plain" ]]; then
  echo "FDAI_LOCAL_SERVICE_LOG_FORMAT MUST be raw or json-plain" >&2
  exit 2
fi

log_dir="$(dirname "$log_file")"
mkdir -p "$log_dir"
chmod 700 "$log_dir"

lock_file="${log_file}.lock"
exec {service_lock_fd}> "$lock_file"
chmod 600 "$lock_file"
if ! flock -n "$service_lock_fd"; then
  echo "service already running: $service" >&2
  exit 75
fi

touch "$log_file"
chmod 600 "$log_file"

cleanup_stale_output_pipes() {
  local candidate
  local candidate_pid
  for candidate in "$log_dir/.$service.output."*; do
    [[ -p "$candidate" ]] || continue
    candidate_pid="${candidate##*.}"
    [[ "$candidate_pid" =~ ^[1-9][0-9]*$ ]] || continue
    if ! kill -0 "$candidate_pid" 2>/dev/null; then
      rm -f -- "$candidate"
    fi
  done
}

rotate_log() {
  local required_bytes="${1:-0}"
  local generation
  local previous_generation
  local size
  size="$(stat -c %s "$log_file" 2>/dev/null || echo 0)"
  if (( required_bytes == 0 && size < max_bytes )); then
    return
  fi
  if (( required_bytes > 0 && (size == 0 || size + required_bytes <= max_bytes) )); then
    return
  fi
  rm -f "${log_file}.${backup_count}"
  for ((generation = backup_count; generation > 1; generation--)); do
    previous_generation=$((generation - 1))
    if [[ -f "${log_file}.${previous_generation}" ]]; then
      mv "${log_file}.${previous_generation}" "${log_file}.${generation}"
    fi
  done
  mv "$log_file" "${log_file}.1"
  : > "$log_file"
  chmod 600 "$log_file"
}

write_marker() {
  local event="$1"
  local detail="${2:-}"
  local marker
  marker="$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z') service=$service event=$event"
  if [[ -n "$detail" ]]; then
    marker+=" $detail"
  fi
  printf '%s\n' "$marker"
  rotate_log "$(( ${#marker} + 1 ))"
  printf '%s\n' "$marker" >> "$log_file"
}

capture_output() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  python3 "$script_dir/capture-local-service-log.py" \
    --log-file "$log_file" \
    --format "$log_format" \
    --max-bytes "$max_bytes" \
    --backup-count "$backup_count"
}

active_owner() {
  # The log-file lock above only isolates this checkout. A second checkout can
  # already own the resources the service is a singleton on, so report those
  # instead of starting a child that is guaranteed to fail.
  local argument
  local previous=""
  local runtime_lock=""
  local port=""
  for argument in "$@"; do
    case "$argument" in
      FDAI_RUNTIME_LOCK_FILE=*) runtime_lock="${argument#FDAI_RUNTIME_LOCK_FILE=}" ;;
      --port=*) port="${argument#--port=}" ;;
    esac
    if [[ "$previous" == "--port" ]]; then
      port="$argument"
    fi
    previous="$argument"
  done

  if [[ -n "$runtime_lock" && -f "$runtime_lock" ]] \
    && ! flock -n "$runtime_lock" true 2>/dev/null; then
    printf 'runtime-lock=%s' "$runtime_lock"
    return 0
  fi
  if [[ "$port" =~ ^[1-9][0-9]*$ ]] && (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    printf 'port=127.0.0.1:%s' "$port"
    return 0
  fi
  return 1
}

if owner="$(active_owner "$@")"; then
  echo "service already running: $service ($owner)" >&2
  exit 75
fi

rotate_log
write_marker "starting"

cleanup_stale_output_pipes
output_pipe="$log_dir/.${service}.output.$$"
rm -f "$output_pipe"
mkfifo -m 600 "$output_pipe"

cleanup() {
  rm -f "$output_pipe"
}

trap cleanup EXIT

capture_output < "$output_pipe" &
logger_pid=$!
setsid -- "$@" > "$output_pipe" 2>&1 &
child_pid=$!

forward_signal() {
  local signal="$1"
  if kill -0 "$child_pid" 2>/dev/null; then
    kill -s "$signal" -- "-$child_pid" 2>/dev/null || true
  fi
}

trap 'forward_signal INT' INT
trap 'forward_signal TERM' TERM

status=0
while true; do
  wait "$child_pid"
  status=$?
  if ! kill -0 "$child_pid" 2>/dev/null; then
    break
  fi
done
wait "$logger_pid" || true
write_marker "stopped" "exit_code=$status"
exit "$status"
