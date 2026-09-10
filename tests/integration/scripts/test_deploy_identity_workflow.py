"""Contract tests for bounded stable deploy-identity migration."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = (_ROOT / ".github" / "workflows" / "deploy-dev.yml").read_text(encoding="utf-8")
_CONVERGENCE = (
    _ROOT / "scripts" / "deployment" / "azure" / "verify_deploy_convergence.sh"
).read_text(encoding="utf-8")


def test_workflow_binds_and_guards_only_the_identity_migration_plan() -> None:
    assert "DEPLOY_IDENTITY_MIGRATION_ONLY:" in _WORKFLOW
    assert "plan-identity-" in _WORKFLOW
    assert "apply-identity-" in _WORKFLOW
    assert "guard_deploy_identity_plan.py targets" in _WORKFLOW
    assert "guard_deploy_identity_plan.py \\\n              validate" in _WORKFLOW
    assert "env.DEPLOY_IDENTITY_MIGRATION_ONLY != 'true'" in _WORKFLOW
    assert "Preserve state-backed deploy identity features" in _WORKFLOW
    assert "state-env --state-list" in _WORKFLOW


def test_identity_apply_uses_targeted_convergence_without_runtime_checks() -> None:
    assert 'elif [[ "$request_id" == apply-identity-* ]]' in _CONVERGENCE
    assert 'if [[ "$deploy_identity_only" == "true" ]]' in _CONVERGENCE
    assert "Revalidate exact deploy identity plan" in _WORKFLOW
    assert "Verify stable deploy identity effect" in _WORKFLOW
    assert "verify_deploy_identity_effect.py" in _WORKFLOW
    assert "deploy_identity_effect_digest" in _WORKFLOW
    canary = _WORKFLOW.split("- name: Run canary publisher smoke", maxsplit=1)[1].split(
        "- name: Record exact plan apply receipt", maxsplit=1
    )[0]
    assert "DEPLOY_IDENTITY_MIGRATION_ONLY != 'true'" in canary
