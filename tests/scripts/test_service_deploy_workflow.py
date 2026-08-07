"""Static contracts for the protected independent-service workflow."""

from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = (_ROOT / ".github" / "workflows" / "service-deploy.yml").read_text(encoding="utf-8")
_MATRIX = json.loads(
    (_ROOT / "scripts" / "deployment" / "service" / "service-matrix.json").read_text(
        encoding="utf-8"
    )
)
_MIGRATION = json.loads(
    (_ROOT / "infra" / "services" / "state-migration.json").read_text(encoding="utf-8")
)


def test_workflow_has_closed_five_service_input_and_runner() -> None:
    services = set(_MATRIX["services"])
    assert len(services) == 5
    assert services == set(_MIGRATION["services"])
    for service in services:
        assert f"          - {service}\n" in _WORKFLOW
    assert "runs-on: [self-hosted, fdai-deploy]" in _WORKFLOW
    assert "group: service-deploy-${{ inputs.service }}-${{ inputs.environment }}" in _WORKFLOW


def test_workflow_defaults_to_plan_and_requires_exact_apply_coordinates() -> None:
    assert "default: false" in _WORKFLOW
    assert "if: ${{ !inputs.apply }}" in _WORKFLOW
    assert "if: ${{ inputs.apply }}" in _WORKFLOW
    assert "environment: ${{ inputs.apply && format('service-apply-{0}'" in _WORKFLOW
    for coordinate in ("PLAN_RUN_ID", "PLAN_DIGEST", "CONTEXT_DIGEST"):
        assert f'[[ "${coordinate}" =~' in _WORKFLOW
    assert '[[ "$(git rev-parse HEAD)" == "$COMMIT_SHA" ]]' in _WORKFLOW


def test_workflow_uses_per_service_backend_and_never_platform_root() -> None:
    assert "STATE_RESOURCE_GROUP: ${{ vars.STATE_RESOURCE_GROUP }}" in _WORKFLOW
    assert '-backend-config="resource_group_name=$STATE_RESOURCE_GROUP"' in _WORKFLOW
    assert '-backend-config="key=$BACKEND_KEY"' in _WORKFLOW
    assert "steps.contract.outputs.terraform_root" in _WORKFLOW
    assert 'terraform -chdir="infra"' not in _WORKFLOW
    assert "deploy-dev.yml" in _WORKFLOW
    for service, metadata in _MATRIX["services"].items():
        assert metadata["backend_key_template"] == f"services/{service}/{{environment}}.tfstate"
        assert metadata["terraform_root"] == f"infra/services/{service}"
        assert metadata["allowed_resource_address"] in {
            move["to"] for move in _MIGRATION["services"][service]["moves"]
        }


def test_plan_and_apply_both_verify_image_and_guard_exact_binary_plan() -> None:
    assert _WORKFLOW.count("gh attestation verify") == 1
    assert "manifests/sha-${COMMIT_SHA}" in _WORKFLOW
    assert '[[ "$commit_digest" == "$IMAGE_DIGEST" ]]' in _WORKFLOW
    assert "scripts/deployment/service/service_contract.py" in _WORKFLOW
    assert _WORKFLOW.count("scripts/deployment/service/guard_plan.py") == 2
    assert "scripts/deployment/service/plan_bundle.py create" in _WORKFLOW
    assert "scripts/deployment/service/plan_bundle.py verify" in _WORKFLOW
    assert 'cmp "$bundle/service-plan.json" "$RUNNER_TEMP/replayed-service-plan.json"' in _WORKFLOW
    assert '"$RUNNER_TEMP/service-plan-bundle/service.plan"' in _WORKFLOW


def test_apply_has_post_apply_health_and_no_destroy_command() -> None:
    assert "Verify post-apply service health" in _WORKFLOW
    assert "scripts/deployment/service/verify_health.sh" in _WORKFLOW
    assert "terraform destroy" not in _WORKFLOW
    assert "-destroy" not in _WORKFLOW
