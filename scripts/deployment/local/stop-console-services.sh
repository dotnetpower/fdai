#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "Usage: $0" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
stack_lock_file="$repo_root/.fdai/logs/console-stack.log.lock"
[[ -f "$stack_lock_file" ]] || exit 0

exec {stack_lock_fd}>> "$stack_lock_file"
chmod 600 "$stack_lock_file"
if flock -n "$stack_lock_fd"; then
  exit 0
fi

read -r supervisor_pid < "$stack_lock_file" || true
supervisor_cwd="$(readlink -f "/proc/${supervisor_pid:-invalid}/cwd" 2>/dev/null || true)"
supervisor_is_managed=0
if [[ "${supervisor_pid:-}" =~ ^[1-9][0-9]*$ \
  && "$supervisor_cwd" == "$repo_root" \
  && -r "/proc/$supervisor_pid/cmdline" ]] \
  && grep -zEq '(^|/)scripts/deployment/local/start-console-services\.sh$' \
    "/proc/$supervisor_pid/cmdline"; then
  for supervisor_fd in "/proc/$supervisor_pid/fd/"*; do
    if [[ "$(readlink -f "$supervisor_fd" 2>/dev/null || true)" \
      == "$(readlink -f "$stack_lock_file")" ]]; then
      supervisor_is_managed=1
      break
    fi
  done
fi
if [[ "$supervisor_is_managed" != "1" ]]; then
  echo "existing Console supervisor ownership cannot be verified" >&2
  exit 75
fi

kill -TERM "$supervisor_pid"
if ! flock -w 15 "$stack_lock_fd"; then
  echo "existing Console supervisor did not release its lock" >&2
  exit 75
fi
echo "service=console-stack event=stopped"
