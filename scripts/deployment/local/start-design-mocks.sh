#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "Usage: $0" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root"

if ! command -v python3 >/dev/null 2>&1; then
  echo "missing python3: install Python 3 before starting the design mock server" >&2
  exit 1
fi

runner="$repo_root/scripts/automation/run-local-service.sh"
input_digest="$(sha256sum \
  "$repo_root/scripts/deployment/local/start-design-mocks.sh" \
  "$runner" \
  "$repo_root/scripts/automation/run-local-service-child.py" \
  "$repo_root/scripts/automation/capture-local-service-log.py" \
  | sha256sum | cut -d' ' -f1)"

export FDAI_LOCAL_SERVICE_REUSE_EXISTING=1
export FDAI_LOCAL_SERVICE_RESTART_STALE=0
export FDAI_LOCAL_SERVICE_INPUT_DIGEST="$input_digest"
export FDAI_LOCAL_SERVICE_LOG_FORMAT=raw

exec bash "$runner" design-mocks "$repo_root/.fdai/local-logs/design-mocks.log" -- \
  env PORT=5373 python3 -u -m http.server 5373 --bind 127.0.0.1
