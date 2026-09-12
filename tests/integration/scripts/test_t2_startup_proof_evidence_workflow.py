"""Static safety checks for the protected T2 startup-proof evidence workflow."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "t2-startup-proof-evidence.yml"


def test_workflow_is_read_only_and_revision_bound() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "runs-on: [self-hosted, fdai-deploy, fdai-deploy-candidate]" in workflow
    assert "environment: plan-only" in workflow
    assert "workflow-path: .github/workflows/t2-startup-proof-evidence.yml" in workflow
    assert "PYTHONPATH: ${{ github.workspace }}" in workflow
    assert "Verify required CI for exact revision" in workflow
    assert '[[ "$deployed_source_revision" == "$TARGET_COMMIT_SHA" ]]' in workflow
    assert "T2 startup evidence requires exactly one active Core revision" in workflow
    assert "T2 startup evidence requires exactly one running Core replica" in workflow
    assert "terraform apply" not in workflow
    assert "containerapp update" not in workflow
    assert "containerapp revision restart" not in workflow


def test_workflow_keeps_live_values_out_of_the_artifact() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "::add-mask::$runtime_dsn" in workflow
    assert 'chmod 0600 "$RUNNER_TEMP/t2-startup-proof-dsn"' in workflow
    assert "--source-identity-digest" in workflow
    assert "--revision-ref-digest" in workflow
    assert "--replica-ref-digest" in workflow
    assert "t2-startup-proof-live-evidence.json" in workflow
    assert "Remove live context files" in workflow
    assert '[[ "$AZURE_CONFIG_DIR" == "$RUNNER_TEMP/"* ]]' in workflow
    assert 'rm -rf -- "$AZURE_CONFIG_DIR"' in workflow
