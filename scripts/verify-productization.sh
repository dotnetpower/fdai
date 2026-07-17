#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

python_paths=(
  src/fdai/deployment_cli
  src/fdai/composition/wire_llm.py
  src/fdai/core/capability_catalog
  src/fdai/core/conversation/channel_access.py
  src/fdai/core/conversation/channel_gateway.py
  src/fdai/core/conversation/coordinator.py
  src/fdai/core/conversation/identity_links.py
  src/fdai/core/conversation/narrator.py
  src/fdai/core/conversation/tool_discovery.py
  src/fdai/core/rpc
  src/fdai/core/sandbox
  src/fdai/core/supply_chain
  src/fdai/core/operator_memory
  src/fdai/core/scheduler
  src/fdai/core/skills
  src/fdai/delivery/channels
  src/fdai/delivery/azure/llm
  src/fdai/delivery/azure/preflight
  src/fdai/delivery/github/deployment_workflow.py
  src/fdai/delivery/trust
  src/fdai/delivery/ingestion_gateway/main.py
  src/fdai/delivery/knowledge
  scripts/cleanup-deployment-plans.py
  scripts/check-runner-egress.py
  scripts/build-deployment-bundle.py
  scripts/verify-deployment-plan.py
  src/fdai/shared/providers/conversation_channel.py
  src/fdai/shared/providers/document_converter.py
  src/fdai/shared/providers/local/document_ingestion.py
  src/fdai/shared/telemetry
  src/fdai/delivery/mcp
  src/fdai/delivery/read_api/routes/scheduler_runs.py
  src/fdai/delivery/rpc
  src/fdai/delivery/webhook
  src/fdai/delivery/persistence/postgres_schedule_run_ledger.py
  src/fdai/delivery/persistence/postgres_scheduler_store.py
  src/fdai/delivery/persistence/postgres_channel_pairing.py
  src/fdai/delivery/persistence/postgres_channel_identity_link.py
  src/fdai/delivery/persistence/postgres_skill_proposal.py
  src/fdai/delivery/persistence/postgres_model_health.py
  src/fdai/delivery/persistence/postgres_memory_compaction.py
  src/fdai/delivery/persistence/postgres_operator_memory.py
  src/fdai/delivery/persistence/postgres_trusted_artifact.py
  src/fdai/delivery/persistence/postgres_rpc_idempotency.py
  src/fdai/rule_catalog/schema/llm_registry.py
  src/fdai/rule_catalog/schema/llm_resolver.py
  src/fdai/rule_catalog/schema/model_endpoint.py
)

test_paths=(
  tests/deployment_cli
  tests/infra/test_apim_ai_gateway.py
  tests/test_composition_llm.py
  tests/core/capability_catalog
  tests/core/rpc
  tests/core/sandbox
  tests/core/supply_chain
  tests/core/operator_memory
  tests/core/scheduler
  tests/core/skills
  tests/conversation
  tests/delivery/channels
  tests/delivery/azure/llm
  tests/delivery/azure/preflight
  tests/delivery/github/test_deployment_workflow.py
  tests/delivery/trust
  tests/delivery/ingestion_gateway/test_main.py
  tests/delivery/knowledge/test_loader.py
  tests/scripts/test_cleanup_deployment_plans.py
  tests/scripts/test_check_runner_egress.py
  tests/scripts/test_build_deployment_bundle.py
  tests/scripts/test_release_deployment_bundle_workflow.py
  tests/scripts/test_verify_deployment_plan.py
  tests/core/document_ingestion/test_document_ingestion.py
  tests/shared/test_transition_telemetry.py
  tests/delivery/mcp
  tests/delivery/read_api/test_scheduler_runs_panel.py
  tests/delivery/rpc
  tests/delivery/webhook
  tests/delivery/read_api/test_webhook_route.py
  tests/delivery/azure/llm/test_latency_routed_cross_check.py
  tests/persistence/test_postgres_schedule_run_ledger.py
  tests/persistence/test_postgres_scheduler_store.py
  tests/persistence/test_postgres_channel_pairing.py
  tests/persistence/test_postgres_channel_identity_link.py
  tests/persistence/test_postgres_skill_proposal.py
  tests/persistence/test_postgres_model_health.py
  tests/persistence/test_postgres_memory_compaction.py
  tests/persistence/test_postgres_operator_memory.py
  tests/persistence/test_postgres_trusted_artifact.py
  tests/persistence/test_postgres_rpc_idempotency.py
  tests/delivery/read_api/test_operator_memory_panel.py
  tests/delivery/read_api/test_model_settings.py
  tests/rule_catalog/schema/test_llm_registry.py
  tests/rule_catalog/schema/test_llm_resolver.py
  tests/rule_catalog/schema/test_model_endpoint.py
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
bash scripts/check-translations.sh
bash scripts/check-punctuation.sh
bash scripts/check-doc-links.sh
bash scripts/check-catalog-parity.sh
bash scripts/check-guids.sh

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
uvx --from "$wheel" fdaictl onboard guided --help >/dev/null
uvx --from "$wheel" fdaictl deploy plan --help >/dev/null
uvx --from "$wheel" fdaictl deploy status --help >/dev/null
uvx --from "$wheel" fdaictl deploy apply --help >/dev/null
uvx --from "$wheel" fdaictl backup create --help >/dev/null
uvx --from "$wheel" fdaictl backup restore --help >/dev/null
uvx --from "$wheel" fdaictl release upgrade --help >/dev/null
uvx --from "$wheel" fdaictl release rollback --help >/dev/null

printf 'verify-productization: OK\n'
