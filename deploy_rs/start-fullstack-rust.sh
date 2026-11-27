#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/.fdai/rust-fullstack.pids"
LOG_DIR="$ROOT/.fdai/logs"
mkdir -p "$LOG_DIR"

if [[ -f "$PID_FILE" ]]; then
  while read -r pid; do
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done < "$PID_FILE"
  rm -f "$PID_FILE"
  sleep 0.5
fi

CARGO_BUILD_ARGS=(--manifest-path "$ROOT/Cargo.toml" --locked)
if [[ "${FDAI_CARGO_OFFLINE:-0}" == "1" ]]; then
  CARGO_BUILD_ARGS+=(--offline)
fi

echo "[fullstack] Building all 9 Pure-Rust services (6 core + Release Hub + Lifecycle Hub + Console v4)..."
cargo build "${CARGO_BUILD_ARGS[@]}" \
  -p fdai-operator-service --bin fdai-operator-service \
  -p fdai-document-ingestion-api --bin fdai-document-ingestion-api \
  -p fdai-document-processing-worker --bin fdai-document-processing-worker \
  -p fdai-isolated-executor --bin fdai-isolated-executor \
  -p fdai-core-control-plane --bin fdai-core-control-plane \
  -p fdai-system-knowledge-service --bin fdai-system-knowledge-service \
  -p fdai-release-hub --bin fdai-release-hub \
  -p fdai-hub --bin fdai-hub \
  -p fdai-console-v4 --bin fdai-console-v4

# Resolve local DB / Kafka runtime env safely (honor explicit caller env; never echo secret values)
load_env_key() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 0
  if [[ -n "${!key:-}" ]]; then
    return 0
  fi
  local val
  val="$(grep -E "^${key}=" "$file" | tail -n 1 | cut -d= -f2- | tr -d '\r' || true)"
  if [[ -n "$val" ]]; then
    export "${key}=${val}"
  fi
}

LOCAL_OP_ENV="$ROOT/.fdai/local-operator-service.env"
if [[ -f "$LOCAL_OP_ENV" ]]; then
  for k in \
    FDAI_DATABASE_URL \
    FDAI_DATABASE_ROLE \
    FDAI_KAFKA_BOOTSTRAP_SERVERS \
    KAFKA_BOOTSTRAP_SERVERS \
    FDAI_STAGE_TOPIC \
    KAFKA_TOPIC_EVENTS \
    FDAI_START_CONSUMER; do
    load_env_key "$LOCAL_OP_ENV" "$k"
  done
fi

if [[ -z "${DEV_MODE:-}" && -z "${FDAI_E2E_BEARER:-}" && -z "${FDAI_ENTRA_TENANT_ID:-}" ]]; then
  if [[ -f "$LOCAL_OP_ENV" ]]; then
    for k in \
      FDAI_ENTRA_TENANT_ID \
      FDAI_API_AUDIENCE \
      FDAI_ENTRA_ISSUER \
      FDAI_ENTRA_JWKS_URI \
      FDAI_RBAC_READERS_GROUP_ID \
      FDAI_RBAC_CONTRIBUTORS_GROUP_ID \
      FDAI_RBAC_APPROVERS_GROUP_ID \
      FDAI_RBAC_OWNERS_GROUP_ID \
      FDAI_RBAC_BREAK_GLASS_GROUP_ID \
      FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS; do
      load_env_key "$LOCAL_OP_ENV" "$k"
    done
  elif [[ -f "$ROOT/console/.env.local" ]]; then
    TENANT_ID="$(grep -E '^VITE_MSAL_TENANT_ID=' "$ROOT/console/.env.local" | cut -d= -f2- | tr -d '\r' || true)"
    API_SCOPE="$(grep -E '^VITE_MSAL_API_SCOPE=' "$ROOT/console/.env.local" | cut -d= -f2- | tr -d '\r' || true)"
    if [[ -n "$TENANT_ID" && -n "$API_SCOPE" ]]; then
      export FDAI_ENTRA_TENANT_ID="$TENANT_ID"
      AUD_CLEAN="${API_SCOPE%/access}"
      export FDAI_API_AUDIENCE="${AUD_CLEAN#api://}"
    fi
  fi
