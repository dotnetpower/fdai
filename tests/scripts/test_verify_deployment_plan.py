"""Exact binary deployment-plan verification tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "deployment"
    / "azure"
    / "verify-deployment-plan.py"
)
_NOW = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)
_PLAN_ID = "plan-123-1"
_CONTEXT_DIGEST = "d" * 64
_COMMIT_SHA = "b" * 40


@pytest.fixture(scope="module")
def verify_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_deployment_plan", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_artifacts(
    root: Path,
    *,
    expires_at: datetime,
) -> tuple[Path, Path, Path, Path, Path, str]:
    plan = root / "terraform.plan"
    plan.write_bytes(b"deterministic-plan")
    digest = hashlib.sha256(plan.read_bytes()).hexdigest()
    source_artifact = root / "source.zip"
    source_artifact.write_bytes(b"deterministic-source")
    preflight = root / "preflight-evidence.json"
    preflight.write_text('{"schema":"egress.v1"}\n', encoding="utf-8")
    azure_preflight = root / "azure-preflight-evidence.json"
    azure_preflight.write_text('{"schema":"azure.v1"}\n', encoding="utf-8")
    metadata = root / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "schema_version": "fdai.deployment-plan.v1",
                "plan_id": _PLAN_ID,
                "plan_digest": digest,
                "source_artifact_digest": hashlib.sha256(source_artifact.read_bytes()).hexdigest(),
                "context_digest": _CONTEXT_DIGEST,
                "preflight_evidence_digest": hashlib.sha256(preflight.read_bytes()).hexdigest(),
                "azure_preflight_evidence_digest": hashlib.sha256(
                    azure_preflight.read_bytes()
                ).hexdigest(),
                "preflight_blocks": False,
                "commit_sha": _COMMIT_SHA,
                "request_id": "plan-request",
                "created_at": (_NOW - timedelta(minutes=5)).isoformat(),
                "expires_at": expires_at.isoformat(),
                "status": "ready",
                "workflow_run_id": "123",
            }
        ),
        encoding="utf-8",
    )
    return plan, source_artifact, metadata, preflight, azure_preflight, digest


def _verify(
    module: ModuleType,
    plan: Path,
    source_artifact: Path,
    metadata: Path,
    preflight: Path,
    azure_preflight: Path,
    digest: str,
) -> None:
    module.verify_plan(
        plan,
        source_artifact,
        metadata,
        preflight,
        azure_preflight,
        expected_plan_id=_PLAN_ID,
        expected_plan_digest=digest,
        expected_context_digest=_CONTEXT_DIGEST,
        expected_commit_sha=_COMMIT_SHA,
        now=_NOW,
    )


def test_matching_unexpired_plan_passes(verify_module: ModuleType, tmp_path: Path) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
    )

    _verify(
        verify_module,
        plan,
        source_artifact,
        metadata,
        preflight,
        azure_preflight,
        digest,
    )


def test_binary_digest_mismatch_fails(verify_module: ModuleType, tmp_path: Path) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
    )
    plan.write_bytes(b"changed-plan")

    with pytest.raises(verify_module.PlanVerificationError, match="binary plan digest"):
        _verify(
            verify_module,
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            digest,
        )


def test_expired_plan_fails(verify_module: ModuleType, tmp_path: Path) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW - timedelta(seconds=1),
    )

    with pytest.raises(verify_module.PlanVerificationError, match="expired"):
        _verify(
            verify_module,
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            digest,
        )


def test_context_mismatch_fails(verify_module: ModuleType, tmp_path: Path) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
    )

    with pytest.raises(verify_module.PlanVerificationError, match="context_digest"):
        verify_module.verify_plan(
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            expected_plan_id=_PLAN_ID,
            expected_plan_digest=digest,
            expected_context_digest="e" * 64,
            expected_commit_sha=_COMMIT_SHA,
            now=_NOW,
        )


def test_preflight_blocked_plan_fails(verify_module: ModuleType, tmp_path: Path) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
    )
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    payload["preflight_blocks"] = True
    metadata.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(verify_module.PlanVerificationError, match="preflight"):
        _verify(
            verify_module,
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            digest,
        )


def test_azure_preflight_evidence_digest_mismatch_fails(
    verify_module: ModuleType,
    tmp_path: Path,
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
    )
    azure_preflight.write_text('{"schema":"tampered"}\n', encoding="utf-8")

    with pytest.raises(verify_module.PlanVerificationError, match="Azure preflight evidence"):
        _verify(
            verify_module,
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            digest,
        )


def test_source_artifact_digest_mismatch_fails(
    verify_module: ModuleType,
    tmp_path: Path,
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
    )
    source_artifact.write_bytes(b"tampered-source")

    with pytest.raises(verify_module.PlanVerificationError, match="source artifact digest"):
        _verify(
            verify_module,
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            digest,
        )
