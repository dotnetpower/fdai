#!/usr/bin/env bash
# Apply one reviewed public-development Terraform plan with durable attempt records.

recover_contributor_plan_attempt() {
  local root="$1" plan="$2" state="$3" pending="$2.pending.json"
  [[ -e "$pending" || -L "$pending" ]] || return 0
  local metadata digest prior_source prior_actor result recovery_plan recovery_receipt
  [[ -f "$pending" && ! -L "$pending" && "$(stat -c '%a:%u' "$pending")" == "600:$EUID" ]] || {
    target_log "ERROR: prior Terraform attempt record is not an owner-only regular file"
    return 1
  }
  metadata="$(python3 - "$pending" <<'PY'
import json
import re
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
digest = payload.get("plan_sha256", "")
source = payload.get("source_commit", "")
actor = payload.get("approved_by", "")
if (
    payload.get("schema_version") != "fdai.contributor-apply.v1"
    or payload.get("state") != "applying"
    or re.fullmatch(r"[0-9a-f]{64}", digest) is None
    or re.fullmatch(r"[0-9a-f]{40}", source) is None
    or re.fullmatch(r"[0-9a-fA-F-]{36}", actor) is None
):
    raise SystemExit("prior Terraform attempt record is invalid")
print(digest, source, actor, sep="\n")
PY
)" || {
    target_log "ERROR: prior Terraform attempt record is invalid"
    return 1
  }
  mapfile -t fields <<<"$metadata"
  digest="${fields[0]:-}"
  prior_source="${fields[1]:-}"
  prior_actor="${fields[2]:-}"
  result="$plan.result.$digest.json"
  recovery_plan="$plan.recovery.$digest.tfplan"
  recovery_receipt="$plan.recovery.$digest.json"
  [[ -f "$plan" && ! -L "$plan" && "$(stat -c '%a:%u' "$plan")" == "600:$EUID" \
    && "$(sha256sum "$plan" | cut -d' ' -f1)" == "$digest" \
    && -f "$result" && ! -L "$result" && "$(stat -c '%a:%u' "$result")" == "600:$EUID" \
    && ! -e "$recovery_plan" && ! -L "$recovery_plan" \
    && ! -e "$recovery_receipt" && ! -L "$recovery_receipt" ]] || {
    target_log "ERROR: prior Terraform attempt artifacts are incomplete or changed"
    return 1
  }
  trap 'rm -f -- "$recovery_plan"' RETURN
  python3 - "$pending" "$result" <<'PY' || {
import json
import sys

pending = json.load(open(sys.argv[1], encoding="utf-8"))
result = json.load(open(sys.argv[2], encoding="utf-8"))
for key in ("schema_version", "plan_sha256", "source_commit", "approved_by", "recorded_at"):
    if result.get(key) != pending.get(key):
        raise SystemExit("prior Terraform result does not match its attempt")
if (
    result.get("state") != "verification-required"
    or not isinstance(result.get("exit_code"), int)
    or result["exit_code"] == 0
    or result.get("operational_verification") != "pending"
):
    raise SystemExit("prior Terraform result is not recoverable")
PY
    target_log "ERROR: prior Terraform result is invalid"
    return 1
  }
  [[ "$(git -C "$REPO_ROOT" rev-parse HEAD)" == "$SOURCE_COMMIT" \
    && -z "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)" ]] \
    && git -C "$REPO_ROOT" merge-base --is-ancestor "$prior_source" "$SOURCE_COMMIT" || {
    target_log "ERROR: recovery requires clean descendant source"
    return 1
  }
  /bin/bash "$HERE/verify-azure-context.sh" "$EXPECTED_SUBSCRIPTION" "$EXPECTED_TENANT" || return 1
  [[ "$(timeout 30s az ad signed-in-user show --query id --output tsv --only-show-errors)" == "$prior_actor" \
    && "$DEPLOYER_OBJECT_ID" == "$prior_actor" ]] || {
    target_log "ERROR: authenticated Terraform recovery actor changed"
    return 1
  }
  [[ -f "$state" && ! -L "$state" && -s "$state" \
    && "$(stat -c '%a:%u' "$state")" == "600:$EUID" ]] || {
    target_log "ERROR: prior Terraform state is not an owner-only regular file"
    return 1
  }
  timeout 300s terraform -chdir="$root" init -reconfigure -input=false -lockfile=readonly || return 1
  local refresh_status=0 resource_count state_digest refresh_digest
  timeout 900s terraform -chdir="$root" plan -refresh-only -input=false -lock-timeout=5m \
    -detailed-exitcode -out="$recovery_plan" || refresh_status=$?
  if ((refresh_status != 0 && refresh_status != 2)); then
    target_log "ERROR: authoritative Terraform refresh failed; prior apply remains fenced"
    return 1
  fi
  chmod 0600 "$recovery_plan"
  resource_count="$(timeout 60s terraform -chdir="$root" state list | wc -l)" || return 1
  [[ "$resource_count" =~ ^[0-9]+$ && "$resource_count" -gt 0 ]] || return 1
  state_digest="$(sha256sum "$state" | cut -d' ' -f1)"
  refresh_digest="$(sha256sum "$recovery_plan" | cut -d' ' -f1)"
  python3 - "$pending" "$result" "$recovery_receipt" "$SOURCE_COMMIT" \
    "$refresh_status" "$resource_count" "$state_digest" "$refresh_digest" <<'PY' || return 1
