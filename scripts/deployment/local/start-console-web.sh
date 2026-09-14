#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 [--force] [--auth-mode browser-entra|azure-cli]" >&2
  exit 2
}

force_preparation=0
auth_mode="browser-entra"
while (( $# > 0 )); do
  case "$1" in
    --force)
      force_preparation=1
      shift
      ;;
    --auth-mode)
      if [[ $# -lt 2 ]]; then
        usage
      fi
      auth_mode="$2"
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done
if [[ "$auth_mode" != "browser-entra" && "$auth_mode" != "azure-cli" ]]; then
  usage
fi
prepare_arguments=(--auth-mode "$auth_mode")
if [[ "$force_preparation" == "1" ]]; then
  prepare_arguments=(--force "${prepare_arguments[@]}")
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root"

git_dir="$(git rev-parse --path-format=absolute --git-dir)"
common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
if [[ "$git_dir" != "$common_dir" ]]; then
  echo "Full-stack startup is available only from the primary checkout. Stop the primary stack before starting services from a linked worktree." >&2
  exit 75
fi

lock_is_held() {
  local lock_file="$1"
  local service="$2"
  local status
  [[ -e "$lock_file" ]] || return 1
  if flock -n -E 75 "$lock_file" true; then
    return 1
  else
    status=$?
  fi
  if (( status == 75 )); then
    return 0
  fi
  echo "Console service lock check failed: $service (exit_code=$status)" >&2
  exit "$status"
}

probe_python=""
if [[ -x "$repo_root/.venv/bin/python" ]]; then
  probe_python="$repo_root/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  probe_python="$(command -v python3)"
fi

conflicts=()
if [[ -n "$probe_python" ]]; then
  port_services=(
    console-frontend:5273
    manual-studio:5474
    operator-api:8010
    document-ingestion-api:8011
    document-processing-worker:8012
    isolated-executor:8013
  )
  for entry in "${port_services[@]}"; do
    service="${entry%%:*}"
    port="${entry##*:}"
    if lock_is_held "$repo_root/.fdai/logs/$service.log.lock" "$service"; then
      continue
    fi
    if "$probe_python" - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.25)
            if probe.connect_ex((host, port)) == 0:
                raise SystemExit(0)
    except OSError:
        continue
raise SystemExit(1)
PY
    then
      conflicts+=("$service (port=127.0.0.1:$port)")
    fi
  done
  if ! lock_is_held \
    "$repo_root/.fdai/logs/core-runtime.log.lock" \
    core-runtime; then
    if lock_is_held "$repo_root/.fdai/core-runtime.lock" core-runtime; then
      conflicts+=("core-runtime (runtime-lock=.fdai/core-runtime.lock)")
    fi
  fi
fi

if (( ${#conflicts[@]} > 0 )); then
  echo "Console startup is blocked by services outside the managed launcher:" >&2
  printf '  %s\n' "${conflicts[@]}" >&2
  echo "Stop the matching VS Code debug configuration or other owning process, then retry." >&2
  exit 75
fi

FDAI_LOCAL_TEAMS_NOTIFICATION_ACTIVATION=1 \
  bash "$repo_root/scripts/deployment/local/prepare-console-full-stack.sh" \
  "${prepare_arguments[@]}"
exec bash "$repo_root/scripts/deployment/local/start-console-services.sh" \
  --auth-mode "$auth_mode"
