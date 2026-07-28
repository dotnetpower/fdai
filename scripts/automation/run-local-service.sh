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

max_bytes="${FDAI_LOCAL_SERVICE_LOG_MAX_BYTES:-10485760}"
if [[ ! "$max_bytes" =~ ^[1-9][0-9]*$ ]]; then
  echo "FDAI_LOCAL_SERVICE_LOG_MAX_BYTES MUST be a positive integer" >&2
  exit 2
fi
log_format="${FDAI_LOCAL_SERVICE_LOG_FORMAT:-raw}"
if [[ "$log_format" != "raw" && "$log_format" != "json-plain" ]]; then
  echo "FDAI_LOCAL_SERVICE_LOG_FORMAT MUST be raw or json-plain" >&2
  exit 2
fi

log_dir="$(dirname "$log_file")"
mkdir -p "$log_dir"
chmod 700 "$log_dir"
touch "$log_file"
chmod 600 "$log_file"

rotate_log() {
  local size
  size="$(stat -c %s "$log_file" 2>/dev/null || echo 0)"
  if (( size < max_bytes )); then
    return
  fi
  rm -f "${log_file}.1"
  mv "$log_file" "${log_file}.1"
  : > "$log_file"
  chmod 600 "$log_file"
}

write_marker() {
  local event="$1"
  local detail="${2:-}"
  local marker
  marker="$(date '+%Y-%m-%d %H:%M:%S,%3N %Z') service=$service event=$event"
  if [[ -n "$detail" ]]; then
    marker+=" $detail"
  fi
  printf '%s\n' "$marker"
  printf '%s\n' "$marker" >> "$log_file"
}

capture_output() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  python3 "$script_dir/capture-local-service-log.py" \
    --log-file "$log_file" \
    --format "$log_format" \
    --max-bytes "$max_bytes"
}

rotate_log
write_marker "starting"

output_pipe="$log_dir/.${service}.output.$$"
rm -f "$output_pipe"
mkfifo -m 600 "$output_pipe"

cleanup() {
  rm -f "$output_pipe"
}

trap cleanup EXIT

capture_output < "$output_pipe" &
logger_pid=$!
"$@" > "$output_pipe" 2>&1 &
child_pid=$!

forward_signal() {
  local signal="$1"
  if kill -0 "$child_pid" 2>/dev/null; then
    kill -s "$signal" "$child_pid" 2>/dev/null || true
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
