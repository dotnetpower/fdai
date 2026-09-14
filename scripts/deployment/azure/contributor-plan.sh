#!/usr/bin/env bash
# Apply one reviewed public-development Terraform plan with durable attempt records.

apply_contributor_plan() {
  local root="$1" plan="$2" state="$3" expected_digest="$4"
  local pending="$plan.pending.json" receipt="$plan.result.$expected_digest.json"
  local answer actor age status=0
  [[ "$expected_digest" =~ ^[0-9a-f]{64}$ && -f "$plan" && ! -L "$plan" ]] || {
    target_log "ERROR: a regular saved Terraform plan and its digest are required"
    return 1
  }
  [[ "$(stat -c '%a:%u' "$plan")" == "600:$EUID" ]] || {
    target_log "ERROR: saved Terraform plan must be owner-only"
    return 1
  }
  [[ ! -e "$pending" && ! -L "$pending" && ! -e "$receipt" && ! -L "$receipt" ]] || {
    target_log "ERROR: prior Terraform attempt exists; verify its outcome before any new apply"
    return 1
  }
  [[ "$(sha256sum "$plan" | cut -d' ' -f1)" == "$expected_digest" ]] || {
    target_log "ERROR: saved Terraform plan changed after preview"
    return 1
  }
  [[ -t 0 ]] || {
    target_log "ERROR: exact Terraform plan approval requires an interactive terminal"
    return 1
  }
  printf 'Approve this Terraform plan by entering its SHA-256 (%s), or Enter to cancel: ' \
    "$expected_digest" >&2
  IFS= read -r answer || return 1
  [[ "$answer" == "$expected_digest" ]] || {
    target_log "ERROR: Terraform plan was not approved"
    return 1
  }
  age=$(( $(date -u +%s) - $(stat -c '%Y' "$plan") ))
  [[ "$(sha256sum "$plan" | cut -d' ' -f1)" == "$expected_digest" ]] \
    && ((age >= 0 && age <= 1200)) || {
    target_log "ERROR: Terraform plan changed or expired; generate a new preview"
    return 1
  }
  [[ "$(git -C "$REPO_ROOT" rev-parse HEAD)" == "$SOURCE_COMMIT" \
    && -z "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)" ]] || {
    target_log "ERROR: Terraform source changed or is not clean; generate a reviewed preview"
    return 1
  }
  /bin/bash "$HERE/verify-azure-context.sh" "$EXPECTED_SUBSCRIPTION" "$EXPECTED_TENANT" || return 1
  actor="$(timeout 30s az ad signed-in-user show --query id --output tsv --only-show-errors)" || return 1
  [[ "$actor" == "$DEPLOYER_OBJECT_ID" ]] || {
    target_log "ERROR: authenticated Terraform approver changed"
    return 1
  }
  python3 - "$pending" "$expected_digest" "$SOURCE_COMMIT" "$actor" <<'PY' || return 1
import datetime
import json
import os
import sys

descriptor = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
    json.dump({"schema_version": "fdai.contributor-apply.v1", "plan_sha256": sys.argv[2],
               "source_commit": sys.argv[3], "approved_by": sys.argv[4], "state": "applying",
               "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}, stream)
    stream.flush()
    os.fsync(stream.fileno())
PY
  timeout 1800s terraform -chdir="$root" apply -input=false -lock-timeout=5m "$plan" || status=$?
  if ((status == 0)); then
    [[ -f "$state" && ! -L "$state" && -s "$state" \
      && "$(stat -c '%a:%u' "$state")" == "600:$EUID" ]] || status=1
    timeout 60s terraform -chdir="$root" state list >/dev/null || status=1
  fi
  python3 - "$pending" "$receipt" "$status" <<'PY' || return 1
import json
import os
import sys
from pathlib import Path

pending = Path(sys.argv[1])
payload = json.loads(pending.read_text(encoding="utf-8"))
payload.update(state="terraform-applied" if sys.argv[3] == "0" else "verification-required",
               exit_code=int(sys.argv[3]), operational_verification="pending")
descriptor = os.open(sys.argv[2], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
    json.dump(payload, stream)
    stream.flush()
    os.fsync(stream.fileno())
if sys.argv[3] == "0":
    pending.unlink()
PY
  if ((status != 0)); then
    target_log "ERROR: Terraform apply requires authoritative outcome verification; do not retry apply"
  fi
  return "$status"
}
