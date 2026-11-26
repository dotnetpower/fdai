from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fdai_ingestion_api_service.auth import (
    AuthenticationError,
    ChannelAttachmentWorkloadAuthenticator,
    WorkloadAuthorizationError,
)
from fdai_ingestion_api_service.channel_attachment_http import (
    ChannelAttachmentHttpConfig,
    build_channel_attachment_app,
)
from fdai_service_contracts import (
    ChannelAttachmentAdmissionReceipt,
    ChannelAttachmentCommitReceipt,
    ChannelAttachmentTerminalReceipt,
)
from fdai_service_contracts.compatibility import canonical_digest
from starlette.testclient import TestClient

NOW = datetime(2026, 9, 14, 3, 0, tzinfo=UTC)
HANDOFF_ID = "channel-attachment-" + "a" * 64
REQUEST_DIGEST = f"sha256:{'b' * 64}"
CONTENT = b"bounded content"
CONTENT_SHA256 = hashlib.sha256(CONTENT).hexdigest()
UPLOAD_ID = UUID("00000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000002")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000003")


def _claims(**updates: object) -> Mapping[str, Any]:
    claims: dict[str, object] = {
        "idtyp": "app",
        "oid": "workload-object",
        "azp": "edge-client",
        "roles": ["Document.ChannelAttachment.Submit"],
    }
    claims.update(updates)
    return claims


def _authenticator(claims: Mapping[str, Any] | None = None):
    return ChannelAttachmentWorkloadAuthenticator(
        verifier=lambda _token: claims or _claims(),
        allowed_client_id="edge-client",
    )


def _admission_request() -> dict[str, object]:
    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "handoff_id": HANDOFF_ID,
        "idempotency_key": "message-1:attachment:0",
        "origin_digest": f"sha256:{'c' * 64}",
        "ordinal": 0,
        "attributed_principal_id": "principal-1",
        "principal_manifest_digest": f"sha256:{'d' * 64}",
        "conversation_ref": "conversation-1",
        "requested_purpose": "knowledge_base",
        "source_name": "evidence.txt",
        "media_type_hint": "text/plain",
        "declared_size": len(CONTENT),
        "requested_at": NOW.isoformat().replace("+00:00", "Z"),
        "execution_authority": False,
    }
    return {**material, "request_digest": canonical_digest(material)}


def _receipt(model: type, material: dict[str, object]):  # type: ignore[type-arg]
    return model.model_validate({**material, "receipt_digest": canonical_digest(material)})


