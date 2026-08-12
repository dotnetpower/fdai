#!/usr/bin/env bash
# Generate private local environments for the independent ingestion and Executor services.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
runtime_env="$repo_root/.fdai/local-runtime.env"
operator_env="$repo_root/.fdai/local-operator-service.env"

if [[ ! -f "$runtime_env" || ! -f "$operator_env" ]]; then
  echo "local runtime and Operator environments MUST be prepared first" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090 - generated private environments are trusted workspace inputs.
source "$runtime_env"
set +a

: "${FDAI_STATE_STORE_DSN:?FDAI_STATE_STORE_DSN MUST be configured}"
: "${FDAI_KAFKA_BOOTSTRAP_SERVERS:?FDAI_KAFKA_BOOTSTRAP_SERVERS MUST be configured}"
if [[ "${FDAI_EXECUTION_VENUE:-}" != "local" ]]; then
  echo "independent local service environments require FDAI_EXECUTION_VENUE=local" >&2
  exit 1
fi

role_dsn() {
  local role="$1"
  if [[ "$FDAI_STATE_STORE_DSN" == *\?* ]]; then
    printf '%s&options=-c%%20role%%3D%s' "$FDAI_STATE_STORE_DSN" "$role"
  else
    printf '%s?options=-c%%20role%%3D%s' "$FDAI_STATE_STORE_DSN" "$role"
  fi
}

write_env() {
  local target="$1"
  local source="$2"
  shift 2
  local temporary
  temporary="$(mktemp "${target}.XXXXXX")"
  grep -vE '^(FDAI_DATABASE_URL|FDAI_DATABASE_ROLE|FDAI_INGESTION_DEPLOYMENT_ROLE|FDAI_INGESTION_CORS_ALLOW_ORIGINS|FDAI_DOCUMENT_EVENT_TOPIC|FDAI_LOCAL_DOCUMENT_STORE_DIR|FDAI_CLAMAV_HOST|FDAI_CLAMAV_PORT|FDAI_INGESTION_WORKER_HEALTH_PORT|FDAI_ISOLATED_EXECUTOR_(DEPLOYED|AUTHORITY_CUTOVER|MI_CLIENT_ID|HEALTH_PORT|LOCK_FILE))=' "$source" > "$temporary" || true
  printf '%s\n' "$@" >> "$temporary"
  chmod 600 "$temporary"
  mv "$temporary" "$target"
}

mkdir -p "$repo_root/.fdai"
umask 077
write_env "$repo_root/.fdai/local-document-ingestion-api.env" "$operator_env" \
  "FDAI_DATABASE_URL=$(role_dsn fdai_ingestion_api)" \
  "FDAI_DATABASE_ROLE=fdai_ingestion_api" \
  "FDAI_INGESTION_DEPLOYMENT_ROLE=api" \
  "FDAI_INGESTION_CORS_ALLOW_ORIGINS=http://127.0.0.1:5273,http://localhost:5273" \
  "FDAI_DOCUMENT_EVENT_TOPIC=aw.pipeline.stages" \
  "FDAI_LOCAL_DOCUMENT_STORE_DIR=$repo_root/.fdai/document-store"
write_env "$repo_root/.fdai/local-document-processing-worker.env" "$runtime_env" \
  "FDAI_DATABASE_URL=$(role_dsn fdai_ingestion_worker)" \
  "FDAI_DATABASE_ROLE=fdai_ingestion_worker" \
  "FDAI_INGESTION_DEPLOYMENT_ROLE=worker" \
  "FDAI_DOCUMENT_EVENT_TOPIC=aw.pipeline.stages" \
  "FDAI_LOCAL_DOCUMENT_STORE_DIR=$repo_root/.fdai/document-store" \
  "FDAI_CLAMAV_HOST=127.0.0.1" \
  "FDAI_CLAMAV_PORT=3310" \
  "FDAI_INGESTION_WORKER_HEALTH_PORT=8012"
write_env "$repo_root/.fdai/local-isolated-executor.env" "$runtime_env" \
  "FDAI_STATE_STORE_DSN=$(role_dsn fdai_executor)" \
  "FDAI_DATABASE_ROLE=fdai_executor" \
  "FDAI_ISOLATED_EXECUTOR_DEPLOYED=0" \
  "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER=0" \
  "FDAI_ISOLATED_EXECUTOR_HEALTH_PORT=8013" \
  "FDAI_ISOLATED_EXECUTOR_LOCK_FILE=$repo_root/.fdai/isolated-executor.lock"

echo "prepared local environments for Document Ingestion API, Document Processing Worker, and Isolated Executor"
