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
reuse_existing="${FDAI_LOCAL_SERVICE_REUSE_EXISTING:-0}"
if [[ "$reuse_existing" != "0" && "$reuse_existing" != "1" ]]; then
  echo "FDAI_LOCAL_SERVICE_REUSE_EXISTING MUST be 0 or 1" >&2
  exit 2
fi
restart_stale="${FDAI_LOCAL_SERVICE_RESTART_STALE:-0}"
if [[ "$restart_stale" != "0" && "$restart_stale" != "1" ]]; then
  echo "FDAI_LOCAL_SERVICE_RESTART_STALE MUST be 0 or 1" >&2
  exit 2
fi
input_digest="${FDAI_LOCAL_SERVICE_INPUT_DIGEST:-}"
if [[ -n "$input_digest" && ! "$input_digest" =~ ^[a-f0-9]{64}$ ]]; then
  echo "FDAI_LOCAL_SERVICE_INPUT_DIGEST MUST be a lowercase SHA-256 digest" >&2
  exit 2
fi
if [[ "$reuse_existing" == "1" && -z "$input_digest" ]]; then
  echo "FDAI_LOCAL_SERVICE_INPUT_DIGEST is required when service reuse is enabled" >&2
  exit 2
fi
shutdown_seconds="${FDAI_LOCAL_SERVICE_SHUTDOWN_SECONDS:-10}"
if [[ ! "$shutdown_seconds" =~ ^[1-9][0-9]*$ ]]; then
  echo "FDAI_LOCAL_SERVICE_SHUTDOWN_SECONDS MUST be a positive integer" >&2
  exit 2
fi
reuse_fingerprint=""
if [[ -n "$input_digest" ]]; then
  reuse_fingerprint="$({
    printf '%s\0' "$input_digest"
    printf '%s\0' "$@"
  } | sha256sum | cut -d' ' -f1)"
fi

log_dir="$(dirname "$log_file")"
mkdir -p "$log_dir"
chmod 700 "$log_dir"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
launch_marker="${FDAI_LOCAL_SERVICE_LAUNCH_MARKER:-}"
if [[ -n "$launch_marker" \
  && "$(readlink -m "$(dirname "$launch_marker")")" != "$(readlink -m "$log_dir")" ]]; then
  echo "FDAI_LOCAL_SERVICE_LAUNCH_MARKER must stay inside the service log directory" >&2
  exit 2
fi

write_launch_marker() {
  local event="$1"
  if [[ -z "$launch_marker" ]]; then
    return
  fi
  printf '%s\n' "$event" > "$launch_marker.tmp.$$"
  mv -f -- "$launch_marker.tmp.$$" "$launch_marker"
}

lock_file="${log_file}.lock"
exec {service_lock_fd}>> "$lock_file"
chmod 600 "$lock_file"
if ! flock -n "$service_lock_fd"; then
  if [[ "$reuse_existing" == "1" ]]; then
    read -r owner_fingerprint owner_pid owner_child_pid < "$lock_file" || true
    current_cwd="$(pwd -P)"
    owner_cwd="$(readlink -f "/proc/${owner_pid:-invalid}/cwd" 2>/dev/null || true)"
    owner_is_managed=0
    if [[ "${owner_pid:-}" =~ ^[1-9][0-9]*$ \
      && "$owner_cwd" == "$current_cwd" \
      && -r "/proc/$owner_pid/cmdline" ]] \
      && grep -zFq -- "scripts/automation/run-local-service.sh" "/proc/$owner_pid/cmdline" \
      && grep -zFxq -- "$service" "/proc/$owner_pid/cmdline"; then
      for owner_fd in "/proc/$owner_pid/fd/"*; do
        if [[ "$(readlink -f "$owner_fd" 2>/dev/null || true)" == "$(readlink -f "$lock_file")" ]]; then
          owner_is_managed=1
          break
        fi
      done
    fi
    child_cwd="$(readlink -f "/proc/${owner_child_pid:-invalid}/cwd" 2>/dev/null || true)"
    child_is_managed=0
    child_group="$(ps -o pgid= -p "${owner_child_pid:-invalid}" 2>/dev/null | tr -d ' ' || true)"
    if [[ "${owner_child_pid:-}" =~ ^[1-9][0-9]*$ \
      && "$child_cwd" == "$current_cwd" \
      && "$child_group" == "$owner_child_pid" ]]; then
      for child_fd in "/proc/$owner_child_pid/fd/"*; do
        if [[ "$(readlink -f "$child_fd" 2>/dev/null || true)" == "$(readlink -f "$lock_file")" ]]; then
          child_is_managed=1
          break
        fi
      done
    fi
    if [[ "$owner_is_managed" != "1" && "$child_is_managed" != "1" ]]; then
      if [[ "$restart_stale" == "1" ]] && flock -w 2 "$service_lock_fd"; then
        owner_fingerprint=""
        owner_cwd=""
        child_cwd=""
      else
        echo "service ownership cannot be verified: $service" >&2
        exit 75
      fi
    fi
    if [[ "$owner_fingerprint" != "$reuse_fingerprint" ]]; then
      if [[ "$restart_stale" != "1" ]]; then
        echo "service restart required: $service (launch inputs changed)" >&2
        exit 75
      fi
      if [[ -z "$owner_cwd" && -z "$child_cwd" ]] && flock -w 2 "$service_lock_fd"; then
        owner_is_managed=0
        child_is_managed=0
      else
        if [[ "$owner_is_managed" != "1" && "$child_is_managed" != "1" ]]; then
          echo "service restart required: $service (launch inputs changed)" >&2
          exit 75
        fi
        echo "service inputs changed; restarting: $service" >&2
        if [[ "$owner_is_managed" == "1" ]]; then
          kill -TERM "$owner_pid" 2>/dev/null || true
        else
          kill -TERM -- "-$owner_child_pid" 2>/dev/null || true
        fi
        if ! flock -w "$((shutdown_seconds + 5))" "$service_lock_fd"; then
          if [[ "$child_is_managed" == "1" ]]; then
            kill -KILL -- "-$owner_child_pid" 2>/dev/null || true
          fi
          if ! flock -w 2 "$service_lock_fd"; then
            echo "stale service lock was not released: $service" >&2
            exit 75
          fi
        fi
      fi
    else
      printf '%s service=%s event=starting\n' "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')" "$service"
      printf '%s service=%s event=reused\n' "$(date '+%Y-%m-%dT%H:%M:%S.%6N%:z')" "$service"
      write_launch_marker "reused"
      exit 0
    fi
  else
    echo "service already running: $service" >&2
    exit 75
  fi
