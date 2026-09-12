"""Protected deployment contract for the provider-schema Job."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = _ROOT / ".github/workflows/deploy-dev.yml"
_DEPLOYMENT_VERIFIER = _ROOT / "scripts/deployment/azure/verify-provider-schema-deployment.sh"


def test_provider_schema_plan_uses_dedicated_bounded_target() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    dispatch_inputs = workflow.split("workflow_dispatch:\n    inputs:\n", maxsplit=1)[1].split(
        "\npermissions:", maxsplit=1
    )[0]
    assert "deploy_provider_schema:" not in dispatch_inputs
    assert "Bind model-binding Terraform target" in workflow
    assert (
        "TF_CLI_ARGS_plan=-target=azurerm_container_app_job.provider_schema[0]"
        in workflow
    )
    assert "startsWith(inputs.request_id, 'plan-provider-')" in workflow
    assert "startsWith(inputs.request_id, 'apply-provider-')" in workflow
    assert "mode=provider-schema" in workflow
    resolver = workflow.split("- name: Resolve and seal model capabilities", maxsplit=1)[1].split(
        "      - name:", maxsplit=1
    )[0]
    assert "env.PROVIDER_SCHEMA_ONLY != 'true'" in resolver
    assert '[[ "$resolved_models_digest" == "-" ]] || PYTHONPATH=' in workflow


def test_provider_schema_apply_skips_unrelated_runtime_mutations() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    for step_name in (
        "Run schema migrations",
        "Publish integrated migration adoption evidence",
        "Verify deployed health endpoints",
        "Run canary publisher smoke",
    ):
        block = workflow.split(f"- name: {step_name}", maxsplit=1)[1].split(
            "      - name:", maxsplit=1
        )[0]
        assert "env.PROVIDER_SCHEMA_ONLY != 'true'" in block


def test_provider_schema_apply_retains_execution_and_agent_evidence() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    verifier = _DEPLOYMENT_VERIFIER.read_text(encoding="utf-8")
    convergence = workflow.split("- name: Verify Terraform convergence", maxsplit=1)[1].split(
        "      - name:", maxsplit=1
    )[0]
    receipt = workflow.split("- name: Record exact plan apply receipt", maxsplit=1)[1].split(
        "      - name:", maxsplit=1
    )[0]
    resume_claim = workflow.split("- name: Verify existing exact apply claim", maxsplit=1)[1].split(
        "      - name:", maxsplit=1
    )[0]

    assert "inputs.apply && inputs.resume_verification" in resume_claim
    assert "if: ${{ inputs.apply }}" in convergence
    assert "verify-provider-schema-deployment.sh" in convergence
    assert "provider-schema-deployment-evidence.json" in convergence
    assert "az storage blob exists" in verifier
    assert "az storage blob download" in verifier
    assert ".application_source_commit == $source" in verifier
    assert ".runtime_image_revision == $image" in verifier
    assert ".plan_id == $plan" in verifier
    assert "--overwrite false" in verifier
    assert "provider-schema-deployment-evidence.json" in receipt


def test_provider_schema_plan_and_apply_require_exact_healthy_core_baseline() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("verify-provider-schema-core-baseline.sh") == 3
    assert '"$FDAI_RUNTIME_IMAGE_REVISION" "$FDAI_RUNTIME_IMAGE_DIGEST"' in workflow
    assert '"$runtime_revision" "$runtime_digest"' in workflow
    assert "--verify-receipt provider-schema-core-baseline-plan.json" in workflow
    assert '"${blob_prefix}/provider-schema-core-baseline.json"' in workflow
    assert "--overwrite false" in workflow
    assert "provider-schema-core-baseline-plan.json" in workflow
    assert "provider-schema-core-baseline.json" in workflow
