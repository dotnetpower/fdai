#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${repo_root}" ]]; then
  echo "verify-productization: repository root could not be resolved" >&2
  exit 1
fi
cd "$repo_root"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

python_paths=(
  services/core-control-plane/src/fdai/deployment_cli
  services/core-control-plane/src/fdai/composition/wire_llm.py
  services/core-control-plane/src/fdai/core/capability_catalog
  services/core-control-plane/src/fdai/core/conversation/channel_access.py
  services/core-control-plane/src/fdai/core/conversation/channel_gateway.py
  services/core-control-plane/src/fdai/core/conversation/coordinator.py
  services/core-control-plane/src/fdai/core/conversation/identity_links.py
  services/core-control-plane/src/fdai/core/conversation/narrator.py
  services/core-control-plane/src/fdai/core/conversation/tool_discovery.py
  services/core-control-plane/src/fdai/core/rpc
  services/core-control-plane/src/fdai/core/sandbox
  services/core-control-plane/src/fdai/core/supply_chain
  services/core-control-plane/src/fdai/core/operator_memory
  services/core-control-plane/src/fdai/core/scheduler
  services/core-control-plane/src/fdai/core/skills
  services/core-control-plane/src/fdai/delivery/channels
  services/core-control-plane/src/fdai/delivery/azure/llm
  services/core-control-plane/src/fdai/delivery/azure/preflight
  services/core-control-plane/src/fdai/delivery/github/deployment_workflow.py
  services/core-control-plane/src/fdai/delivery/trust
  services/core-control-plane/src/fdai/delivery/ingestion_gateway/main.py
  services/core-control-plane/src/fdai/delivery/knowledge
  scripts/deployment/azure/cleanup-deployment-plans.py
  scripts/deployment/azure/check-runner-egress.py
  scripts/deployment/release/build-deployment-bundle.py
  scripts/deployment/release/build-offline-kit.py
  scripts/deployment/release/issue-license.py
  scripts/deployment/azure/verify-deployment-plan.py
  services/core-control-plane/src/fdai/shared/providers/conversation_channel.py
  services/core-control-plane/src/fdai/shared/providers/document_converter.py
  services/core-control-plane/src/fdai/shared/providers/local/document_ingestion.py
  services/core-control-plane/src/fdai/shared/telemetry
  services/core-control-plane/src/fdai/delivery/mcp
  services/core-control-plane/src/fdai/delivery/operator_api/routes/scheduler_runs.py
  services/core-control-plane/src/fdai/delivery/rpc
  services/core-control-plane/src/fdai/delivery/webhook
  services/core-control-plane/src/fdai/delivery/persistence/postgres_schedule_run_ledger.py
  services/core-control-plane/src/fdai/delivery/persistence/postgres_scheduler_store.py
  services/core-control-plane/src/fdai/delivery/persistence/postgres_channel_pairing.py
  services/core-control-plane/src/fdai/delivery/persistence/postgres_channel_identity_link.py
  services/core-control-plane/src/fdai/delivery/persistence/postgres_skill_proposal.py
  services/core-control-plane/src/fdai/delivery/persistence/postgres_model_health.py
  services/core-control-plane/src/fdai/delivery/persistence/postgres_memory_compaction.py
  services/core-control-plane/src/fdai/delivery/persistence/postgres_operator_memory.py
  services/core-control-plane/src/fdai/delivery/persistence/postgres_trusted_artifact.py
  services/core-control-plane/src/fdai/delivery/persistence/postgres_rpc_idempotency.py
  services/core-control-plane/src/fdai/rule_catalog/schema/llm_registry.py
  services/core-control-plane/src/fdai/rule_catalog/schema/llm_resolver.py
  services/core-control-plane/src/fdai/rule_catalog/schema/model_endpoint.py
)

