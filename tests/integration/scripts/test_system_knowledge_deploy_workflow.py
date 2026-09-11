from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/system-knowledge-deploy.yml"


def test_workflow_is_plan_first_and_exact_revision_bound() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    inputs = workflow[True]["workflow_dispatch"]["inputs"]

    assert inputs["apply"]["default"] is False
    assert inputs["transition"]["options"] == ["bootstrap", "enable", "disable"]
    assert workflow["jobs"]["deploy"]["runs-on"] == [
        "self-hosted",
        "fdai-deploy",
        "fdai-deploy-candidate",
    ]
    assert "inputs.commit_sha == github.sha" in workflow["jobs"]["deploy"]["if"]
    assert "check-runs?per_page=100" in text
    assert "gh attestation verify" in text
    assert workflow["permissions"]["id-token"] == "write"


def test_workflow_seals_and_replays_the_exact_plan() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "system-knowledge-plan-metadata.json" in text
    assert "sha256sum" in text
    assert 'cmp "$bundle/system-knowledge-context.json"' in text
    assert text.count("scripts/deployment/system_knowledge/guard_plan.py") == 2
    assert "terraform -chdir=infra/services/system-knowledge-service apply" in text


def test_workflow_materializes_transport_secrets_only_for_active_apply() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["deploy"]["steps"]
    secret_step = next(
        step for step in steps if step["name"] == "Materialize Teams secrets in private Key Vault"
    )

    assert secret_step["if"] == "${{ inputs.apply && inputs.transition != 'disable' }}"
    assert "--include-outgoing-hmac" in secret_step["run"]
    assert "SYSTEM_KNOWLEDGE_PRINCIPAL_MAP_JSON" in workflow["jobs"]["deploy"]["env"]
    assert "SYSTEM_KNOWLEDGE_TEAMS_OUTGOING_HMAC_SECRET" in workflow["jobs"]["deploy"]["env"]


def test_workflow_verifies_health_blob_and_disabled_rollback() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'properties.healthState == "Healthy"' in text
    assert "az storage container show" in text
    assert "fdai-system-knowledge-teams.zip" in text
    assert "disabled System Knowledge Service state is not empty" in text
    assert "SYSTEM_KNOWLEDGE_INSTALLER_CLIENT_ID" in text
    assert "install_teams_app.py" in text
    assert "steps.context.outputs.teams_transport == 'bot_framework'" in text
    assert text.count("--transport") == 2