fi
: > "$lock_file"
if [[ -n "$reuse_fingerprint" ]]; then
  printf '%s %s\n' "$reuse_fingerprint" "$$" > "$lock_file"
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
  python3 "$script_dir/capture-local-service-log.py" \
    --log-file "$log_file" \
    --format "$log_format" \
    --max-bytes "$max_bytes" \
    --backup-count "$backup_count"
}

probe_loopback_port() {
  local loopback="$1"
  local port="$2"
  python3 - "$loopback" "$port" "$service_lock_fd" <<'PY'
import os
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
try:
    os.close(int(sys.argv[3]))
except OSError:
    pass

family = socket.AF_INET6 if ":" in host else socket.AF_INET
with socket.socket(family, socket.SOCK_STREAM) as probe:
    probe.settimeout(0.25)
    raise SystemExit(0 if probe.connect_ex((host, port)) == 0 else 1)
PY
}

active_owner_result=""
active_owner() {
  # The log-file lock above only isolates this checkout. A second checkout can
  # already own the resources the service is a singleton on, so report those
  # instead of starting a child that is guaranteed to fail.
  local argument
  local previous=""
  local runtime_lock=""
  local port=""
  local flock_status
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

  if [[ -n "$runtime_lock" && -f "$runtime_lock" ]]; then
    # flock exits 1 only for contention and uses other codes (66 for a lock file
    # it cannot open) for real errors. Treating every failure as contention hid
    # an unusable lock file behind a permanent, unactionable "already running".
    flock -n -E 75 "$runtime_lock" true
    flock_status=$?
    if (( flock_status == 75 )); then
      active_owner_result="runtime-lock=$runtime_lock"
      return 0
    fi
    if (( flock_status != 0 )); then
      active_owner_result="runtime-lock-unusable=$runtime_lock exit=$flock_status"
      return 0
    fi
  fi
  if [[ "$port" =~ ^[1-9][0-9]*$ ]]; then
    # A server bound with --host localhost listens on IPv6 loopback on a dual-stack
    # host. Bound both probes so a filtered loopback address cannot retain the
    # service lock past the supervisor readiness deadline.
    local loopback
    for loopback in 127.0.0.1 ::1; do
      if probe_loopback_port "$loopback" "$port"; then
        active_owner_result="port=$loopback:$port"
        return 0
      fi
    done
  fi
  return 1
}

if active_owner "$@"; then
  echo "service already running: $service ($active_owner_result)" >&2
  exit 75
fi

rotate_log
write_marker "starting"
write_launch_marker "starting"

cleanup_stale_output_pipes
output_pipe="$log_dir/.${service}.output.$$"
rm -f "$output_pipe"
mkfifo -m 600 "$output_pipe"

cleanup() {
  rm -f "$output_pipe"
  if [[ -n "${shutdown_guard_pid:-}" ]]; then
    wait "$shutdown_guard_pid" 2>/dev/null || true
  fi
}

trap cleanup EXIT

capture_output < "$output_pipe" &
logger_pid=$!
python3 "$script_dir/run-local-service-child.py" "$@" > "$output_pipe" 2>&1 &
child_pid=$!
if [[ -n "$reuse_fingerprint" ]]; then
  printf '%s %s %s\n' "$reuse_fingerprint" "$$" "$child_pid" > "$lock_file"
fi
shutdown_guard_pid=""

forward_signal() {
  local signal="$1"
  if kill -0 "$child_pid" 2>/dev/null; then
    kill -s "$signal" -- "-$child_pid" 2>/dev/null || true
  fi
}

schedule_forced_shutdown() {
  if [[ -n "$shutdown_guard_pid" ]]; then
    return
  fi
  (
    if ! timeout "$shutdown_seconds" tail --pid="$child_pid" -f /dev/null; then
      echo "service shutdown exceeded ${shutdown_seconds}s; forcing stop: $service" >&2
      kill -KILL -- "-$child_pid" 2>/dev/null || true
    fi
  ) &
  shutdown_guard_pid=$!
}

handle_signal() {
  local signal="$1"
  forward_signal "$signal"
  schedule_forced_shutdown
}

trap 'handle_signal INT' INT
trap 'handle_signal TERM' TERM

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
