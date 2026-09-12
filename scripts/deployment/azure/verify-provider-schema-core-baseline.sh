#!/usr/bin/env bash
set -euo pipefail

validate_receipt() {
  local path="$1"
  local expected_source_revision="$2"
  local expected_image_digest="$3"
  if [[ -L "$path" || ! -f "$path" || "$(stat -c %s "$path")" -gt 65536 ]]; then
    echo "provider-schema Core baseline receipt is unavailable or too large" >&2
    return 1
  fi
  jq -e \
    --arg source_revision "$expected_source_revision" \
    --arg image_digest "$expected_image_digest" '
      type == "object"
      and .schema_version == "fdai.provider-schema-core-baseline.v1"
      and .source_revision == $source_revision
      and .image_digest == $image_digest
      and (.core_app_ref_digest | type == "string" and test("^[0-9a-f]{64}$"))
      and (.active_revision_ref_digest | type == "string" and test("^[0-9a-f]{64}$"))
      and (.max_inactive_revisions | type == "number")
      and .max_inactive_revisions >= 1
      and .health_state == "Healthy"
      and .provisioning_state == "Provisioned"
      and (.observed_at | type == "string" and test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"))
      and .grants_authority == false
    ' "$path" >/dev/null || {
      echo "provider-schema Core baseline receipt is invalid" >&2
      return 1
    }
}

if [[ "${1:-}" == "--verify-receipt" ]]; then
  receipt_path="${2:-}"
  expected_source_revision="${3:-}"
  expected_image_digest="${4:-}"
  [[ "$expected_source_revision" =~ ^[0-9a-f]{40}$ ]] || {
    echo "provider-schema Core baseline source revision is invalid" >&2
    exit 2
  }
  [[ "$expected_image_digest" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    echo "provider-schema Core baseline image digest is invalid" >&2
    exit 2
  }
  validate_receipt "$receipt_path" "$expected_source_revision" "$expected_image_digest"
  exit
fi

expected_source_revision="${1:-}"
expected_image_digest="${2:-}"
terraform_dir="${3:-.}"
output_path="${4:-}"

[[ "$expected_source_revision" =~ ^[0-9a-f]{40}$ ]] || {
  echo "provider-schema Core baseline source revision is invalid" >&2
  exit 2
}
[[ "$expected_image_digest" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo "provider-schema Core baseline image digest is invalid" >&2
  exit 2
}
[[ -d "$terraform_dir" ]] || {
  echo "provider-schema Core baseline Terraform directory is unavailable" >&2
  exit 2
}
[[ -n "$output_path" && ! -L "$output_path" ]] || {
  echo "provider-schema Core baseline output path is invalid" >&2
  exit 2
}
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"

resource_group="$(terraform -chdir="$terraform_dir" output -raw resource_group_name)"
core_app="$(terraform -chdir="$terraform_dir" output -raw core_app_name)"
[[ "$resource_group" =~ ^[A-Za-z0-9][A-Za-z0-9_.()-]{0,89}$ ]] || {
  echo "provider-schema Core baseline resource group is invalid" >&2
  exit 1
}
[[ "$core_app" =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]] || {
  echo "provider-schema Core baseline app name is invalid" >&2
  exit 1
}

umask 077
app_evidence="$(mktemp "$RUNNER_TEMP/provider-schema-core-app.XXXXXX.json")"
revision_evidence="$(mktemp "$RUNNER_TEMP/provider-schema-core-revision.XXXXXX.json")"
receipt="$(mktemp "$RUNNER_TEMP/provider-schema-core-baseline.XXXXXX.json")"
trap 'rm -f -- "$app_evidence" "$revision_evidence" "$receipt"' EXIT

timeout 60s az containerapp show \
  --resource-group "$resource_group" \
  --name "$core_app" \
  --only-show-errors --output json > "$app_evidence"
read -r active_revision ready_revision max_inactive_revisions < <(
  jq -er '
    [
      (.properties.latestRevisionName | select(type == "string")),
      (.properties.latestReadyRevisionName | select(type == "string")),
      (.properties.configuration.maxInactiveRevisions
        | select(type == "number" and . >= 1))
    ] | @tsv
  ' "$app_evidence"
)
revision_pattern='^[a-z0-9][a-z0-9-]{1,127}$'
if [[ ! "$active_revision" =~ $revision_pattern || "$active_revision" != "$ready_revision" ]]; then
  echo "provider-schema Core baseline has no exact ready active revision" >&2
  exit 1
fi

timeout 60s az containerapp revision show \
  --resource-group "$resource_group" \
  --name "$core_app" \
  --revision "$active_revision" \
  --only-show-errors --output json > "$revision_evidence"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
binding="$(python3 "$script_dir/verify_active_core_revision.py" --revision "$revision_evidence")"
active_image_digest="$(jq -er '.image_digest | select(test("^[0-9a-f]{64}$"))' <<< "$binding")"
active_source_revision="$(
  jq -er '
    [
      .properties.template.containers[]
      | select(.name == "core-control-plane")
      | .env[]
      | select(.name == "FDAI_SOURCE_REVISION")
      | .value
      | select(type == "string" and test("^[0-9a-f]{40}$"))
    ] | select(length == 1) | .[0]
  ' "$revision_evidence"
)"
[[ "$active_source_revision" == "$expected_source_revision" ]] || {
  echo "active Core source revision does not match the provider-schema candidate" >&2
  exit 1
}
[[ "sha256:$active_image_digest" == "$expected_image_digest" ]] || {
  echo "active Core image digest does not match the provider-schema candidate" >&2
  exit 1
}

observed_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
core_app_ref_digest="$(printf '%s/%s' "$resource_group" "$core_app" | sha256sum | cut -d' ' -f1)"
active_revision_ref_digest="$(printf '%s' "$active_revision" | sha256sum | cut -d' ' -f1)"
jq -n \
  --arg source_revision "$active_source_revision" \
  --arg image_digest "$expected_image_digest" \
  --arg core_app_ref_digest "$core_app_ref_digest" \
  --arg active_revision_ref_digest "$active_revision_ref_digest" \
  --arg observed_at "$observed_at" \
  --argjson max_inactive_revisions "$max_inactive_revisions" '
    {
      schema_version: "fdai.provider-schema-core-baseline.v1",
      source_revision: $source_revision,
      image_digest: $image_digest,
      core_app_ref_digest: $core_app_ref_digest,
      active_revision_ref_digest: $active_revision_ref_digest,
      max_inactive_revisions: $max_inactive_revisions,
      health_state: "Healthy",
      provisioning_state: "Provisioned",
      observed_at: $observed_at,
      grants_authority: false
    }
  ' > "$receipt"
validate_receipt "$receipt" "$expected_source_revision" "$expected_image_digest"
install -m 0600 "$receipt" "$output_path"

echo "Exact healthy Core rollback baseline verified for provider-schema deployment." \
  >> "$GITHUB_STEP_SUMMARY"