"""Protected cohort observation import workflow contract tests."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = (ROOT / ".github/workflows/cohort-observation-import.yml").read_text(encoding="utf-8")


def test_workflow_is_exact_revision_and_protected() -> None:
    parsed = yaml.safe_load(WORKFLOW)

    assert "workflow_dispatch" in parsed[True]
    assert "runs-on: [self-hosted, fdai-deploy, fdai-deploy-candidate]" in WORKFLOW
    assert "workflow-path: .github/workflows/cohort-observation-import.yml" in WORKFLOW
    assert 'git merge-base --is-ancestor "$TARGET_COMMIT_SHA" origin/main' in WORKFLOW
    assert (
        'git rev-list --first-parent origin/main | grep -Fx "$TARGET_COMMIT_SHA" >/dev/null'
        in WORKFLOW
    )
    assert '"$(git rev-parse HEAD)" == "$TARGET_COMMIT_SHA"' in WORKFLOW
    assert '.name == "required" and .conclusion == "success"' in WORKFLOW
    assert "length >= 1" in WORKFLOW
    assert "length == 1" not in WORKFLOW


def test_source_run_is_stable_allowlisted_and_exact_revision() -> None:
    assert "actions/runs/$SOURCE_RUN_ID/attempts/$SOURCE_RUN_ATTEMPT" in WORKFLOW
    assert '.conclusion == "success" and .head_sha == $revision' in WORKFLOW
    assert "policy.allowed_exporters(arm)" in WORKFLOW
    assert "source workflow is not authorized" in WORKFLOW
    assert "source workflow attempt changed before artifact download" in WORKFLOW
    assert "source workflow attempt changed during artifact download" in WORKFLOW
    assert '--name "$SOURCE_ARTIFACT_NAME"' in WORKFLOW
    assert "exactly one cohort observation batch" in WORKFLOW


def test_workflow_uses_private_state_and_exports_aggregate_evidence_only() -> None:
    parsed = yaml.safe_load(WORKFLOW)
    job = parsed["jobs"]["import"]
    azure_step = next(
        step
        for step in job["steps"]
        if step.get("name") == "Authenticate and bind private platform state"
    )

    assert "ARM_SUBSCRIPTION_ID" not in job["env"]
    assert "AZURE_TENANT_ID" not in job["env"]
    assert "ARM_SUBSCRIPTION_ID" in azure_step["env"]
    assert "AZURE_TENANT_ID" in azure_step["env"]
    assert "login-deploy-identity.sh" in WORKFLOW
    assert "::add-mask::$migration_dsn" in WORKFLOW
    assert "FDAI_STATE_STORE_DSN" in WORKFLOW
    assert "cohort_observation_import_cli" in WORKFLOW
    assert "PostgresCohortEvidenceInventorySource" in WORKFLOW
    assert "claim_eligibility_authority == false" in WORKFLOW
    assert "execution_authority == false" in WORKFLOW
    assert "actions/attest@" in WORKFLOW
    assert "retention-days: 90" in WORKFLOW
    assert "secrets." not in WORKFLOW


def test_every_workflow_shell_block_is_valid_bash() -> None:
    parsed = yaml.safe_load(WORKFLOW)
    bash = shutil.which("bash")

    assert bash is not None
    for step in parsed["jobs"]["import"]["steps"]:
        script = step.get("run")
        if not isinstance(script, str):
            continue
        sanitized = re.sub(r"\$\{\{[^\n}]+\}\}", "placeholder", script)
        completed = subprocess.run(  # noqa: S603 - validates repository workflow syntax
            [bash, "-n"],
            input=sanitized,
            capture_output=True,
            check=False,
            text=True,
        )
        assert completed.returncode == 0, f"{step['name']}: {completed.stderr}"
