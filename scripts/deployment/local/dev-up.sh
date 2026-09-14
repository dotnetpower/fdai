#!/usr/bin/env bash
#
# dev-up.sh - start the local development stack (runtime/validation pgvector + Redpanda + ClamAV).
#
# On first run, seeds `infra/local/.env` from `.env.example` so the compose
# file's ${POSTGRES_PASSWORD} placeholder resolves to a documented dev
# default. `.env` is git-ignored - never committed.
#
# Exits 0 only after every container reports healthy.

set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "dev-up: Docker CLI is required but was not found on PATH" >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "dev-up: Docker Compose v2 is required; install the docker compose plugin" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  current_user="${USER:-$(id -un)}"
  if [[ "${FDAI_DOCKER_GROUP_REEXEC:-0}" != "1" ]] \
    && command -v sg >/dev/null 2>&1 \
    && getent group docker | awk -F: '{print $4}' | tr ',' '\n' | grep -Fxq "$current_user"; then
    printf -v docker_command '%q ' \
      env FDAI_DOCKER_GROUP_REEXEC=1 bash "${BASH_SOURCE[0]}" "$@"
    exec sg docker -c "$docker_command"
  fi
  echo "dev-up: Docker daemon is unavailable; start Docker and retry" >&2
  exit 1
fi

repo_root="$(git rev-parse --show-toplevel)"
compose_dir="${repo_root}/infra/local"
cd "${compose_dir}"

reconcile_redpanda_community_config() {
  if ! docker exec fdai-redpanda \
    rpk cluster config set partition_autobalancing_mode node_add; then
    echo "dev-up: failed to disable licensed continuous partition balancing" >&2
    return 1
  fi
  if ! docker exec fdai-redpanda \
    rpk cluster config set core_balancing_continuous false; then
    echo "dev-up: failed to disable licensed continuous core balancing" >&2
    return 1
  fi
  if ! docker exec fdai-redpanda \
    rpk cluster config set default_topic_partitions 2; then
    echo "dev-up: failed to set the two-partition local topic default" >&2
    return 1
  fi
}

reconcile_semantic_topic_partitions() {
  local topic="${FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC:-fdai.pantheon.objects}"
  local description
  if ! description="$(
    docker exec fdai-redpanda rpk topic describe "$topic" --print-partitions 2>/dev/null
  )"; then
    return 0
  fi
  local partition_count
  partition_count="$(
    awk 'NR > 1 && $1 ~ /^[0-9]+$/ { count += 1 } END { print count + 0 }' \
      <<<"$description"
  )"
  if (( partition_count == 0 )); then
    return 0
  fi
  if (( partition_count < 2 )); then
    if ! docker exec fdai-redpanda \
      rpk topic add-partitions "$topic" --num "$((2 - partition_count))"; then
      echo "dev-up: failed to expand the semantic topic to two partitions" >&2
      return 1
    fi
  fi
}

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "dev-up: seeded infra/local/.env from .env.example"
fi

echo "dev-up: bringing up postgres + redpanda + clamav..."
docker compose up -d --wait
reconcile_redpanda_community_config
reconcile_semantic_topic_partitions

echo
echo "dev-up: OK"
echo "  postgres runtime:     localhost:5432  (user=fdai db=fdai)"
echo "  postgres validation:  localhost:5433  (user=fdai db=fdai_validation)"
echo "  redpanda:  localhost:19092 (kafka external listener)"
echo "  admin:     localhost:9644  (redpanda admin API)"
echo "  clamav:    localhost:3310  (clamd stream scanner)"
