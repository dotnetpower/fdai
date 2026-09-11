"""Contract tests for bounded stable deploy-identity migration."""

from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = (_ROOT / ".github" / "workflows" / "deploy-dev.yml").read_text(encoding="utf-8")
_CONVERGENCE = (
    _ROOT / "scripts" / "deployment" / "azure" / "verify_deploy_convergence.sh"
).read_text(encoding="utf-8")
_EFFECT_WRAPPER_PATH = (
    _ROOT / "scripts" / "deployment" / "azure" / "verify-deploy-identity-effect.sh"
)
_EFFECT_WRAPPER = _EFFECT_WRAPPER_PATH.read_text(encoding="utf-8")
_STATE_RECONCILER = (
    _ROOT / "scripts" / "deployment" / "azure" / "reconcile_deploy_identity_state.py"
).read_text(encoding="utf-8")
_APPLY_RECEIPT_BUILDER = (
    _ROOT / "scripts" / "deployment" / "azure" / "build_deployment_apply_receipt.py"
).read_text(encoding="utf-8")


def test_workflow_binds_and_guards_only_the_identity_migration_plan() -> None:
    assert "DEPLOY_IDENTITY_MIGRATION_ONLY:" in _WORKFLOW
    assert "plan-identity-" in _WORKFLOW
    assert "apply-identity-" in _WORKFLOW
    assert "guard_deploy_identity_plan.py target-env --terraform-dir ." in _WORKFLOW
    assert _WORKFLOW.count("guard_deploy_identity_plan.py target-env --terraform-dir .") == 2
    assert 'echo "TF_CLI_ARGS_plan=$(python3' not in _WORKFLOW
    apply_restore = _WORKFLOW.split("read -r resolved_models_digest", maxsplit=1)[1].split(
        "verify-deployment-plan.py", maxsplit=1
    )[0]
    assert apply_restore.index("export TF_VAR_resolved_capabilities") < apply_restore.index(
        "guard_deploy_identity_plan.py target-env"
    )
    assert "guard_deploy_identity_plan.py \\\n              validate" in _WORKFLOW
    assert "env.DEPLOY_IDENTITY_MIGRATION_ONLY != 'true'" in _WORKFLOW
    assert "state-env --terraform-dir ." in _WORKFLOW
    assert "reconcile_deploy_identity_state.py --terraform-dir ." in _WORKFLOW
    assert "mode=deploy-identity" in _WORKFLOW
    operational_adoption = _WORKFLOW.split(
        'if [[ "$TF_VAR_enable_operational_history" == "true"',
        maxsplit=1,
    )[1].split("fi", maxsplit=1)[0]
    assert 'DEPLOY_IDENTITY_MIGRATION_ONLY" != "true"' in operational_adoption
    assert "--assignee-object-id" in _STATE_RECONCILER


def test_identity_apply_uses_targeted_convergence_without_runtime_checks() -> None:
    assert 'elif [[ "$request_id" == apply-identity-* ]]' in _CONVERGENCE
    assert 'if [[ "$deploy_identity_only" == "true" ]]' in _CONVERGENCE
    assert "deploy-identity-applied-plan.json" in _WORKFLOW
    assert "- name: Verify stable deploy identity effect" not in _WORKFLOW
    assert "verify-deploy-identity-effect.sh" in _WORKFLOW
    assert "deploy_identity_effect_digest" in _APPLY_RECEIPT_BUILDER
    canary = _WORKFLOW.split("- name: Run canary publisher smoke", maxsplit=1)[1].split(
        "- name: Record exact plan apply receipt", maxsplit=1
    )[0]
    assert "DEPLOY_IDENTITY_MIGRATION_ONLY != 'true'" in canary
    for start, end in (
        ("Synchronize console Entra redirect URI", "Build allowlisted design-mocks artifact"),
        ("Run schema migrations", "Publish integrated migration adoption evidence"),
        ("Verify deployed health endpoints", "Verify independent Executor effect and rollback"),
        ("Publish and verify console", None),
    ):
        step = _WORKFLOW.split(f"- name: {start}", maxsplit=1)[1]
        if end is not None:
            step = step.split(f"- name: {end}", maxsplit=1)[0]
        assert "DEPLOY_IDENTITY_MIGRATION_ONLY != 'true'" in step


def test_identity_effect_wrapper_is_fail_closed_and_publishes_one_receipt() -> None:
    completed = subprocess.run(  # noqa: S603 - fixed Bash path and repository script.
        ["/usr/bin/bash", "-n", str(_EFFECT_WRAPPER_PATH)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "set -euo pipefail" in _EFFECT_WRAPPER
    assert "DEPLOY_IDENTITY_EFFECT_DIGEST=" in _EFFECT_WRAPPER
    assert "--overwrite false" in _EFFECT_WRAPPER