class RecordingIntake:
    def __init__(self) -> None:
        self.admissions = 0
        self.commits = 0
        self.statuses = 0
        self.content = b""

    async def admit(self, request: object) -> ChannelAttachmentAdmissionReceipt:
        self.admissions += 1
        return _receipt(
            ChannelAttachmentAdmissionReceipt,
            {
                "schema_version": "1.0.0",
                "receipt_kind": "admission",
                "handoff_id": HANDOFF_ID,
                "request_digest": request.request_digest,  # type: ignore[attr-defined]
                "policy_digest": f"sha256:{'e' * 64}",
                "max_content_bytes": 1024,
                "accepted_at": NOW.isoformat().replace("+00:00", "Z"),
                "expires_at": (NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
                "execution_authority": False,
            },
        )

    async def commit(
        self,
        *,
        handoff_id: str,
        request_digest: str,
        observed_size: int,
        observed_sha256: str,
        chunks: AsyncIterator[bytes],
    ) -> ChannelAttachmentCommitReceipt:
        self.commits += 1
        self.content = b"".join([chunk async for chunk in chunks])
        assert handoff_id == HANDOFF_ID
        assert request_digest == REQUEST_DIGEST
        assert observed_size == len(CONTENT)
        assert observed_sha256 == CONTENT_SHA256
        return _receipt(
            ChannelAttachmentCommitReceipt,
            {
                "schema_version": "1.0.0",
                "receipt_kind": "commit",
                "handoff_id": HANDOFF_ID,
                "request_digest": REQUEST_DIGEST,
                "upload_id": str(UPLOAD_ID),
                "document_id": str(DOCUMENT_ID),
                "version_id": str(VERSION_ID),
                "observed_size": len(CONTENT),
                "observed_sha256": CONTENT_SHA256,
                "state": "received",
                "committed_at": NOW.isoformat().replace("+00:00", "Z"),
                "execution_authority": False,
            },
        )

    async def status(
        self,
        *,
        handoff_id: str,
        request_digest: str,
    ) -> ChannelAttachmentTerminalReceipt:
        self.statuses += 1
        assert handoff_id == HANDOFF_ID
        assert request_digest == REQUEST_DIGEST
        return _receipt(
            ChannelAttachmentTerminalReceipt,
            {
                "schema_version": "1.0.0",
                "receipt_kind": "terminal",
                "handoff_id": HANDOFF_ID,
                "request_digest": REQUEST_DIGEST,
                "upload_id": str(UPLOAD_ID),
                "document_id": str(DOCUMENT_ID),
                "version_id": str(VERSION_ID),
                "commit_receipt_digest": f"sha256:{'f' * 64}",
                "observed_size": len(CONTENT),
                "observed_sha256": CONTENT_SHA256,
                "requested_purpose": "knowledge_base",
                "outcome": "ready",
                "document_state": "ready",
                "index_state": "active",
                "retention_state": "live",
                "active": True,
                "available": True,
                "handover_draft_ready": False,
                "citation": f"doc:{DOCUMENT_ID}:{VERSION_ID}",
                "reason_code": None,
                "observed_at": NOW.isoformat().replace("+00:00", "Z"),
                "execution_authority": False,
            },
        )


def test_workload_authenticator_requires_exact_app_identity_and_role() -> None:
    assert _authenticator().authenticate("Bearer token") == "workload-object"
    for claims in (
        _claims(idtyp="user"),
        _claims(azp="other-client"),
        _claims(roles=["Reader"]),
        _claims(roles=["Document.ChannelAttachment.Submit", "Reader"]),
        _claims(scp="user_impersonation"),
        _claims(groups=["group-1"]),
    ):
        with pytest.raises(WorkloadAuthorizationError):
            _authenticator(claims).authenticate("Bearer token")
    with pytest.raises(AuthenticationError):
        _authenticator().authenticate(None)


def test_readiness_fails_when_supervised_background_task_stops() -> None:
    async def stopped_task() -> None:
        await asyncio.sleep(0)

    app = build_channel_attachment_app(
        authenticator=_authenticator(),
        intake=RecordingIntake(),  # type: ignore[arg-type]
        config=ChannelAttachmentHttpConfig(background_tasks=(stopped_task,)),
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "not_ready"


def test_authentication_happens_before_admission_body_parsing() -> None:
    intake = RecordingIntake()
    app = build_channel_attachment_app(
        authenticator=ChannelAttachmentWorkloadAuthenticator(
            verifier=lambda _token: (_ for _ in ()).throw(AuthenticationError("invalid")),
            allowed_client_id="edge-client",
        ),
        intake=intake,  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        response = client.post(
            "/internal/document-ingestion/channel-attachments/v1/admissions",
            headers={"Authorization": "Bearer invalid"},
            content=b"not-json",
        )
    assert response.status_code == 401
    assert intake.admissions == 0


def test_auth_probe_requires_the_same_exact_workload_role() -> None:
    valid = build_channel_attachment_app(
        authenticator=_authenticator(),
        intake=RecordingIntake(),  # type: ignore[arg-type]
    )
    denied = build_channel_attachment_app(
        authenticator=_authenticator(_claims(roles=["Reader"])),
        intake=RecordingIntake(),  # type: ignore[arg-type]
    )

    with TestClient(valid) as client:
        accepted = client.get(
            "/internal/document-ingestion/channel-attachments/v1/auth-probe",
            headers={"Authorization": "Bearer token"},
        )
    with TestClient(denied) as client:
        rejected = client.get(
            "/internal/document-ingestion/channel-attachments/v1/auth-probe",
            headers={"Authorization": "Bearer token"},
        )

    assert accepted.status_code == 204
    assert rejected.status_code == 403


def test_internal_routes_validate_contract_and_forward_bounded_content() -> None:
    intake = RecordingIntake()
    app = build_channel_attachment_app(
        authenticator=_authenticator(),
        intake=intake,  # type: ignore[arg-type]
    )
    headers = {"Authorization": "Bearer token"}
    with TestClient(app) as client:
        admission = client.post(
            "/internal/document-ingestion/channel-attachments/v1/admissions",
            headers=headers,
            json=_admission_request(),
        )
        content = client.put(
            f"/internal/document-ingestion/channel-attachments/v1/{HANDOFF_ID}/content",
            headers={
                **headers,
                "x-fdai-request-digest": REQUEST_DIGEST,
                "x-fdai-content-sha256": CONTENT_SHA256,
                "content-length": str(len(CONTENT)),
            },
            content=CONTENT,
        )
        status = client.get(
            f"/internal/document-ingestion/channel-attachments/v1/{HANDOFF_ID}",
            headers={**headers, "x-fdai-request-digest": REQUEST_DIGEST},
        )

    assert admission.status_code == 201
    assert admission.json()["receipt_kind"] == "admission"
    assert content.status_code == 200
    assert content.json()["receipt_kind"] == "commit"
    assert status.status_code == 200
    assert status.json()["citation"] == f"doc:{DOCUMENT_ID}:{VERSION_ID}"
    assert intake.content == CONTENT
    assert (intake.admissions, intake.commits, intake.statuses) == (1, 1, 1)


def test_content_route_rejects_missing_length_and_invalid_digest_before_intake() -> None:
    intake = RecordingIntake()
    app = build_channel_attachment_app(
        authenticator=_authenticator(),
        intake=intake,  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        response = client.put(
            f"/internal/document-ingestion/channel-attachments/v1/{HANDOFF_ID}/content",
            headers={
                "Authorization": "Bearer token",
                "x-fdai-request-digest": "sha256:bad",
                "x-fdai-content-sha256": CONTENT_SHA256,
            },
            content=CONTENT,
        )
    assert response.status_code == 400
    assert intake.commits == 0
