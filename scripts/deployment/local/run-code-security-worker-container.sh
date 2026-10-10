#!/usr/bin/env bash
set -euo pipefail

container_name="fdai-code-security-worker"
shutdown_seconds="${FDAI_CODE_SECURITY_CONTAINER_SHUTDOWN_SECONDS:-30}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 DOCKER_RUN_ARG..." >&2
  exit 2
fi
if [[ ! "$shutdown_seconds" =~ ^[1-9][0-9]*$ ]]; then
  echo "FDAI_CODE_SECURITY_CONTAINER_SHUTDOWN_SECONDS MUST be a positive integer" >&2
  exit 2
fi
if docker container inspect "$container_name" >/dev/null 2>&1; then
  echo "managed code-security worker container already exists: $container_name" >&2
  exit 75
fi

docker_pid=""
stopping=0

stop_container() {
  if [[ "$stopping" == "1" ]]; then
    return
  fi
  stopping=1
  docker stop --time "$shutdown_seconds" "$container_name" >/dev/null 2>&1 || true
}

# Invoked by the signal trap below.
# shellcheck disable=SC2329
terminate() {
  trap - HUP INT TERM
  stop_container
  if [[ "$docker_pid" =~ ^[1-9][0-9]*$ ]]; then
    wait "$docker_pid" 2>/dev/null || true
  fi
  exit 130
}

trap terminate HUP INT TERM
docker run --rm --name "$container_name" "$@" &
docker_pid="$!"

set +e
wait "$docker_pid"
status=$?
set -e
trap - HUP INT TERM
stop_container
exit "$status"
