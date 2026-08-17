#!/usr/bin/env bash
# Ensure local semantic turns can use bounded partition-level concurrency.

set -euo pipefail

container="${FDAI_LOCAL_REDPANDA_CONTAINER:-fdai-redpanda}"
topic="${FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC:-aw.pantheon.objects}"
minimum_partitions="${FDAI_SEMANTIC_TURN_MIN_PARTITIONS:-2}"
lock_key="${container//[^a-zA-Z0-9_.-]/_}-${topic//[^a-zA-Z0-9_.-]/_}"
lock_file="${TMPDIR:-/tmp}/fdai-semantic-topic-${lock_key}.lock"

if [[ ! "$minimum_partitions" =~ ^[0-9]+$ ]] || ((minimum_partitions < 2 || minimum_partitions > 8)); then
  echo "semantic topic minimum partitions MUST be in [2, 8]" >&2
  exit 1
fi

exec 9>"$lock_file"
flock 9

if ! partition_output="$(docker exec "$container" rpk topic describe "$topic" -p 2>/dev/null)"; then
  docker exec "$container" rpk topic create "$topic" -p "$minimum_partitions" --if-not-exists
  exit 0
fi

partition_count="$(awk '$1 ~ /^[0-9]+$/ { count += 1 } END { print count + 0 }' <<<"$partition_output")"
if ((partition_count < minimum_partitions)); then
  docker exec "$container" rpk topic add-partitions "$topic" \
    --num "$((minimum_partitions - partition_count))"
fi