test_paths=(
  tests/deployment_cli
  tests/integration/infra/test_apim_ai_gateway.py
  tests/integration/test_composition_llm.py
  services/core-control-plane/tests/core/capability_catalog
  services/core-control-plane/tests/core/rpc
  services/core-control-plane/tests/core/sandbox
  services/core-control-plane/tests/core/supply_chain
  services/core-control-plane/tests/core/operator_memory
  services/core-control-plane/tests/core/scheduler
  services/core-control-plane/tests/core/skills
  tests/conversation
  services/core-control-plane/tests/delivery/channels
  services/core-control-plane/tests/delivery/azure/llm
  services/core-control-plane/tests/delivery/azure/preflight
  services/core-control-plane/tests/delivery/github/test_deployment_workflow.py
  services/core-control-plane/tests/delivery/trust
  services/core-control-plane/tests/delivery/ingestion_gateway/test_main.py
  services/core-control-plane/tests/delivery/knowledge/test_loader.py
  tests/integration/scripts/test_cleanup_deployment_plans.py
  tests/integration/scripts/test_check_runner_egress.py
  tests/integration/scripts/test_build_deployment_bundle.py
  tests/integration/scripts/test_build_offline_kit.py
  tests/integration/scripts/test_issue_license.py
  tests/integration/scripts/test_release_deployment_bundle_workflow.py
  tests/integration/scripts/test_verify_deployment_plan.py
  services/core-control-plane/tests/core/document_ingestion/test_document_ingestion.py
  services/core-control-plane/tests/shared/test_transition_telemetry.py
  services/core-control-plane/tests/delivery/mcp
  services/core-control-plane/tests/delivery/operator_api/test_scheduler_runs_panel.py
  services/core-control-plane/tests/delivery/rpc
  services/core-control-plane/tests/delivery/webhook
  services/core-control-plane/tests/delivery/operator_api/test_webhook_route.py
  services/core-control-plane/tests/delivery/azure/llm/test_latency_routed_cross_check.py
  services/core-control-plane/tests/persistence/test_postgres_schedule_run_ledger.py
  services/core-control-plane/tests/persistence/test_postgres_scheduler_store.py
  services/core-control-plane/tests/persistence/test_postgres_channel_pairing.py
  services/core-control-plane/tests/persistence/test_postgres_channel_identity_link.py
  services/core-control-plane/tests/persistence/test_postgres_skill_proposal.py
  services/core-control-plane/tests/persistence/test_postgres_model_health.py
  services/core-control-plane/tests/persistence/test_postgres_memory_compaction.py
  services/core-control-plane/tests/persistence/test_postgres_operator_memory.py
  services/core-control-plane/tests/persistence/test_postgres_trusted_artifact.py
  services/core-control-plane/tests/persistence/test_postgres_rpc_idempotency.py
  services/core-control-plane/tests/delivery/operator_api/test_operator_memory_panel.py
  services/core-control-plane/tests/delivery/operator_api/test_model_settings.py
  services/core-control-plane/tests/rule_catalog/schema/test_llm_registry.py
  services/core-control-plane/tests/rule_catalog/schema/test_llm_resolver.py
  services/core-control-plane/tests/rule_catalog/schema/test_model_endpoint.py
)

printf '== productization: lint ==\n'
uv run ruff check "${python_paths[@]}" "${test_paths[@]}"

printf '== productization: typing ==\n'
uv run mypy "${python_paths[@]}"

printf '== productization: focused tests ==\n'
uv run pytest "${test_paths[@]}" -q

printf '== productization: console ==\n'
npm --prefix console test -- --run \
  src/routes/scheduler-runs.model.test.ts \
  src/routes/processes.model.test.ts \
  src/routes/settings-models.test.ts \
  src/routes/operator-memory.model.test.ts \
  src/panels.test.ts
npm --prefix console run typecheck
npm --prefix console run build

printf '== productization: docs ==\n'
bash scripts/quality/localization/check-translations.sh
bash scripts/quality/repository/check-punctuation.sh
bash scripts/quality/repository/check-doc-links.sh
bash scripts/quality/localization/check-catalog-parity.sh
bash scripts/quality/repository/check-guids.sh

printf '== productization: migration head ==\n'
head_count="$(uv run alembic heads | wc -l | tr -d ' ')"
if [[ "$head_count" != "1" ]]; then
  printf 'expected one Alembic head, found %s\n' "$head_count" >&2
  exit 1
fi
uv run alembic heads

printf '== productization: wheel + isolated CLI smoke ==\n'
uv build --wheel --out-dir "$tmp_dir/dist"
wheel="$(find "$tmp_dir/dist" -maxdepth 1 -type f -name 'fdai-*.whl' -print -quit)"
if [[ -z "$wheel" ]]; then
  printf 'wheel build produced no fdai wheel\n' >&2
  exit 1
fi
uvx --from "$wheel" fdaictl version --output json
uvx --from "$wheel" fdai-model-endpoint-discovery --help >/dev/null
uvx --from "$wheel" fdaictl provision inspect --help >/dev/null
uvx --from "$wheel" fdaictl onboard guided --help >/dev/null
uvx --from "$wheel" fdaictl deploy plan --help >/dev/null
uvx --from "$wheel" fdaictl deploy status --help >/dev/null
uvx --from "$wheel" fdaictl deploy apply --help >/dev/null
uvx --from "$wheel" fdaictl backup create --help >/dev/null
uvx --from "$wheel" fdaictl backup restore --help >/dev/null
uvx --from "$wheel" fdaictl provision init --help >/dev/null
uvx --from "$wheel" fdaictl release upgrade --help >/dev/null
uvx --from "$wheel" fdaictl release rollback --help >/dev/null

printf 'verify-productization: OK\n'
