from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = (_ROOT / ".github/workflows/cost-governance-lifecycle.yml").read_text(encoding="utf-8")
_ROUTES = (_ROOT / "scripts/lib/design-routes.json").read_text(encoding="utf-8")


def test_lifecycle_workflow_is_protected_and_exact_revision_bound() -> None:
    assert "verify-protected-workflow-source" in _WORKFLOW
    assert "ref: ${{ inputs.commit_sha }}" in _WORKFLOW
    assert "ref: ${{ inputs.release_source_revision }}" in _WORKFLOW
    assert 'select(.name == "required" and .conclusion == "success")' in _WORKFLOW
    assert '--source-digest "$RELEASE_SOURCE_REVISION"' in _WORKFLOW
    assert "image_digest=\"$(jq -er '.image_digest'" in _WORKFLOW
    assert "fdai-cost-governance@${image_digest}" in _WORKFLOW


def test_lifecycle_workflow_uses_private_state_and_canonical_cli() -> None:
    assert "FDAI_STATE_STORE_DSN" in _WORKFLOW
    assert "migration_dsn_secret_name" in _WORKFLOW
    assert "fdai_cost_governance.lifecycle_cli" in _WORKFLOW
    assert "operation == $operation" in _WORKFLOW
    assert 'evidence_kind == "live-authoritative"' in _WORKFLOW
    assert "terraform apply" not in _WORKFLOW


def test_enable_starts_collection_without_promoting_actions() -> None:
    collector = _WORKFLOW.split("- name: Start first bounded collector pass", 1)[1]

    assert "steps.transition.outputs.start_collector == 'true'" in collector
    assert ".replayed == false and .current_enabled == true" in _WORKFLOW
    assert "az containerapp job start" in collector
    assert "promote-action-type" not in _WORKFLOW
    assert "enforce" not in _WORKFLOW


def test_cost_governance_design_route_owns_lifecycle_workflow() -> None:
    route = _ROUTES.split('"id": "cost-governance-package"', 1)[1].split('"must_read"', 1)[0]

    assert '".github/workflows/cost-governance-lifecycle.yml"' in route
