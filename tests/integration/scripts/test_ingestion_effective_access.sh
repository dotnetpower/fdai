#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
gate="${repository_root}/scripts/deployment/azure/check-ingestion-effective-access.sh"
work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT

mkdir -p "${work_dir}/bin"

cat >"${work_dir}/evidence.json" <<'EOF'
{
  "contract_version": "1.0",
  "evidence_class": "terraform-static",
  "enabled": true,
  "topology": "split",
  "executor": {
    "principal_id": "executor-principal",
    "authority_role_names": ["Azure Event Hubs Data Owner"]
  },
  "identities": {
    "api": {
      "present": true,
      "principal_id": "api-principal",
      "database_role": "fdai_ingestion_api",
      "expected_role_assignments": [
        {"role_name": "AcrPull", "scope": "/registries/fdai"},
        {"role_name": "Azure Event Hubs Data Sender", "scope": "/eventhubs/aw.pipeline.stages"},
        {"role_name": "Cognitive Services OpenAI User", "scope": "/models/fdai"},
        {"role_name": "Key Vault Secrets User", "scope": "/secrets/ingestion-api-dsn"},
        {"role_name": "Storage Blob Data Contributor", "scope": "/storage/documents"}
      ]
    },
    "worker": {
      "present": true,
      "principal_id": "worker-principal",
      "database_role": "fdai_ingestion_worker",
      "expected_role_assignments": [
        {"role_name": "AcrPull", "scope": "/registries/fdai"},
        {"role_name": "Azure Event Hubs Data Receiver", "scope": "/eventhubs/aw.pantheon.objects"},
        {"role_name": "Azure Event Hubs Data Sender", "scope": "/eventhubs/aw.pipeline.stages"},
        {"role_name": "Cognitive Services OpenAI User", "scope": "/models/fdai"},
        {"role_name": "Key Vault Secrets User", "scope": "/secrets/ingestion-worker-dsn"},
        {"role_name": "Storage Blob Data Contributor", "scope": "/storage/documents"}
      ]
    },
    "migration": {
      "present": true,
      "principal_id": "migration-principal",
      "database_role": "fdaiadmin",
      "expected_role_assignments": [
        {"role_name": "AcrPull", "scope": "/registries/fdai"},
        {"role_name": "Key Vault Secrets User", "scope": "/secrets/state-store-dsn"}
      ]
    }
  },
  "checks": {
    "identities_distinct_from_executor": true,
    "runtime_identities_are_distinct": true,
    "executor_authority_role_overlap": []
  },
  "cohost_rollback": {
    "flag": "ingestion_cohost_worker",
    "api_database_role": "fdai_ingestion_cohost",
    "adls_owner": "api",
    "eventhubs_receive_owner": "api",
    "worker_identity_present": false,
    "migration_identity_preserved": true,
    "executor_identity_preserved": true,
    "independent_worker_restore_target": "split"
  },
  "live_evidence_required": [
    "Azure effective role assignments including inherited scopes",
    "PostgreSQL role existence and non-privileged runtime attributes"
  ]
}
EOF

jq '[.identities.api.expected_role_assignments[] | {
  principalId: "api-principal",
  roleDefinitionName: .role_name,
  scope: .scope
}]' "${work_dir}/evidence.json" >"${work_dir}/api.json"
jq '[.identities.worker.expected_role_assignments[] | {
  principalId: "worker-principal",
  roleDefinitionName: .role_name,
  scope: .scope
}]' "${work_dir}/evidence.json" >"${work_dir}/worker.json"
jq '[.identities.migration.expected_role_assignments[] | {
  principalId: "migration-principal",
  roleDefinitionName: .role_name,
  scope: .scope
}]' "${work_dir}/evidence.json" >"${work_dir}/migration.json"

cat >"${work_dir}/bin/az" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
jq -s 'add' \
  "${MOCK_EVIDENCE_DIR}/api.json" \
  "${MOCK_EVIDENCE_DIR}/worker.json" \
  "${MOCK_EVIDENCE_DIR}/migration.json"
EOF
chmod +x "${work_dir}/bin/az"

cat >"${work_dir}/bin/psql" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' \
  'fdai_ingestion_api|false|false|false|false' \
  'fdai_ingestion_cohost|false|false|false|false' \
  'fdai_ingestion_worker|false|false|false|false' \
  'fdaiadmin|false|true|true|true'
EOF
chmod +x "${work_dir}/bin/psql"

static_output="$(bash "${gate}" --evidence-file "${work_dir}/evidence.json")"
grep -Fq 'PASS static:' <<<"${static_output}"
grep -Fq 'NOT RUN live:' <<<"${static_output}"

live_output="$(
  PATH="${work_dir}/bin:${PATH}" \
  MOCK_EVIDENCE_DIR="${work_dir}" \
  FDAI_INGESTION_EVIDENCE_DATABASE_URL="postgresql://evidence.invalid/fdai" \
    bash "${gate}" --evidence-file "${work_dir}/evidence.json" --live
)"
grep -Fq 'PASS live:' <<<"${live_output}"

jq '.checks.executor_authority_role_overlap = ["Azure Event Hubs Data Owner"]' \
  "${work_dir}/evidence.json" >"${work_dir}/overlap.json"
if bash "${gate}" --evidence-file "${work_dir}/overlap.json" >/dev/null 2>&1; then
  printf 'expected executor authority overlap to fail closed\n' >&2
  exit 1
fi

jq '.identities.worker.principal_id = .executor.principal_id' \
  "${work_dir}/evidence.json" >"${work_dir}/identity-overlap.json"
if bash "${gate}" --evidence-file "${work_dir}/identity-overlap.json" >/dev/null 2>&1; then
  printf 'expected executor identity overlap to fail closed\n' >&2
  exit 1
fi

jq '. += [{
  "principalId": "api-principal",
  "roleDefinitionName": "Reader",
  "scope": "/subscriptions/example"
}]' \
  "${work_dir}/api.json" >"${work_dir}/api-extra.json"
mv "${work_dir}/api-extra.json" "${work_dir}/api.json"
if PATH="${work_dir}/bin:${PATH}" \
  MOCK_EVIDENCE_DIR="${work_dir}" \
  FDAI_INGESTION_EVIDENCE_DATABASE_URL="postgresql://evidence.invalid/fdai" \
    bash "${gate}" --evidence-file "${work_dir}/evidence.json" --live >/dev/null 2>&1; then
  printf 'expected inherited Azure RBAC above the ceiling to fail closed\n' >&2
  exit 1
fi

printf 'PASS shell: static, live, role-overlap, identity-overlap, and inherited-role cases.\n'
