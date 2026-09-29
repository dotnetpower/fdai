#!/usr/bin/env bash
# Regenerate, or check, every repository artifact derived from contracts and catalogs.
#
# A contract, ActionType, or ontology change ripples into generated schemas, TypeScript and Python
# contract views, compatibility receipts, ontology release pins, the semantic assurance corpus,
# and the System Knowledge catalog. Run this once after such a change instead of discovering each
# stale artifact separately. Write mode never commits; review the diff like any other change.
#
# Usage: refresh-derived-artifacts.sh [--check]
set -euo pipefail

mode="write"
if [ "${1:-}" = "--check" ]; then
  mode="check"
elif [ "$#" -gt 0 ]; then
  echo "usage: refresh-derived-artifacts.sh [--check]" >&2
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
export PYTHONPATH="services/core-control-plane/src:packages/service-contracts/src${PYTHONPATH:+:$PYTHONPATH}"

check_flag=()
if [ "$mode" = "check" ]; then
  check_flag=(--check)
fi

run() {
  echo "derived-artifacts: $*"
  "$@"
}

# Schemas first: the service-contract views and compatibility receipts read them.
for generator in \
  generate_alert_noise_schemas.py \
  generate_adaptive_answer_schema.py \
  generate_cluster_connector_schemas.py \
  generate_conversation_model_schema.py \
  generate_document_context_schema.py \
  generate_authentication_receipt_ref_schema.py \
  generate_document_context_projection_schema.py \
  generate_test_context_schemas.py; do
  run uv run python "scripts/quality/contracts/$generator" "${check_flag[@]}"
done
run uv run python scripts/quality/contracts/generate_service_contracts.py "${check_flag[@]}"
run uv run python scripts/quality/contracts/generate_service_compatibility_fixtures.py "${check_flag[@]}"
run uv run python scripts/quality/architecture/generate-behavior-seeds.py "${check_flag[@]}"

if [ "$mode" = "check" ]; then
  run uv run python scripts/catalog/refresh-release-derived-pins.py
  run uv run python scripts/automation/build_semantic_assurance_corpus.py --check
  run uv run python scripts/quality/localization/check-derived-sources.py
else
  run uv run python scripts/catalog/refresh-release-derived-pins.py --write
  run uv run python scripts/automation/build_semantic_assurance_corpus.py
  # The catalog records its build time and revision, so rebuild it only when its pins are stale.
  if ! uv run python scripts/quality/localization/check-derived-sources.py >/dev/null 2>&1; then
    run uv run --package fdai-system-knowledge-service fdai-system-knowledge-build-catalog \
      --repo-root . \
      --protected-main-ref refs/remotes/origin/main \
      --output services/system-knowledge-service/src/fdai_system_knowledge_service/data/catalog.json
    run uv run python scripts/quality/localization/check-derived-sources.py
  fi
fi

echo "derived-artifacts: OK (mode=$mode)"
