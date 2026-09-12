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
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "deployment"
    / "azure"
    / "verify-deployment-plan.py"
)
_NOW = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)
_PLAN_ID = "plan-123-1"
_CONTEXT_DIGEST = "d" * 64
_COMMIT_SHA = "b" * 40
_POST_APPLY_OBSERVATIONS = [
    "database-migrations",
    "runtime-health",
    "initial-inventory-execution",
    "canary-publisher",
    "terraform-zero-change",
]
_COST_GOVERNANCE_POST_APPLY_OBSERVATIONS = [
    "terraform-zero-change",
    "cost-governance-job-image-readback",
]


def _plan_summary(*, create: int = 1, delete: int = 0, replace: int = 0) -> dict[str, object]:
    action_counts = {
        "create": create,
        "delete": delete,
        "no_op": 0,
        "read": 0,
        "replace": replace,
        "update": 0,
    }
    type_counts = {
        "terraform_data": {name: count for name, count in action_counts.items() if count}
    }
    body: dict[str, object] = {
        "schema_version": "fdai.deployment-plan-summary.v1",
        "action_counts": action_counts,
        "resource_type_counts": type_counts,
        "managed_resources": sum(action_counts.values()),
        "destructive": bool(delete or replace),
    }
    body["summary_digest"] = hashlib.sha256(
        json.dumps(body, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return body


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
    runtime_image: dict[str, str] | None = None,
    model_resolution: dict[str, object] | None = None,
    request_kind: str = "standard",
    request_id: str = "plan-request",
    include_summary: bool = True,
    plan_summary: dict[str, object] | None = None,
    post_apply_observations: list[str] | None = None,
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
    metadata_payload: dict[str, object] = {
        "schema_version": "fdai.deployment-plan.v1",
        "plan_id": _PLAN_ID,
        "plan_digest": digest,
        "source_artifact_digest": hashlib.sha256(source_artifact.read_bytes()).hexdigest(),
        "context_digest": _CONTEXT_DIGEST,
        "preflight_evidence_digest": hashlib.sha256(preflight.read_bytes()).hexdigest(),
        "azure_preflight_evidence_digest": hashlib.sha256(azure_preflight.read_bytes()).hexdigest(),
        "preflight_blocks": False,
        "commit_sha": _COMMIT_SHA,
        "request_id": request_id,
        "request_kind": request_kind,
        "created_at": (_NOW - timedelta(minutes=5)).isoformat(),
        "expires_at": expires_at.isoformat(),
        "status": "ready",
        "workflow_run_id": "123",
    }
    if include_summary:
        metadata_payload["plan_summary"] = plan_summary or _plan_summary()
        metadata_payload["post_apply_observations"] = list(
            post_apply_observations
            or (
                _COST_GOVERNANCE_POST_APPLY_OBSERVATIONS
                if runtime_image is not None and runtime_image.get("profile") == "cost-governance"
                else _POST_APPLY_OBSERVATIONS
            )
        )
    if runtime_image is not None:
        metadata_payload["runtime_image"] = runtime_image
    if model_resolution is not None:
        metadata_payload["model_resolution"] = model_resolution
    metadata.write_text(json.dumps(metadata_payload), encoding="utf-8")
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
        expected_request_kind="standard",
        expected_environment="dev",
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


def test_legacy_v1_plan_without_summary_evidence_passes(
    verify_module: ModuleType,
    tmp_path: Path,
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        include_summary=False,
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


def test_plan_summary_digest_must_match(verify_module: ModuleType, tmp_path: Path) -> None:
    summary = _plan_summary()
    summary["summary_digest"] = "f" * 64
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        plan_summary=summary,
    )

    with pytest.raises(verify_module.PlanVerificationError, match="summary digest does not match"):
        _verify(
            verify_module,
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            digest,
        )


def test_destructive_plan_summary_is_rejected(verify_module: ModuleType, tmp_path: Path) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        plan_summary=_plan_summary(create=0, delete=1),
    )

    with pytest.raises(verify_module.PlanVerificationError, match="summary is destructive"):
        _verify(
            verify_module,
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            digest,
        )


def test_runtime_state_only_replacement_summary_passes(
    verify_module: ModuleType,
    tmp_path: Path,
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        plan_summary=_plan_summary(create=0, replace=1),
        request_id=f"plan-runtime-{'a' * 48}",
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


def test_standard_state_only_replacement_summary_is_rejected(
    verify_module: ModuleType,
    tmp_path: Path,
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        plan_summary=_plan_summary(create=0, replace=1),
    )

    with pytest.raises(verify_module.PlanVerificationError, match="summary is destructive"):
        _verify(
            verify_module,
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            digest,
        )


def test_runtime_state_only_replacement_cannot_include_create(
    verify_module: ModuleType,
    tmp_path: Path,
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        plan_summary=_plan_summary(create=1, replace=1),
        request_id=f"plan-runtime-{'a' * 48}",
    )

    with pytest.raises(verify_module.PlanVerificationError, match="summary is destructive"):
        _verify(
            verify_module,
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            digest,
        )


def test_plan_summary_requires_post_apply_observations(
    verify_module: ModuleType,
    tmp_path: Path,
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
    )
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    del payload["post_apply_observations"]
    metadata.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(verify_module.PlanVerificationError, match="summary evidence is incomplete"):
        _verify(
            verify_module,
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            digest,
        )


def test_matching_runtime_image_evidence_passes(
    verify_module: ModuleType,
    tmp_path: Path,
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        runtime_image={
            "source_revision": "a" * 40,
            "digest": f"sha256:{'c' * 64}",
            "profile": "cost-governance",
        },
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


def test_cost_runtime_image_rejects_core_post_apply_observations(
    verify_module: ModuleType,
    tmp_path: Path,
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        runtime_image={
            "source_revision": "a" * 40,
            "digest": f"sha256:{'c' * 64}",
            "profile": "cost-governance",
        },
        post_apply_observations=_POST_APPLY_OBSERVATIONS,
    )

    with pytest.raises(verify_module.PlanVerificationError, match="observations are invalid"):
        _verify(
            verify_module,
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            digest,
        )


def test_matching_model_resolution_evidence_passes(
    verify_module: ModuleType,
    tmp_path: Path,
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        model_resolution={
            "resolved_models_digest": "a" * 64,
            "deployment_models_digest": "b" * 64,
        },
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


def test_matching_chatops_validation_evidence_passes(
    verify_module: ModuleType,
    tmp_path: Path,
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        model_resolution={
            "resolved_models_digest": "a" * 64,
            "deployment_models_digest": "b" * 64,
            "chatops_channel_validation": True,
        },
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


def test_chatops_validation_evidence_must_be_boolean(
    verify_module: ModuleType,
    tmp_path: Path,
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        model_resolution={
            "resolved_models_digest": "a" * 64,
            "deployment_models_digest": "b" * 64,
            "chatops_channel_validation": "true",
        },
    )

    with pytest.raises(verify_module.PlanVerificationError, match="ChatOps validation flag"):
        _verify(
            verify_module,
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            digest,
        )


def test_matching_model_binding_provenance_passes(
    verify_module: ModuleType,
    tmp_path: Path,
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        request_kind="model",
        model_resolution={
            "resolved_models_digest": "a" * 64,
            "deployment_models_digest": "b" * 64,
            "binding_policy_environment": "dev",
            "binding_policy_revision": 2,
            "binding_policy_digest": f"sha256:{'c' * 64}",
            "binding_policy_expected_active_digest": f"sha256:{'d' * 64}",
            "active_core_revision": "core--revision",
            "active_core_image_digest": "e" * 64,
            "active_core_model_digest": "d" * 64,
        },
    )

    verify_module.verify_plan(
        plan,
        source_artifact,
        metadata,
        preflight,
        azure_preflight,
        expected_plan_id=_PLAN_ID,
        expected_plan_digest=digest,
        expected_context_digest=_CONTEXT_DIGEST,
        expected_commit_sha=_COMMIT_SHA,
        expected_request_kind="model",
        expected_environment="dev",
        now=_NOW,
    )


def test_model_plan_without_binding_policy_provenance_fails(
    verify_module: ModuleType,
    tmp_path: Path,
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        request_kind="model",
        model_resolution={
            "resolved_models_digest": "a" * 64,
            "deployment_models_digest": "b" * 64,
        },
    )

    with pytest.raises(verify_module.PlanVerificationError, match="policy provenance"):
        verify_module.verify_plan(
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            expected_plan_id=_PLAN_ID,
            expected_plan_digest=digest,
            expected_context_digest=_CONTEXT_DIGEST,
            expected_commit_sha=_COMMIT_SHA,
            expected_request_kind="model",
            expected_environment="dev",
            now=_NOW,
        )


@pytest.mark.parametrize(
    ("environment", "revision"),
    [("staging", 2), ("dev", True)],
)
def test_model_plan_rejects_invalid_policy_provenance(
    verify_module: ModuleType,
    tmp_path: Path,
    environment: str,
    revision: object,
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        request_kind="model",
        model_resolution={
            "resolved_models_digest": "a" * 64,
            "deployment_models_digest": "b" * 64,
            "binding_policy_environment": environment,
            "binding_policy_revision": revision,
            "binding_policy_digest": f"sha256:{'c' * 64}",
            "binding_policy_expected_active_digest": f"sha256:{'d' * 64}",
            "active_core_revision": "core--revision",
            "active_core_image_digest": "e" * 64,
            "active_core_model_digest": "d" * 64,
        },
    )

    with pytest.raises(verify_module.PlanVerificationError, match="provenance"):
        verify_module.verify_plan(
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            expected_plan_id=_PLAN_ID,
            expected_plan_digest=digest,
            expected_context_digest=_CONTEXT_DIGEST,
            expected_commit_sha=_COMMIT_SHA,
            expected_request_kind="model",
            expected_environment="dev",
            now=_NOW,
        )


@pytest.mark.parametrize(
    "model_resolution",
    [
        {"resolved_models_digest": "bad", "deployment_models_digest": "b" * 64},
        {"resolved_models_digest": "a" * 64, "deployment_models_digest": "bad"},
        {
            "resolved_models_digest": "a" * 64,
            "deployment_models_digest": "b" * 64,
            "extra": "x",
        },
    ],
)
def test_invalid_model_resolution_evidence_fails(
    verify_module: ModuleType,
    tmp_path: Path,
    model_resolution: dict[str, object],
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        model_resolution=model_resolution,
    )

    with pytest.raises(verify_module.PlanVerificationError, match="model resolution"):
        _verify(
            verify_module,
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            digest,
        )


@pytest.mark.parametrize(
    "runtime_image",
    [
        {
            "source_revision": "bad",
            "digest": f"sha256:{'c' * 64}",
            "profile": "cost-governance",
        },
        {"source_revision": "a" * 40, "digest": "bad", "profile": "cost-governance"},
        {"source_revision": "a" * 40, "digest": f"sha256:{'c' * 64}"},
        {
            "source_revision": "a" * 40,
            "digest": f"sha256:{'c' * 64}",
            "profile": "unknown",
        },
        {
            "source_revision": "a" * 40,
            "digest": f"sha256:{'c' * 64}",
            "profile": "cost-governance",
            "extra": "x",
        },
    ],
)
def test_invalid_runtime_image_evidence_fails(
    verify_module: ModuleType,
    tmp_path: Path,
    runtime_image: dict[str, str],
) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
        runtime_image=runtime_image,
    )

    with pytest.raises(verify_module.PlanVerificationError, match="runtime image"):
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
            expected_request_kind="standard",
            expected_environment="dev",
            now=_NOW,
        )


def test_request_kind_mismatch_fails(verify_module: ModuleType, tmp_path: Path) -> None:
    plan, source_artifact, metadata, preflight, azure_preflight, digest = _write_artifacts(
        tmp_path,
        expires_at=_NOW + timedelta(minutes=30),
    )

    with pytest.raises(verify_module.PlanVerificationError, match="request kind"):
        verify_module.verify_plan(
            plan,
            source_artifact,
            metadata,
            preflight,
            azure_preflight,
            expected_plan_id=_PLAN_ID,
            expected_plan_digest=digest,
            expected_context_digest=_CONTEXT_DIGEST,
            expected_commit_sha=_COMMIT_SHA,
            expected_request_kind="model",
            expected_environment="dev",
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
