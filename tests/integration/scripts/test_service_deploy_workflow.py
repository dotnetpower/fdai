"""Static contracts for the protected independent-service workflow."""

from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = (_ROOT / ".github" / "workflows" / "service-deploy.yml").read_text(encoding="utf-8")
_HEALTH_SCRIPT = (_ROOT / "scripts" / "deployment" / "service" / "verify_health.sh").read_text(
    encoding="utf-8"
)
_LEGACY_WORKFLOW = (_ROOT / ".github" / "workflows" / "deploy-dev.yml").read_text(encoding="utf-8")
_MATRIX = json.loads(
    (_ROOT / "scripts" / "deployment" / "service" / "service-matrix.json").read_text(
        encoding="utf-8"
    )
)
_MIGRATION = json.loads(
    (_ROOT / "infra" / "services" / "state-migration.json").read_text(encoding="utf-8")
)
_ACTION_PINS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "actions/download-artifact": "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
}
_GH_CLI_VERSION = "2.94.0"
_GH_CLI_ARCHIVE_SHA256 = "a757f1ba6db18f4de8cbadb244843a5f89bc75b5e7c6fc127d2bd77fbd12ed62"


def test_workflow_has_closed_five_service_input_and_runner() -> None:
    services = set(_MATRIX["services"])
    assert len(services) == 5
    assert services == set(_MIGRATION["services"])
    for service in services:
        assert f"          - {service}\n" in _WORKFLOW
    assert "runs-on: [self-hosted, fdai-deploy]" in _WORKFLOW
    assert "group: service-deploy-${{ inputs.service }}-${{ inputs.environment }}" in _WORKFLOW


def test_workflow_pins_every_action_to_trusted_immutable_commit() -> None:
    uses = re.findall(r"^\s*uses:\s+([^\s#]+)", _WORKFLOW, re.MULTILINE)

    assert uses
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", value) for value in uses)
    for action, sha in _ACTION_PINS.items():
        assert f"{action}@{sha}" in uses


def test_workflow_defaults_to_plan_and_requires_exact_apply_coordinates() -> None:
    assert "default: false" in _WORKFLOW
    assert "if: ${{ !inputs.apply && !inputs.migrate_state }}" in _WORKFLOW
    assert "if: ${{ inputs.apply }}" in _WORKFLOW
    assert "apply and migrate_state are mutually exclusive." in _WORKFLOW
    assert "service-state-migration-{0}" in _WORKFLOW
    assert "service-initial-cutover-{0}" in _WORKFLOW
    assert "inputs.apply && format('service-apply-{0}'" in _WORKFLOW
    for coordinate in ("PLAN_RUN_ID", "PLAN_RUN_ATTEMPT", "PLAN_DIGEST", "CONTEXT_DIGEST"):
        assert f'[[ "${coordinate}" =~' in _WORKFLOW
    assert '[[ "$(git -C "$TARGET_ROOT" rev-parse HEAD)" == "$COMMIT_SHA" ]]' in _WORKFLOW
    assert "migrate_state and initial_cutover are mutually exclusive." in _WORKFLOW


def test_workflow_uses_protected_controls_and_protected_commit_ancestry() -> None:
    assert "path: trusted-controls" in _WORKFLOW
    assert "ref: main" in _WORKFLOW
    assert "fetch-depth: 1" in _WORKFLOW
    assert "path: target" in _WORKFLOW
    assert '"+refs/heads/main:refs/remotes/origin/main"' in _WORKFLOW
    assert 'git -C "$TRUSTED_CONTROLS" merge-base --is-ancestor' in _WORKFLOW
    assert '"$COMMIT_SHA" refs/remotes/origin/main' in _WORKFLOW
    assert 'TRUSTED_CONTROLS="$GITHUB_WORKSPACE/trusted-controls"' in _WORKFLOW
    for script in ("service_contract.py", "guard_plan.py", "plan_bundle.py"):
        assert f'"$TRUSTED_CONTROLS/scripts/deployment/service/{script}"' in _WORKFLOW


