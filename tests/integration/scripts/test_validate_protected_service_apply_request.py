from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from scripts.deployment.azure.validate_protected_service_apply_request import (
    ProtectedServiceApplyRequestError,
    validate_protected_service_apply_request,
)

_REPOSITORY = "example/fdai"
_COMMIT_SHA = "a" * 40
_PLAN_RUN_ID = "123"
_PLAN_RUN_ATTEMPT = "2"
_PLAN_DIGEST = "b" * 64
_CONTEXT_DIGEST = "c" * 64


def _valid_request(
    *,
    service: str = "core-control-plane",
    deployment_mode: str = "model-binding",
) -> dict[str, Any]:
    image_name = {
        "core-control-plane": "fdai-core-control-plane",
        "document-ingestion-api": "fdai-document-ingestion-api",
    }[service]
    image_ref = f"ghcr.io/{_REPOSITORY}/{image_name}@sha256:{'d' * 64}"
    return {
        "repository": _REPOSITORY,
        "service": service,
        "environment": "dev",
        "commit_sha": _COMMIT_SHA,
        "plan_run_id": _PLAN_RUN_ID,
        "plan_run_attempt": _PLAN_RUN_ATTEMPT,
        "plan_digest": _PLAN_DIGEST,
        "context_digest": _CONTEXT_DIGEST,
        "image_ref": image_ref,
        "run_metadata": {
            "id": int(_PLAN_RUN_ID),
            "run_attempt": int(_PLAN_RUN_ATTEMPT),
            "name": "service-deploy",
            "event": "workflow_dispatch",
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
            "repository": {"full_name": _REPOSITORY},
        },
        "artifacts": {
            "artifacts": [
                {
                    "name": (f"service-plan-{service}-dev-{_PLAN_RUN_ID}-{_PLAN_RUN_ATTEMPT}"),
                    "expired": False,
                }
            ]
        },
        "plan_metadata": {
            "plan_id": (f"{service}-dev-{_PLAN_RUN_ID}-{_PLAN_RUN_ATTEMPT}"),
            "workflow_run_id": _PLAN_RUN_ID,
            "workflow_run_attempt": _PLAN_RUN_ATTEMPT,
            "service": service,
            "environment": "dev",
            "status": "ready",
            "deployment_mode": deployment_mode,
            "commit_sha": _COMMIT_SHA,
            "plan_digest": _PLAN_DIGEST,
            "context_digest": _CONTEXT_DIGEST,
            "image_ref": image_ref,
            "image_digest": image_ref.rsplit("@", maxsplit=1)[1],
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    }


def test_valid_core_service_apply_request_is_accepted() -> None:
    validate_protected_service_apply_request(**_valid_request())


def test_repository_name_is_normalized_for_ghcr() -> None:
    request = _valid_request()
    request["repository"] = "Example/FDAI"
    request["run_metadata"]["repository"]["full_name"] = "Example/FDAI"

    validate_protected_service_apply_request(**request)


@pytest.mark.parametrize(
    "deployment_mode",
    [
        "standard",
        "database-host-binding",
        "sharepoint-connector-enable",
        "sharepoint-connector-disable",
    ],
)  # type: ignore[untyped-decorator]
def test_valid_document_service_apply_request_is_accepted(deployment_mode: str) -> None:
    validate_protected_service_apply_request(
        **_valid_request(
            service="document-ingestion-api",
            deployment_mode=deployment_mode,
        )
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda request: request.update(environment="prod"),
        lambda request: request.update(commit_sha="A" * 40),
        lambda request: request.update(plan_run_id="0"),
        lambda request: request.update(plan_run_attempt="../2"),
        lambda request: request.update(plan_digest="b" * 63),
        lambda request: request.update(context_digest="C" * 64),
        lambda request: request.update(service="operator-service"),
        lambda request: request.update(
            image_ref=f"ghcr.io/{_REPOSITORY}/fdai-operator-service@sha256:{'d' * 64}"
        ),
        lambda request: request["run_metadata"].update(name="deploy-dev"),
        lambda request: request["run_metadata"].update(event="push"),
        lambda request: request["run_metadata"].update(head_branch="feature"),
        lambda request: request["run_metadata"].update(status="in_progress"),
        lambda request: request["run_metadata"].update(conclusion="failure"),
        lambda request: request["run_metadata"]["repository"].update(full_name="example/other"),
        lambda request: request["artifacts"]["artifacts"][0].update(expired=True),
        lambda request: request["artifacts"].update(artifacts=[]),
        lambda request: request["plan_metadata"].update(deployment_mode="standard"),
        lambda request: request["plan_metadata"].update(deployment_mode={}),
        lambda request: request["plan_metadata"].update(service="operator-service"),
        lambda request: request["plan_metadata"].update(commit_sha="e" * 40),
        lambda request: request["plan_metadata"].update(plan_digest="f" * 64),
        lambda request: request["plan_metadata"].update(
            expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        ),
    ],
)  # type: ignore[untyped-decorator]
def test_invalid_core_service_apply_request_fails_closed(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    request = deepcopy(_valid_request())
    mutate(request)

    with pytest.raises(ProtectedServiceApplyRequestError):
        validate_protected_service_apply_request(**request)


def test_document_service_apply_rejects_cross_service_image_and_mode() -> None:
    request = _valid_request(
        service="document-ingestion-api",
        deployment_mode="database-host-binding",
    )
    request["image_ref"] = f"ghcr.io/{_REPOSITORY}/fdai-core-control-plane@sha256:{'d' * 64}"
    with pytest.raises(ProtectedServiceApplyRequestError):
        validate_protected_service_apply_request(**request)

    request = _valid_request(
        service="document-ingestion-api",
        deployment_mode="model-binding",
    )
    with pytest.raises(ProtectedServiceApplyRequestError):
        validate_protected_service_apply_request(**request)
