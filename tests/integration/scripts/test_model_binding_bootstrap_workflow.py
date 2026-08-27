"""Fail-closed active-runtime contract for the protected model-binding fence."""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = _ROOT / ".github/workflows/deploy-dev.yml"
_STEP_NAME = "Verify model binding policy active digest"


def _step_script() -> str:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    step = next(
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == _STEP_NAME
    )
    script = step.get("run")
    assert isinstance(script, str)
    return script


def test_model_cas_requires_bound_active_core_revision() -> None:
    script = _step_script()

    assert "verify_active_core_revision.py" in script
    assert "--require-model-binding" in script
    assert "verify_active_model_attestation.py" in script
    assert "runtime_digest" in script
    assert "ACTIVE_CORE_REVISION=" in script
    assert "ACTIVE_CORE_IMAGE_DIGEST=" in script
    assert "ACTIVE_CORE_MODEL_DIGEST=" in script
    assert "bootstrap requires" not in script
    assert "terraform state show" not in script


def test_model_cas_keeps_terraform_output_diagnostic_only() -> None:
    script = _step_script()

    assert 'state_digest="$(terraform output -raw resolved_models_sha256' in script
    assert "Terraform model digest differs from active Core runtime evidence" in script
    assert 'if [[ "sha256:${current}" != "$expected" ]]' in script


def test_model_apply_reverifies_the_sealed_active_revision() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    assert "Reverify active Core model fence" in workflow
    assert "active Core revision changed after protected model planning" in workflow
    assert workflow.index("Reverify active Core model fence") < workflow.index(
        "Claim exact plan apply"
    )


def test_partner_endpoint_bindings_are_sealed_before_manifest_digest() -> None:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    step = next(
        step
        for step in workflow["jobs"]["terraform"]["steps"]
        if step.get("name") == "Resolve and seal model capabilities"
    )
    script = step["run"]

    assert "seal_model_endpoint_bindings.py" in script
    assert script.index("seal_model_endpoint_bindings.py") < script.index(
        'python3 - "$resolved" "$manifest"'
    )
    assert "git show -s --format=%cI" in script


def test_chatops_validation_requires_exact_resolved_foundry_secondary() -> None:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    step = next(
        step
        for step in workflow["jobs"]["terraform"]["steps"]
        if step.get("name") == "Resolve and seal model capabilities"
    )
    script = step["run"]

    assert inputs["validate_chatops_channels"]["default"] is False
    assert "inputs.validate_chatops_channels || inputs.deploy_dev_operations_gateway" in str(
        step["env"]["MODEL_COMPLETENESS_FAIL_ON"]
    )
    assert "require_resolved_capability.py" in script
    assert script.index("seal_model_endpoint_bindings.py") < script.index(
        "require_resolved_capability.py"
    )
    assert script.index("require_resolved_capability.py") < script.index(
        'python3 - "$resolved" "$manifest"'
    )
    assert "--capability t2.reasoner.secondary" in script
    assert "--publisher MistralAI" in script
    assert "--family Mistral-Large-3" in script
    assert "--version 1" in script
    assert "--sku GlobalStandard" in script
    assert "--minimum-capacity-tpm 1000" in script
    assert "--provider-kind azure-foundry" in script
    assert '--endpoint-ref "azure-foundry:aif-fdai-models-' in script

    workflow_text = _WORKFLOW.read_text(encoding="utf-8")
    assert '"chatops_channel_validation": (' in workflow_text
    assert "ChatOps validation input does not match the protected plan." in workflow_text
    assert workflow_text.count("require_resolved_capability.py") == 2
    assert workflow_text.index("verify-deployment-plan.py") < workflow_text.rindex(
        "require_resolved_capability.py"
    )