fi

BIN="$ROOT/target/debug"
start_bg() {
  local name="$1"; shift
  nohup "$@" >"$LOG_DIR/${name}.log" 2>&1 < /dev/null &
  echo "$!" >> "$PID_FILE"
}

start_bg operator-service "$BIN/fdai-operator-service" --host 127.0.0.1 --port 8010
start_bg document-ingestion-api "$BIN/fdai-document-ingestion-api" --host 127.0.0.1 --port 8011
start_bg document-processing-worker "$BIN/fdai-document-processing-worker" --host 127.0.0.1 --port 8012
start_bg isolated-executor "$BIN/fdai-isolated-executor" --host 127.0.0.1 --port 8013
start_bg core-control-plane "$BIN/fdai-core-control-plane" --host 127.0.0.1 --port 8014
start_bg system-knowledge-service "$BIN/fdai-system-knowledge-service" --host 127.0.0.1 --port 8016
start_bg release-hub "$BIN/fdai-release-hub" --host 127.0.0.1 --port "${FDAI_RELEASE_HUB_PORT:-8022}" --static-dir "$ROOT/lifecycle_rs/release-hub/ui/dist"
FDAI_RELEASE_HUB_ENDPOINT="${FDAI_RELEASE_HUB_ENDPOINT:-http://127.0.0.1:${FDAI_RELEASE_HUB_PORT:-8022}}" \
  start_bg lifecycle-hub "$BIN/fdai-hub" --host 127.0.0.1 --port "${FDAI_LIFECYCLE_HUB_PORT:-8021}" --static-dir "$ROOT/lifecycle_rs/hub/ui/dist"
start_bg console-v4 "$BIN/fdai-console-v4" --host 127.0.0.1 --port "${FDAI_CONSOLE_PORT:-5290}"

wait_url() {
  local label="$1" url="$2"
  for _ in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "  [OK] $label -> $url"
      return 0
    fi
    sleep 0.25
  done
  echo "  [FAIL] $label -> $url" >&2
  return 1
}

echo "[fullstack] Verifying all 9 Pure-Rust endpoints..."
wait_url "Operator API"               "http://127.0.0.1:8010/healthz"
wait_url "Document Ingestion API"     "http://127.0.0.1:8011/healthz"
wait_url "Document Processing Worker" "http://127.0.0.1:8012/healthz"
wait_url "Isolated Executor"          "http://127.0.0.1:8013/healthz"
wait_url "Core Control Plane"         "http://127.0.0.1:8014/healthz"
wait_url "System Knowledge Service"   "http://127.0.0.1:8016/healthz"
wait_url "Release Hub (Axum)"         "http://127.0.0.1:${FDAI_RELEASE_HUB_PORT:-8022}/healthz"
wait_url "Lifecycle Hub (Axum)"       "http://127.0.0.1:${FDAI_LIFECYCLE_HUB_PORT:-8021}/healthz"
wait_url "Console v4 (Pure-Rust)"     "http://127.0.0.1:${FDAI_CONSOLE_PORT:-5290}/api/v4/meta"
echo "[fullstack] ALL PURE-RUST SERVICES READY (PIDs in $PID_FILE)"
echo "  Console Web (v4): http://127.0.0.1:${FDAI_CONSOLE_PORT:-5290}"
echo "  Release Hub:      http://127.0.0.1:${FDAI_RELEASE_HUB_PORT:-8022}"
echo "  Lifecycle Hub:    http://127.0.0.1:${FDAI_LIFECYCLE_HUB_PORT:-8021}"
echo "  Operator API:     http://127.0.0.1:8010/healthz"
