from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = _ROOT / ".github/workflows/deploy-dev.yml"


def test_protected_workflow_exposes_request_bound_status_metadata() -> None:
    source = _WORKFLOW.read_text(encoding="utf-8")

    assert (
        "run-name: deploy-${{ inputs.request_id || "
        "format('{0}-{1}', inputs.environment, github.run_number) }}"
    ) in source
    assert "name: deployment-plan-metadata-${{ inputs.request_id }}" in source
    assert "path: infra/plan-metadata.json" in source
    assert "retention-days: 1" in source
    assert "Verify protected environment approval policy" in source
    assert "verify-github-environment.py" in source
    assert "GH_TOKEN: ${{ github.token }}" in source


def test_exact_apply_still_restores_the_private_binary_plan() -> None:
    source = _WORKFLOW.read_text(encoding="utf-8")

    assert "Restore and verify exact protected plan" in source
    assert '--name "${blob_prefix}/terraform.plan"' in source
    assert "terraform apply -input=false -lock-timeout=300s dev.plan" in source
    assert "apply-claim.json" in source
    assert "apply-receipt.json" in source
