#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/.fdai/rust-fullstack.pids"
if [[ -f "$PID_FILE" ]]; then
  while read -r pid; do
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done < "$PID_FILE"
  rm -f "$PID_FILE"
  echo "[fullstack] Stopped all services."
else
  echo "[fullstack] No active PID file at $PID_FILE"
fi