def test_workflow_binds_image_attestation_to_source_and_signer() -> None:
    assert f'GH_CLI_VERSION: "{_GH_CLI_VERSION}"' in _WORKFLOW
    assert f'GH_CLI_ARCHIVE_SHA256: "{_GH_CLI_ARCHIVE_SHA256}"' in _WORKFLOW
    assert "sha256sum --check --strict" in _WORKFLOW
    assert 'echo "$install_root/bin" >> "$GITHUB_PATH"' in _WORKFLOW
    assert _WORKFLOW.count('--source-digest "$COMMIT_SHA"') == 3
    assert _WORKFLOW.count('--signer-workflow "$ATTESTATION_SIGNER_WORKFLOW"') == 3
    assert '--predicate-type "https://slsa.dev/provenance/v1"' in _WORKFLOW
    assert '--predicate-type "https://spdx.dev/Document/v2.3"' in _WORKFLOW
    assert "container-supply-chain.yml" in _WORKFLOW
    assert "attestations/resolved-models/v1" in _WORKFLOW
    assert "Core image must have one canonical resolved-models digest." in _WORKFLOW
    assert _WORKFLOW.count('--resolved-models-digest "$RESOLVED_MODELS_DIGEST"') == 2


def test_workflow_validates_exact_source_run_before_artifact_download() -> None:
    assert 'gh api "repos/$GITHUB_REPOSITORY/actions/runs/$PLAN_RUN_ID"' in _WORKFLOW
    for field in (".id", ".run_attempt", ".conclusion", ".event", ".head_sha", ".path"):
        assert field in _WORKFLOW
    assert '"success"' in _WORKFLOW
    assert '"workflow_dispatch"' in _WORKFLOW
    assert '".github/workflows/service-deploy.yml"' in _WORKFLOW
    assert "-${{ inputs.plan_run_attempt }}" in _WORKFLOW
    assert "merge-base --is-ancestor" in _WORKFLOW
    assert '"$source_head_sha" "$CONTROLS_COMMIT_SHA"' in _WORKFLOW
    assert ".github/workflows/service-deploy.yml" in _WORKFLOW
    assert "scripts/deployment/service" in _WORKFLOW
    assert 'echo "PLAN_CONTROLS_COMMIT_SHA=$source_head_sha"' in _WORKFLOW
    assert _WORKFLOW.count('--controls-commit-sha "$CONTROLS_COMMIT_SHA"') == 1
    assert _WORKFLOW.count('--controls-commit-sha "$PLAN_CONTROLS_COMMIT_SHA"') == 1
    assert _WORKFLOW.index('--controls-commit-sha "$CONTROLS_COMMIT_SHA"') < _WORKFLOW.index(
        '--controls-commit-sha "$PLAN_CONTROLS_COMMIT_SHA"'
    )


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
    assert _WORKFLOW.count("gh attestation verify") == 3
    assert "manifests/sha-${COMMIT_SHA}" in _WORKFLOW
    assert '[[ "$commit_digest" == "$IMAGE_DIGEST" ]]' in _WORKFLOW
    assert "scripts/deployment/service/service_contract.py" in _WORKFLOW
    assert _WORKFLOW.count("scripts/deployment/service/guard_plan.py") == 2
    assert 'scripts/deployment/service/plan_bundle.py" create' in _WORKFLOW
    assert 'scripts/deployment/service/plan_bundle.py" verify' in _WORKFLOW
    assert 'cmp "$bundle/service-plan.json" "$RUNNER_TEMP/replayed-service-plan.json"' in _WORKFLOW
    assert '"$RUNNER_TEMP/service-plan-bundle/service.plan"' in _WORKFLOW
    assert _WORKFLOW.count("INITIAL_CUTOVER: ${{ inputs.initial_cutover }}") == 4
    assert _WORKFLOW.count("cutover_args+=(--initial-cutover)") == 3
    assert _WORKFLOW.count('"${cutover_args[@]}"') == 4
    for argument in (
        "--workflow-run-attempt",
        "--tenant-id",
        "--subscription-id",
        "--backend-resource-group",
        "--backend-storage-account",
        "--backend-container",
        "--controls-commit-sha",
        "--attestation-signer-workflow",
    ):
        assert _WORKFLOW.count(argument) == 2


