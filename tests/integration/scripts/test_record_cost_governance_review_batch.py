"""Focused tests for bounded multi-target Cost Governance review envelopes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
from scripts.deployment.azure.record_cost_governance_review_batch import (
    BatchReviewError,
    load_review_batch,
    record_review_batch,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = REPO_ROOT / ".github/workflows/cost-governance-promotion-review.yml"


def _run_workflow_mode(script: str, environment: dict[str, str]) -> int:
    bash = shutil.which("bash")
    assert bash is not None
    # This executes a reviewed repository-owned workflow fragment with fixed test inputs.
    completed = subprocess.run(  # noqa: S603
        [bash, "-c", script],
        check=False,
        env=environment,
    )
    return completed.returncode


def _write_batch(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "target_kind": "package-activation",
                    "target_id": "cost-governance",
                    "decision": "recommend",
                    "rationale": "The exact campaign satisfies the package review criteria.",
                },
                {
                    "target_kind": "action-type",
                    "target_id": "remediate.right-size",
                    "decision": "hold",
                    "rationale": "The action requires more independent effect evidence.",
                },
            ]
        ),
        encoding="utf-8",
    )


def test_batch_decomposes_to_stable_authority_neutral_child_reviews(tmp_path: Path) -> None:
    batch = tmp_path / "batch.json"
    _write_batch(batch)
    commands: list[list[str]] = []

    def run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert check is False
        assert capture_output is True
        assert text is True
        commands.append(command)
        target_kind = command[command.index("--target-kind") + 1]
        target_id = command[command.index("--target-id") + 1]
        output = {
            "inserted": True,
            "review": {
                "target_kind": target_kind,
                "target_id": target_id,
                "approval_authority": False,
                "execution_authority": False,
                "promotion_authority": False,
            },
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(output), "")

    result = record_review_batch(
        readiness=tmp_path / "readiness.json",
        policy=tmp_path / "policy.json",
        batch_file=batch,
        request_id="cost-review-r1",
        evidence_refs=("workflow:123:1",),
        runner=run,
    )

    request_ids = [command[command.index("--request-id") + 1] for command in commands]
    assert request_ids == [
        "cost-review-r1:package-activation:cost-governance",
        "cost-review-r1:action-type:remediate.right-size",
    ]
    assert result["inserted"] is True
    assert len(result["reviews"]) == 2
    assert all(review["inserted"] is True for review in result["reviews"])


def test_batch_rejects_duplicate_target_identity(tmp_path: Path) -> None:
    batch = tmp_path / "batch.json"
    duplicate = {
        "target_kind": "workflow",
        "target_id": "cost-aware-remediation",
        "decision": "hold",
        "rationale": "More evidence is required.",
    }
    batch.write_text(json.dumps([duplicate, duplicate]), encoding="utf-8")

    with pytest.raises(BatchReviewError, match="identities MUST be unique"):
        load_review_batch(batch)


def test_batch_failure_does_not_expose_child_stderr(tmp_path: Path) -> None:
    batch = tmp_path / "batch.json"
    _write_batch(batch)

    def fail(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 3, "", "sensitive provider detail")

    with pytest.raises(BatchReviewError) as captured:
        record_review_batch(
            readiness=tmp_path / "readiness.json",
            policy=tmp_path / "policy.json",
            batch_file=batch,
            request_id="cost-review-r1",
            evidence_refs=("workflow:123:1",),
            runner=fail,
        )

    assert "sensitive provider detail" not in str(captured.value)


def test_protected_workflow_supports_batch_and_single_review_modes() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    assert "review_batch_json:" in workflow
    assert "record_cost_governance_review_batch.py" in workflow
    assert "record_cost_governance_review.py" in workflow
    assert 'printf \'%s\' "$REVIEW_BATCH_JSON" > "$batch_file"' in workflow
    assert '.schema_version == "fdai.cost-governance-review-batch.v1"' in workflow


def test_workflow_mode_preflight_executes_batch_single_and_mixed_cases() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    step = workflow.index("- name: Verify exact controls, reviewer, and required CI")
    start = workflow.index('if [[ -n "${REVIEW_BATCH_JSON:-}" ]]', step)
    line_start = workflow.rfind("\n", 0, start) + 1
    end = workflow.index("          fi", start) + len("          fi")
    script = "set -euo pipefail\n" + textwrap.dedent(workflow[line_start:end])
    base = {
        **os.environ,
        "REVIEW_BATCH_JSON": "",
        "REVIEW_TARGET_KIND": "",
        "REVIEW_TARGET_ID": "",
        "REVIEW_DECISION": "",
        "REVIEW_RATIONALE": "",
    }

    batch = _run_workflow_mode(
        script,
        {
            **base,
            "REVIEW_BATCH_JSON": '[{"target_kind":"workflow"}]',
        },
    )
    single = _run_workflow_mode(
        script,
        {
            **base,
            "REVIEW_TARGET_KIND": "workflow",
            "REVIEW_TARGET_ID": "cost-aware-remediation",
            "REVIEW_DECISION": "hold",
            "REVIEW_RATIONALE": "More evidence is required.",
        },
    )
    mixed = _run_workflow_mode(
        script,
        {
            **base,
            "REVIEW_BATCH_JSON": '[{"target_kind":"workflow"}]',
            "REVIEW_TARGET_KIND": "workflow",
        },
    )

    assert batch == 0
    assert single == 0
    assert mixed != 0
