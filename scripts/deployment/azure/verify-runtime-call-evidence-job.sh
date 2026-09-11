#!/usr/bin/env bash
set -euo pipefail

source_commit="${1:-}"
plan_id="${2:-}"
output_path="${3:-}"

[[ "$source_commit" =~ ^[0-9a-f]{40}$ ]] || {
  echo "runtime-call evidence source commit is invalid" >&2
  exit 2
}
[[ "$plan_id" =~ ^plan-[1-9][0-9]*-[1-9][0-9]*$ ]] || {
  echo "runtime-call evidence plan id is invalid" >&2
  exit 2
}
[[ -n "$output_path" ]] || {
  echo "runtime-call evidence readback output path is required" >&2
  exit 2
}
: "${TF_VAR_env:?TF_VAR_env is required}"
: "${TF_VAR_region_short:?TF_VAR_region_short is required}"

job="$(terraform output -raw inventory_job_name)"
[[ -n "$job" && "$job" != *$'\n'* ]] || {
  echo "runtime-call evidence Inventory Job is unavailable" >&2
  exit 1
}
enabled="$(
  az containerapp job show --name "$job" \
    --resource-group "rg-fdai-${TF_VAR_env}-${TF_VAR_region_short}" \
    --query "properties.template.containers[?name=='inventory'] | [0].env[?name=='FDAI_RUNTIME_CALL_EVIDENCE_ENABLED'] | [0].value" \
    --output tsv --only-show-errors
)"
[[ "$enabled" == "1" ]] || {
  echo "runtime-call evidence Inventory Job binding is not enabled" >&2
  exit 1
}

RUNTIME_CALL_EVIDENCE_JOB="$job" \
RUNTIME_CALL_EVIDENCE_SOURCE_COMMIT="$source_commit" \
RUNTIME_CALL_EVIDENCE_PLAN_ID="$plan_id" \
python3 - "$output_path" <<'PY'
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

output = Path(sys.argv[1])
temporary = output.with_suffix(output.suffix + ".tmp")
receipt = {
    "schema_version": "fdai.runtime-call-evidence-job-readback.v1",
    "source_commit": os.environ["RUNTIME_CALL_EVIDENCE_SOURCE_COMMIT"],
    "plan_id": os.environ["RUNTIME_CALL_EVIDENCE_PLAN_ID"],
    "resource_ref_digest": hashlib.sha256(
        os.environ["RUNTIME_CALL_EVIDENCE_JOB"].encode()
    ).hexdigest(),
    "binding": "FDAI_RUNTIME_CALL_EVIDENCE_ENABLED",
    "value": "1",
    "verified_at": datetime.now(UTC).isoformat(),
}
temporary.write_text(
    json.dumps(receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n",
    encoding="utf-8",
)
temporary.replace(output)
PY
