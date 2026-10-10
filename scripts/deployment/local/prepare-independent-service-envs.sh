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
# Generated private environments are trusted workspace inputs.
# shellcheck disable=SC1090
source "$runtime_env"
set +a

: "${FDAI_STATE_STORE_DSN:?FDAI_STATE_STORE_DSN MUST be configured}"
: "${FDAI_KAFKA_BOOTSTRAP_SERVERS:?FDAI_KAFKA_BOOTSTRAP_SERVERS MUST be configured}"
: "${FDAI_CODE_SECURITY_IMAGE_INPUT_DIGEST:?FDAI_CODE_SECURITY_IMAGE_INPUT_DIGEST MUST be configured}"
if [[ ! "$FDAI_CODE_SECURITY_IMAGE_INPUT_DIGEST" =~ ^[0-9a-f]{64}$ ]]; then
  echo "FDAI_CODE_SECURITY_IMAGE_INPUT_DIGEST MUST be a SHA-256 digest" >&2
  exit 1
fi
if [[ "${FDAI_EXECUTION_VENUE:-}" != "local" ]]; then
  echo "independent local service environments require FDAI_EXECUTION_VENUE=local" >&2
  exit 1
fi

role_dsn() {
  local role="$1"
  local dsn="$FDAI_STATE_STORE_DSN"
  local core_role_option='?options=-c%20role%3Dfdai_core'
  if [[ "$dsn" == *"$core_role_option" ]]; then
    dsn="${dsn%"$core_role_option"}"
  fi
  if [[ "$dsn" == *\?* ]]; then
    printf '%s&options=-c%%20role%%3D%s' "$dsn" "$role"
  else
    printf '%s?options=-c%%20role%%3D%s' "$dsn" "$role"
  fi
}

write_env() {
  local target="$1"
  local source="$2"
  shift 2
  local temporary
  temporary="$(mktemp "${target}.XXXXXX")"
  grep -vE '^(FDAI_DATABASE_URL|FDAI_DATABASE_ROLE|FDAI_STATE_STORE_DSN|FDAI_INGESTION_DEPLOYMENT_ROLE|FDAI_INGESTION_CORS_ALLOW_ORIGINS|FDAI_DOCUMENT_EVENT_TOPIC|FDAI_LOCAL_DOCUMENT_STORE_DIR|FDAI_CLAMAV_HOST|FDAI_CLAMAV_PORT|FDAI_INGESTION_WORKER_HEALTH_PORT|FDAI_ISOLATED_EXECUTOR_(DEPLOYED|AUTHORITY_CUTOVER|MI_CLIENT_ID|HEALTH_PORT|LOCK_FILE)|FDAI_CODE_SECURITY_(IMAGE|IMAGE_INPUT_DIGEST|CACHE_DIR|WORK_DIR|REQUEST_INTERVAL_SECONDS|SCHEDULE_INTERVAL_SECONDS|MAX_REQUESTS|MAX_REPOSITORIES))=' "$source" > "$temporary" || true
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
  "FDAI_INGESTION_CORS_ALLOW_ORIGINS=http://localhost:5273,http://127.0.0.1:5273" \
  "FDAI_DOCUMENT_EVENT_TOPIC=fdai.pipeline.stages" \
  "FDAI_DOCUMENT_OCR_PROVIDER=local_python" \
  "FDAI_LOCAL_DOCUMENT_STORE_DIR=$repo_root/.fdai/document-store"
write_env "$repo_root/.fdai/local-document-processing-worker.env" "$runtime_env" \
  "FDAI_DATABASE_URL=$(role_dsn fdai_ingestion_worker)" \
  "FDAI_DATABASE_ROLE=fdai_ingestion_worker" \
  "FDAI_INGESTION_DEPLOYMENT_ROLE=worker" \
  "FDAI_DOCUMENT_EVENT_TOPIC=fdai.pipeline.stages" \
  "FDAI_DOCUMENT_OCR_PROVIDER=local_python" \
  "FDAI_LOCAL_OCR_LANGUAGES=kor+eng" \
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
mkdir -p \
  "$repo_root/.fdai/code-security-cache" \
  "$repo_root/.fdai/code-security-work"
write_env "$repo_root/.fdai/local-code-security-worker.env" "$runtime_env" \
  "FDAI_STATE_STORE_DSN=$(role_dsn fdai_code_security_worker)" \
  "FDAI_DATABASE_ROLE=fdai_code_security_worker" \
  "FDAI_CODE_SECURITY_IMAGE=${FDAI_CODE_SECURITY_IMAGE:-fdai-code-security-scanner:local}" \
  "FDAI_CODE_SECURITY_IMAGE_INPUT_DIGEST=$FDAI_CODE_SECURITY_IMAGE_INPUT_DIGEST" \
  "FDAI_CODE_SECURITY_CACHE_DIR=$repo_root/.fdai/code-security-cache" \
  "FDAI_CODE_SECURITY_WORK_DIR=$repo_root/.fdai/code-security-work" \
  "FDAI_CODE_SECURITY_REQUEST_INTERVAL_SECONDS=${FDAI_CODE_SECURITY_REQUEST_INTERVAL_SECONDS:-5}" \
  "FDAI_CODE_SECURITY_SCHEDULE_INTERVAL_SECONDS=${FDAI_CODE_SECURITY_SCHEDULE_INTERVAL_SECONDS:-300}" \
  "FDAI_CODE_SECURITY_MAX_REQUESTS=${FDAI_CODE_SECURITY_MAX_REQUESTS:-20}" \
  "FDAI_CODE_SECURITY_MAX_REPOSITORIES=${FDAI_CODE_SECURITY_MAX_REPOSITORIES:-5}"

echo "prepared local environments for Document Ingestion API, Document Processing Worker, Isolated Executor, and Code Security Worker"