def test_apply_has_post_apply_health_and_no_destroy_command() -> None:
    assert "Verify post-apply service health" in _WORKFLOW
    assert "scripts/deployment/service/verify_health.sh" in _WORKFLOW
    assert "Capture pre-apply rollback snapshot" in _WORKFLOW
    assert "Roll back unhealthy service revision" in _WORKFLOW
    assert "verify-rollback" in _WORKFLOW
    assert "Fail deployment after automatic rollback" in _WORKFLOW
    assert "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER=0" not in _WORKFLOW
    assert '"$rollback_dir/snapshot.json"' in _WORKFLOW
    assert ".planned_values.outputs.rollback_contract.value" in _WORKFLOW
    assert "output -json rollback_contract" not in _WORKFLOW
    assert "authority was unchanged" in _WORKFLOW
    assert "protected platform rollback is required" in _WORKFLOW
    assert "terraform destroy" not in _WORKFLOW
    assert "-destroy" not in _WORKFLOW
    assert "az containerapp secret set" in _WORKFLOW
    assert "previous_secrets[]" in _WORKFLOW
    assert "sleep 5" in _WORKFLOW
    assert ".properties.latestRevisionName" in _HEALTH_SCRIPT
    assert ".latest_revision_name" not in _HEALTH_SCRIPT
    assert "for _attempt in $(seq 1 36)" in _HEALTH_SCRIPT


def test_apply_failure_uses_the_same_verified_rollback_path() -> None:
    rollback_condition = (
        "if: ${{ inputs.apply && (steps.apply.outcome == 'failure' || "
        "steps.health.outcome == 'failure') }}"
    )
    final_failure_condition = (
        "if: ${{ always() && inputs.apply && (steps.apply.outcome == 'failure' || "
        "steps.health.outcome == 'failure') }}"
    )
    assert "id: apply\n        continue-on-error: true" in _WORKFLOW
    assert "if: ${{ inputs.apply && steps.apply.outcome == 'success' }}" in _WORKFLOW
    assert _WORKFLOW.count(rollback_condition) == 1
    assert "id: rollback\n        continue-on-error: true" in _WORKFLOW
    assert _WORKFLOW.count(final_failure_condition) == 1
    assert '[[ "${{ steps.rollback.outcome }}" != "success" ]]' in _WORKFLOW


def test_service_and_legacy_workflows_enforce_state_cutover_fence() -> None:
    assert "Verify service state cutover ownership" in _WORKFLOW
    assert 'state_migration.py" verify' in _WORKFLOW
    assert "--phase post" in _WORKFLOW
    assert "Guard migrated runtimes from legacy recreation" in _LEGACY_WORKFLOW
    assert "scripts/deployment/service/state_migration.py guard-legacy-plan" in _LEGACY_WORKFLOW


def test_state_migration_uses_remote_legacy_backend_and_verified_restore_helper() -> None:
    assert 'backend "azurerm" {}' in _WORKFLOW
    assert '-backend-config="key=fdai-${ENVIRONMENT}.tfstate"' in _WORKFLOW
    assert "Migrate service state ownership" in _WORKFLOW
    assert 'migrate_state.sh"' in _WORKFLOW
    assert '"$backup_dir" \\' in _WORKFLOW
    assert "            --execute" in _WORKFLOW
    assert "Verify migrated service state ownership" in _WORKFLOW
    assert 'terraform -chdir="$TARGET_ROOT/infra" state pull' in _WORKFLOW
    assert 'terraform -chdir="$TERRAFORM_ROOT" state pull' in _WORKFLOW
    assert "terraform show -json" not in _WORKFLOW
