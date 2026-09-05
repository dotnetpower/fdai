from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from scripts.deployment.service.verify_core_apply_request import (
    CoreApplyRequestError,
    verify_core_apply_request,
)

_NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)
_REPOSITORY = "example/fdai"
_COMMIT_SHA = "a" * 40
_IMAGE_DIGEST = "b" * 64
_IMAGE_REF = f"ghcr.io/{_REPOSITORY}/fdai-core-control-plane@sha256:{_IMAGE_DIGEST}"
_PLAN_DIGEST = "c" * 64
_CONTEXT_DIGEST = "d" * 64
_PLAN_RUN_ID = "123"
_PLAN_RUN_ATTEMPT = "2"


def _run() -> dict[str, Any]:
    return {
        "id": int(_PLAN_RUN_ID),
        "run_attempt": int(_PLAN_RUN_ATTEMPT),
        "conclusion": "success",
        "event": "workflow_dispatch",
        "path": ".github/workflows/service-deploy.yml",
        "head_sha": "e" * 40,
        "repository": {"full_name": _REPOSITORY},
    }


def _metadata() -> dict[str, Any]:
    return {
        "schema_version": "fdai.service-deployment-plan.v6",
        "status": "ready",
        "plan_id": f"core-control-plane-dev-{_PLAN_RUN_ID}-{_PLAN_RUN_ATTEMPT}",
        "service": "core-control-plane",
        "environment": "dev",
        "commit_sha": _COMMIT_SHA,
        "image_ref": _IMAGE_REF,
        "image_digest": f"sha256:{_IMAGE_DIGEST}",
        "plan_digest": _PLAN_DIGEST,
        "context_digest": _CONTEXT_DIGEST,
        "workflow_run_id": _PLAN_RUN_ID,
        "workflow_run_attempt": _PLAN_RUN_ATTEMPT,
        "degraded_recovery": False,
        "deployment_mode": "model-binding",
        "created_at": (_NOW - timedelta(minutes=5)).isoformat(),
        "expires_at": (_NOW + timedelta(hours=1)).isoformat(),
    }


def _verify(
    *,
    run: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    environment: str = "dev",
    image_ref: str = _IMAGE_REF,
    plan_digest: str = _PLAN_DIGEST,
) -> None:
    verify_core_apply_request(
        run=run or _run(),
        metadata=metadata or _metadata(),
        repository=_REPOSITORY,
        environment=environment,
        commit_sha=_COMMIT_SHA,
        image_ref=image_ref,
        plan_run_id=_PLAN_RUN_ID,
        plan_run_attempt=_PLAN_RUN_ATTEMPT,
        plan_digest=plan_digest,
        context_digest=_CONTEXT_DIGEST,
        now=_NOW,
    )


def test_accepts_exact_unexpired_core_model_binding_plan() -> None:
    _verify()


@pytest.mark.parametrize("environment", ["prod", "qa", ""])
def test_rejects_unsupported_environment(environment: str) -> None:
    with pytest.raises(CoreApplyRequestError, match="only for dev and staging"):
        _verify(environment=environment)


def test_rejects_non_core_image() -> None:
    image_ref = f"ghcr.io/{_REPOSITORY}/fdai-operator-service@sha256:{_IMAGE_DIGEST}"
    with pytest.raises(CoreApplyRequestError, match="repository Core image"):
        _verify(image_ref=image_ref)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("conclusion", "failure"),
        ("event", "push"),
        ("path", ".github/workflows/deploy-dev.yml"),
        ("run_attempt", 1),
    ],
)
def test_rejects_mismatched_plan_run(field: str, value: Any) -> None:
    run = _run()
    run[field] = value
    with pytest.raises(CoreApplyRequestError, match=f"source plan run {field}"):
        _verify(run=run)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service", "operator-service"),
        ("deployment_mode", "standard"),
        ("degraded_recovery", True),
        ("commit_sha", "f" * 40),
        ("image_digest", f"sha256:{'f' * 64}"),
        ("plan_digest", "f" * 64),
        ("context_digest", "f" * 64),
        ("workflow_run_id", "456"),
        ("workflow_run_attempt", "1"),
    ],
)
def test_rejects_mismatched_plan_metadata(field: str, value: Any) -> None:
    metadata = _metadata()
    metadata[field] = value
    with pytest.raises(CoreApplyRequestError, match=f"plan metadata {field}"):
        _verify(metadata=metadata)


def test_rejects_expired_plan() -> None:
    metadata = _metadata()
    metadata["expires_at"] = (_NOW - timedelta(seconds=1)).isoformat()
    with pytest.raises(CoreApplyRequestError, match="has expired"):
        _verify(metadata=metadata)


def test_rejects_invalid_request_digest_before_metadata_comparison() -> None:
    with pytest.raises(CoreApplyRequestError, match="plan_digest"):
        _verify(plan_digest="not-a-digest")