import datetime
import json
import os
import sys
from pathlib import Path

pending_path = Path(sys.argv[1])
pending = json.loads(pending_path.read_text(encoding="utf-8"))
result = json.load(open(sys.argv[2], encoding="utf-8"))
payload = {
    "schema_version": "fdai.contributor-recovery.v1",
    "plan_sha256": pending["plan_sha256"],
    "source_commit": pending["source_commit"],
    "verified_source_commit": sys.argv[4],
    "approved_by": pending["approved_by"],
    "failed_exit_code": result["exit_code"],
    "refresh_exit_code": int(sys.argv[5]),
    "tracked_resource_count": int(sys.argv[6]),
    "state_sha256": sys.argv[7],
    "refresh_plan_sha256": sys.argv[8],
    "state": "failed-apply-observed",
    "operational_verification": "observed",
    "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
descriptor = os.open(sys.argv[3], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
    json.dump(payload, stream)
    stream.flush()
    os.fsync(stream.fileno())
pending_path.unlink()
PY
  target_log "Prior Terraform failure was observed through refresh-only verification; replay fence closed."
}

require_public_contributor_key_vault_path() {
  local root="$1" address="module.key_vault.azurerm_key_vault.primary"
  local addresses vault_id public_access
  addresses="$(timeout 60s terraform -chdir="$root" state list)" || {
    target_log "ERROR: platform Terraform state is unreadable before data-plane preflight"
    return 1
  }
  grep -Fxq "$address" <<<"$addresses" || return 0
  vault_id="$(timeout 60s terraform -chdir="$root" state show -no-color "$address" \
    | sed -nE 's/^[[:space:]]*id[[:space:]]*=[[:space:]]*"([^"]+)"[[:space:]]*$/\1/p')"
  [[ "$vault_id" == /subscriptions/*/providers/Microsoft.KeyVault/vaults/* ]] || {
    target_log "ERROR: tracked Key Vault id is invalid"
    return 1
  }
  public_access="$(timeout 30s az resource show --ids "$vault_id" --api-version 2023-07-01 \
    --query properties.publicNetworkAccess --output tsv --only-show-errors)" || {
    target_log "ERROR: Key Vault network posture readback failed"
    return 1
  }
  [[ "$public_access" == "Enabled" ]] || {
    target_log "ERROR: existing Key Vault requires a private data-plane path; use fdai-up.sh with the managed deployment host"
    return 1
  }
}

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
