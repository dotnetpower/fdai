"""Exact protected-deployment decision-evidence tests."""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
from fdai.delivery.decision_evidence_policy import (
    load_deployment_decision_evidence_policy,
)
from fdai_service_contracts.decision_evidence_verification import (
    EvidenceVerificationProofKind,
)

_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT = _ROOT / "scripts" / "deployment" / "azure" / "deployment_decision_evidence.py"
_NOW = datetime(2026, 9, 8, 12, 30, tzinfo=UTC)
_COMMIT = "a" * 40
_PLAN_ID = "plan-123-1"
_PLAN_DIGEST = "b" * 64
_CONTEXT_DIGEST = "c" * 64
_RUN_ID = 123
_RUN_ATTEMPT = 1
_POLICY_PATH = _ROOT / "config/decision-evidence-deployment-policy.json"


def _policy():
    return load_deployment_decision_evidence_policy(_POLICY_PATH)


@pytest.fixture(scope="module")
def verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location("deployment_decision_evidence_script", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _evidence_dir(tmp_path: Path, *, status: str = "applied") -> Path:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    _write(
        evidence / "plan-metadata.json",
        {
            "schema_version": "fdai.deployment-plan.v1",
            "plan_id": _PLAN_ID,
            "plan_digest": _PLAN_DIGEST,
            "context_digest": _CONTEXT_DIGEST,
            "commit_sha": _COMMIT,
        },
    )
    _write(evidence / "preflight-evidence.json", {"blocks": False})
    _write(evidence / "azure-preflight-evidence.json", {"blocks": False})
    _write(
        evidence / "apply-claim.json",
        {
            "schema_version": "fdai.deployment-apply-claim.v1",
            "plan_id": _PLAN_ID,
            "plan_digest": _PLAN_DIGEST,
            "workflow_run_id": str(_RUN_ID),
            "workflow_run_attempt": str(_RUN_ATTEMPT),
        },
    )
    _write(
        evidence / "apply-receipt.json",
        {
            "schema_version": "fdai.deployment-apply-receipt.v1",
            "plan_id": _PLAN_ID,
            "plan_digest": _PLAN_DIGEST,
            "workflow_run_id": str(_RUN_ID),
            "workflow_run_attempt": str(_RUN_ATTEMPT),
            "applied_at": (_NOW - timedelta(minutes=5)).isoformat(),
            "status": status,
        },
    )
    (evidence / "decision-evidence-container-url.txt").write_text(
        "https://example.com/operational-history\n",
        encoding="utf-8",
    )
    return evidence


def _source_run() -> dict[str, object]:
    return {
        "id": _RUN_ID,
        "run_attempt": _RUN_ATTEMPT,
        "head_sha": _COMMIT,
        "head_branch": "main",
        "path": ".github/workflows/deploy-dev.yml",
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
    }


def test_builds_five_non_authorizing_proofs(
    verifier: ModuleType,
    tmp_path: Path,
) -> None:
    receipt, requirement, authentication, readback, container_url = (
        verifier.build_deployment_decision_evidence(
            evidence_dir=_evidence_dir(tmp_path),
            source_run=_source_run(),
            expected_commit_sha=_COMMIT,
            expected_run_id=_RUN_ID,
            expected_run_attempt=_RUN_ATTEMPT,
            evaluated_at=_NOW,
            policy=_policy(),
        )
    )

    assert receipt.execution_authority is False
    assert requirement.source_revision == _COMMIT
    assert authentication.kind is EvidenceVerificationProofKind.AUTHENTICATION
    assert len(readback) == 4
    assert all(proof.execution_authority is False for proof in (authentication, *readback))
    assert container_url == "https://example.com/operational-history"


def test_rejects_source_run_mismatch(verifier: ModuleType, tmp_path: Path) -> None:
    source_run = _source_run()
    source_run["head_sha"] = "f" * 40

    with pytest.raises(verifier.DeploymentDecisionEvidenceError, match="source deployment run"):
        verifier.build_deployment_decision_evidence(
            evidence_dir=_evidence_dir(tmp_path),
            source_run=source_run,
            expected_commit_sha=_COMMIT,
            expected_run_id=_RUN_ID,
            expected_run_attempt=_RUN_ATTEMPT,
            evaluated_at=_NOW,
            policy=_policy(),
        )


def test_rejects_source_run_from_non_main_branch(
    verifier: ModuleType,
    tmp_path: Path,
) -> None:
    source_run = _source_run()
    source_run["head_branch"] = "feature/untrusted"

    with pytest.raises(verifier.DeploymentDecisionEvidenceError, match="source deployment run"):
        verifier.build_deployment_decision_evidence(
            evidence_dir=_evidence_dir(tmp_path),
            source_run=source_run,
            expected_commit_sha=_COMMIT,
            expected_run_id=_RUN_ID,
            expected_run_attempt=_RUN_ATTEMPT,
            evaluated_at=_NOW,
            policy=_policy(),
        )


def test_rejects_non_applied_receipt(verifier: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(verifier.DeploymentDecisionEvidenceError, match="do not agree"):
        verifier.build_deployment_decision_evidence(
            evidence_dir=_evidence_dir(tmp_path, status="failed"),
            source_run=_source_run(),
            expected_commit_sha=_COMMIT,
            expected_run_id=_RUN_ID,
            expected_run_attempt=_RUN_ATTEMPT,
            evaluated_at=_NOW,
            policy=_policy(),
        )


def test_rejects_stale_deployment_evidence(verifier: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(verifier.DeploymentDecisionEvidenceError, match="freshness window"):
        verifier.build_deployment_decision_evidence(
            evidence_dir=_evidence_dir(tmp_path),
            source_run=_source_run(),
            expected_commit_sha=_COMMIT,
            expected_run_id=_RUN_ID,
            expected_run_attempt=_RUN_ATTEMPT,
            evaluated_at=_NOW + timedelta(hours=2),
            policy=_policy(),
        )


def test_output_writer_refuses_existing_path_and_uses_owner_only_mode(
    verifier: ModuleType,
    tmp_path: Path,
) -> None:
    output = tmp_path / "receipt.json"
    verifier._write(output, {"safe": True})

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(
        verifier.DeploymentDecisionEvidenceError,
        match="new regular file",
    ):
        verifier._write(output, {"unsafe": True})


def test_rejects_symlinked_source_artifact(
    verifier: ModuleType,
    tmp_path: Path,
) -> None:
    evidence = _evidence_dir(tmp_path)
    metadata = evidence / "plan-metadata.json"
    target = evidence / "actual-metadata.json"
    metadata.rename(target)
    metadata.symlink_to(target)

    with pytest.raises(verifier.DeploymentDecisionEvidenceError, match="regular file"):
        verifier.build_deployment_decision_evidence(
            evidence_dir=evidence,
            source_run=_source_run(),
            expected_commit_sha=_COMMIT,
            expected_run_id=_RUN_ID,
            expected_run_attempt=_RUN_ATTEMPT,
            evaluated_at=_NOW,
            policy=_policy(),
        )
