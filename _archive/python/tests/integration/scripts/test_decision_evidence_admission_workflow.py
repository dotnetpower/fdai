"""Protected governed decision-evidence workflow contract tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = (_ROOT / ".github/workflows/decision-evidence-admission.yml").read_text(
    encoding="utf-8"
)
_DEPLOY = (_ROOT / ".github/workflows/deploy-dev.yml").read_text(encoding="utf-8")


def test_workflow_is_exact_revision_and_source_run_bound() -> None:
    assert "workflow-path: .github/workflows/decision-evidence-admission.yml" in _WORKFLOW
    assert 'git merge-base --is-ancestor "$TARGET_COMMIT_SHA" origin/main' in _WORKFLOW
    assert (
        'git rev-list --first-parent origin/main | grep -Fx "$TARGET_COMMIT_SHA" >/dev/null'
        in _WORKFLOW
    )
    assert '"$(git rev-parse HEAD)" == "$TARGET_COMMIT_SHA"' in _WORKFLOW
    assert "actions/runs/$SOURCE_RUN_ID/attempts/$SOURCE_RUN_ATTEMPT" in _WORKFLOW
    assert (
        _WORKFLOW.count("actions/runs/$SOURCE_RUN_ID\" \\\n              --jq '.run_attempt'") == 2
    )
    assert "source workflow attempt changed before artifact download" in _WORKFLOW
    assert "source workflow attempt changed during artifact download" in _WORKFLOW
    assert '--attempt "$SOURCE_RUN_ATTEMPT"' not in _WORKFLOW
    assert '[[ "$PLAN_ID" =~ ^plan-[1-9][0-9]*-[1-9][0-9]*$ ]]' in _WORKFLOW
    assert "deployment-apply-receipt-${PLAN_ID}" in _WORKFLOW
    assert "--policy config/decision-evidence-deployment-policy.json" in _WORKFLOW


def test_workflow_uses_managed_identity_and_immutable_blob_writes() -> None:
    assert "az login --identity --client-id" in _WORKFLOW
    assert (
        'verify-azure-context.sh" \\\n            "$ARM_SUBSCRIPTION_ID" "$AZURE_TENANT_ID"'
        in _WORKFLOW
    )
    installer = _WORKFLOW.index("Install pinned GitHub CLI")
    download = _WORKFLOW.index("Download exact source candidate")
    assert "install-pinned-github-cli.sh" in _WORKFLOW[installer:download]
    assert installer < download
    assert "--overwrite false" in _WORKFLOW
    assert "decision evidence immutable record collision" in _WORKFLOW
    assert "decision evidence immutable metadata collision" in _WORKFLOW
    assert "--query 'metadata.fdaisha256' -o tsv" in _WORKFLOW
    assert '"$stored_digest" == "$downloaded_digest"' in _WORKFLOW
    assert '"$stored_digest" == "$digest"' not in _WORKFLOW
    assert '--metadata "fdaisha256=$digest"' in _WORKFLOW
    assert '"decision-evidence/v1/admissions/${lookup_digest}.json" stable-lookup' in (_WORKFLOW)
    assert "datetime.now(UTC) <= valid_until" in _WORKFLOW


def test_retention_shell_block_is_valid_bash() -> None:
    workflow = yaml.safe_load(_WORKFLOW)
    steps = workflow["jobs"]["verify-retain-attest"]["steps"]
    step = next(
        item
        for item in steps
        if item.get("name") == "Retain attested immutable decision evidence records"
    )

    result = subprocess.run(
        ["/bin/bash", "-n"],
        input=step["run"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_download_shell_block_is_valid_bash() -> None:
    workflow = yaml.safe_load(_WORKFLOW)
    steps = workflow["jobs"]["verify-retain-attest"]["steps"]
    step = next(item for item in steps if item.get("name") == "Download exact source candidate")

    result = subprocess.run(
        ["/bin/bash", "-n"],
        input=step["run"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_first_parent_check_consumes_the_complete_stream() -> None:
    command = (
        'set -euo pipefail; target="$(git rev-parse HEAD)"; '
        'git rev-list --first-parent HEAD | grep -Fx "$target" >/dev/null'
    )

    result = subprocess.run(  # noqa: S603 - fixed shell validates workflow semantics
        ["/bin/bash", "-c", command],
        cwd=_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "secrets." not in _WORKFLOW


def test_workflow_retains_all_proof_layers_and_attests_record() -> None:
    for path in (
        "decision-evidence/v1/authentication/",
        "decision-evidence/v1/readback/",
        "decision-evidence/v1/requirements/",
        "decision-evidence/v1/bundles/",
        "decision-evidence/v1/admissions/",
    ):
        assert path in _WORKFLOW
    assert "actions/attest@" in _WORKFLOW
    assert (
        "subject-path: ${{ runner.temp }}/decision-evidence-inputs/admission-record.json"
        in _WORKFLOW
    )
    assert _WORKFLOW.index("Attest governed decision evidence") < _WORKFLOW.index(
        "Retain attested immutable decision evidence records"
    )
    assert "retention-days: 90" in _WORKFLOW
    assert "Execution authority: `false`" in _WORKFLOW
    assert "Promotion authority: `false`" in _WORKFLOW


def test_deploy_workflow_emits_fixed_candidate_artifact() -> None:
    assert 'candidate="$RUNNER_TEMP/deployment-apply-artifact"' in _DEPLOY
    assert "name: deployment-apply-receipt-${{ inputs.plan_id }}" in _DEPLOY
    assert "terraform output -raw decision_evidence_container_url" in _DEPLOY
    assert "retention-days: 90" in _DEPLOY
    for target in (
        "-target=module.decision_evidence_storage[0]",
        "-target=azurerm_private_endpoint.decision_evidence_blob[0]",
        "-target=azurerm_role_assignment.decision_evidence_inventory_reader[0]",
    ):
        assert target in _DEPLOY
    for name in (
        "plan-metadata.json",
        "preflight-evidence.json",
        "azure-preflight-evidence.json",
        "apply-claim.json",
        "apply-receipt.json",
    ):
        assert name in _DEPLOY
