#!/usr/bin/env bash
set -euo pipefail

readonly budget_seconds=900
repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
readonly repository_root
SECONDS=0

remaining_budget() {
  printf '%s' "$(( budget_seconds - SECONDS ))"
}

run_with_budget() {
  local remaining_seconds
  remaining_seconds="$(remaining_budget)"
  if (( remaining_seconds <= 0 )); then
    printf 'SD-03 rollback rehearsal exhausted its %ss budget.\n' \
      "${budget_seconds}" >&2
    exit 1
  fi
  timeout "${remaining_seconds}s" "$@"
}

require_source_contract() {
  local file_path="$1"
  local expected_text="$2"
  local contract_name="$3"
  if ! grep -Fq -- "${expected_text}" "${file_path}"; then
    printf 'SD-03 source contract changed: %s\n' "${contract_name}" >&2
    exit 1
  fi
}

require_source_contract_count() {
  local file_path="$1"
  local expected_text="$2"
  local expected_count="$3"
  local contract_name="$4"
  local actual_count
  actual_count="$(grep -Fc -- "${expected_text}" "${file_path}" || true)"
  if (( actual_count != expected_count )); then
    printf 'SD-03 source contract changed: %s (expected %s, found %s)\n' \
      "${contract_name}" "${expected_count}" "${actual_count}" >&2
    exit 1
  fi
}

require_source_contract \
  "${repository_root}/src/fdai/delivery/ingestion_gateway/worker_service.py" \
  'group_id: str = "fdai-document-audit-gated-worker"' \
  'consumer group'
require_source_contract \
  "${repository_root}/src/fdai/delivery/ingestion_gateway/prod.py" \
  'auto_offset_reset="earliest"' \
  'offset reset policy'
require_source_contract \
  "${repository_root}/src/fdai/delivery/ingestion_gateway/prod.py" \
  '"aw.pantheon.objects"' \
  'pantheon physical topic'
require_source_contract \
  "${repository_root}/src/fdai/delivery/persistence/postgres_document_ingestion.py" \
  'INSERT INTO document_worker_claim' \
  'durable claim namespace'
require_source_contract_count \
  "${repository_root}/infra/main.tf" \
  'scope                = module.event_bus.auxiliary_topic_ids["aw.pipeline.stages"]' \
  3 \
  'pipeline stage role scopes'
require_source_contract_count \
  "${repository_root}/infra/main.tf" \
  'scope                = module.event_bus.topic_ids["aw.pantheon.objects"]' \
  2 \
  'pantheon object role scopes'

run_with_budget terraform -chdir="${repository_root}/infra" init \
  -backend=false \
  -input=false
run_with_budget terraform -chdir="${repository_root}/infra" test \
  -filter=tests/ingestion_roles.tftest.hcl \
  -filter=tests/ingestion_rollback_rehearsal.tftest.hcl

readonly elapsed_seconds="${SECONDS}"
if (( elapsed_seconds >= budget_seconds )); then
  printf 'SD-03 rollback rehearsal exceeded budget: %ss >= %ss\n' \
    "${elapsed_seconds}" "${budget_seconds}" >&2
  exit 1
fi

printf 'SD-03 rollback rehearsal passed in %ss (budget: %ss).\n' \
  "${elapsed_seconds}" "${budget_seconds}"
printf '%s\n' \
  'Simulated: Terraform mock-provider state only; no Azure credentials or Azure API mutation.'
printf '%s\n' \
  'Remaining live evidence: revision readiness, Event Hubs lag/offset continuity, PostgreSQL claim ownership, and effective identity access.'
