#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
terraform_dir="${repository_root}/infra"
evidence_file=""
live_mode=0

usage() {
  cat <<'EOF'
Usage: check-ingestion-effective-access.sh [options]

Validate the Terraform ingestion access ceiling without changing Azure.

Options:
  --terraform-dir DIR  Terraform root that owns the evidence output.
  --evidence-file FILE Read a raw evidence JSON value instead of Terraform state.
  --live                Compare inherited Azure RBAC and PostgreSQL roles read-only.
  -h, --help            Show this help.

Live mode requires FDAI_INGESTION_EVIDENCE_DATABASE_URL and uses only:
  az role assignment list --include-inherited
  psql with default_transaction_read_only=on
EOF
}

fail() {
  printf 'SD-03 effective-access gate failed: %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

while (( $# > 0 )); do
  case "$1" in
    --terraform-dir)
      (( $# >= 2 )) || fail "--terraform-dir requires a value"
      terraform_dir="$2"
      shift 2
      ;;
    --evidence-file)
      (( $# >= 2 )) || fail "--evidence-file requires a value"
      evidence_file="$2"
      shift 2
      ;;
    --live)
      live_mode=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

require_command jq

if [[ -n "${evidence_file}" ]]; then
  [[ -f "${evidence_file}" ]] || fail "evidence file does not exist"
  evidence_json="$(<"${evidence_file}")"
else
  require_command terraform
  evidence_json="$(
    terraform -chdir="${terraform_dir}" output -json ingestion_effective_access_evidence
  )" || fail "Terraform evidence output is unavailable"
fi

if ! jq -e '
  def valid_role:
    (.role_name | type == "string" and length > 0) and
    (.scope | type == "string" and length > 0);
  def valid_identity:
    (.present | type == "boolean") and
    (.principal_id | type == "string") and
    (.database_role | test("^[a-z_][a-z0-9_]{0,62}$")) and
    (.expected_role_assignments | type == "array") and
    (all(.expected_role_assignments[]; valid_role)) and
    (
      [.expected_role_assignments[] | "\(.role_name)|\(.scope | ascii_downcase)"] |
      length == (unique | length)
    );
  .contract_version == "1.0" and
  .evidence_class == "terraform-static" and
  .enabled == true and
  (.topology == "split" or .topology == "cohost") and
  (.executor.principal_id | type == "string" and length > 0) and
  (.executor.authority_role_names == ["Azure Event Hubs Data Owner"]) and
  (.identities | keys == ["api", "migration", "worker"]) and
  (all(.identities[]; valid_identity)) and
  .identities.api.present and
  .identities.migration.present and
  .checks.identities_distinct_from_executor and
  .checks.runtime_identities_are_distinct and
  (.checks.executor_authority_role_overlap | length == 0) and
  (.identities.api.principal_id != .executor.principal_id) and
  (.identities.migration.principal_id != .executor.principal_id) and
  (.identities.api.principal_id != .identities.migration.principal_id) and
  (.identities.api.database_role != .identities.migration.database_role) and
  (
    .executor.authority_role_names as $executor_roles |
    all(
      .identities[].expected_role_assignments[];
      .role_name as $role_name |
      ($executor_roles | index($role_name) | not)
    )
  ) and
  (
    [
      .identities.api.database_role,
      .identities.worker.database_role,
      .identities.migration.database_role,
      .cohost_rollback.api_database_role
    ] |
    length == (unique | length)
  ) and
  (.cohost_rollback.flag == "ingestion_cohost_worker") and
  (.cohost_rollback.api_database_role == "fdai_ingestion_cohost") and
  (.cohost_rollback.adls_owner == "api") and
  (.cohost_rollback.eventhubs_receive_owner == "api") and
  (.cohost_rollback.worker_identity_present == false) and
  .cohost_rollback.migration_identity_preserved and
  .cohost_rollback.executor_identity_preserved and
  (
    if .topology == "split" then
      .identities.worker.present and
      (.identities.worker.principal_id | length > 0) and
      (.identities.worker.principal_id != .executor.principal_id) and
      (.identities.worker.principal_id != .identities.api.principal_id) and
      (.identities.worker.principal_id != .identities.migration.principal_id) and
      (.identities.worker.database_role == "fdai_ingestion_worker")
    else
      (.identities.worker.present == false) and
      (.identities.worker.principal_id == "") and
      (.identities.worker.expected_role_assignments | length == 0) and
      (.identities.api.database_role == .cohost_rollback.api_database_role)
    end
  )
' <<<"${evidence_json}" >/dev/null; then
  fail "Terraform evidence contract is invalid or reports an authority overlap"
fi

printf 'PASS static: Terraform pins ingestion identities, role ceilings, resource scopes, database roles, and co-host rollback mapping.\n'

if (( live_mode == 0 )); then
  printf 'NOT RUN live: Azure inherited RBAC and PostgreSQL role state still require --live evidence.\n'
  exit 0
fi

require_command az
require_command psql
database_url="${FDAI_INGESTION_EVIDENCE_DATABASE_URL:-}"
[[ -n "${database_url}" ]] || fail "FDAI_INGESTION_EVIDENCE_DATABASE_URL is required for --live"

for identity_name in api worker migration; do
  present="$(jq -r --arg name "${identity_name}" '.identities[$name].present' <<<"${evidence_json}")"
  if [[ "${present}" != "true" ]]; then
    continue
  fi

  principal_id="$(
    jq -r --arg name "${identity_name}" '.identities[$name].principal_id' <<<"${evidence_json}"
  )"
  expected_assignments="$(
    jq -c --arg name "${identity_name}" '
      .identities[$name].expected_role_assignments |
      map({role_name, scope: (.scope | ascii_downcase)}) |
      sort_by(.role_name, .scope)
    ' <<<"${evidence_json}"
  )"
  actual_raw="$(
    az role assignment list \
      --all \
      --output json \
      --only-show-errors
  )" || fail "Azure RBAC query failed for ${identity_name}"
  actual_assignments="$(
    jq -ce --arg principal_id "${principal_id}" '
      map(select((.principalId // "" | ascii_downcase) == ($principal_id | ascii_downcase))) |
      map({role_name: .roleDefinitionName, scope: (.scope | ascii_downcase)}) |
      unique |
      sort_by(.role_name, .scope)
    ' <<<"${actual_raw}"
  )" || fail "Azure RBAC response was malformed for ${identity_name}"

  if [[ "${actual_assignments}" != "${expected_assignments}" ]]; then
    fail "effective Azure RBAC exceeds or misses the ${identity_name} ceiling"
  fi
done

database_roles="$(
  jq -r '
    [
      .identities.api.database_role,
      .identities.worker.database_role,
      .identities.migration.database_role,
      .cohost_rollback.api_database_role
    ] |
    unique |
    join(",")
  ' <<<"${evidence_json}"
)"
database_rows="$(
  PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=15000' \
    psql "${database_url}" \
      -X \
      -A \
      -t \
      -v ON_ERROR_STOP=1 \
      -c "SELECT rolname || '|' || rolsuper || '|' || rolcreatedb || '|' || rolcreaterole || '|' || rolcanlogin FROM pg_roles WHERE rolname = ANY(string_to_array('${database_roles}', ',')) ORDER BY rolname"
)" || fail "PostgreSQL role query failed"

for runtime_role in fdai_ingestion_api fdai_ingestion_worker fdai_ingestion_cohost; do
  if ! grep -Fqx "${runtime_role}|false|false|false|false" <<<"${database_rows}"; then
    fail "PostgreSQL runtime role is missing or exceeds its non-privileged ceiling: ${runtime_role}"
  fi
done

migration_role="$(jq -r '.identities.migration.database_role' <<<"${evidence_json}")"
if ! grep -Eq "^${migration_role}\\|" <<<"${database_rows}"; then
  fail "PostgreSQL migration role is missing"
fi

printf 'PASS live: Azure inherited RBAC exactly matches Terraform and PostgreSQL roles satisfy the runtime ceiling.\n'
