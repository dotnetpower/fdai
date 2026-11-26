"""Fail-closed production composition tests for the channel attachment intake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai_ingestion_api_service import channel_attachment_production as production


def _environment(tmp_path: Path) -> dict[str, str]:
    return {
        "FDAI_EXECUTION_VENUE": "local",
        "FDAI_DATABASE_URL": "postgresql://example.invalid/fdai",
        "FDAI_DATABASE_ROLE": "fdai_ingestion_api",
        "FDAI_INGESTION_DEPLOYMENT_ROLE": "channel-intake",
        "FDAI_KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:19092",
        "FDAI_DOCUMENT_EVENT_TOPIC": "fdai.pipeline.stages",
        "FDAI_ENTRA_TENANT_ID": "tenant-example",
        "FDAI_CHANNEL_ATTACHMENT_API_AUDIENCE": "api://document-ingestion",
        "FDAI_CHANNEL_EDGE_CLIENT_ID": "channel-edge-client",
        "FDAI_CHANNEL_ATTACHMENT_PRINCIPAL_SCOPES_JSON": json.dumps(
            {
                "principal-example": {
                    "scope_ref": "scope://operator/example",
                    "roles": ["Contributor"],
                    "locale": "en",
                }
            }
        ),
        "FDAI_CHANNEL_ATTACHMENT_COLLECTION_ID": "channel-evidence",
        "FDAI_CHANNEL_ATTACHMENT_ACCESS_DESCRIPTOR_REF": "access:channel-evidence",
        "FDAI_CHANNEL_ATTACHMENT_READER_GROUPS": "group:responders",
        "FDAI_CHANNEL_ATTACHMENT_RETENTION_POLICY_VERSION": "session-v1",
        "FDAI_CHANNEL_ATTACHMENT_MAX_CONTENT_BYTES": "1048576",
        "FDAI_LOCAL_DOCUMENT_STORE_DIR": str(tmp_path),
    }


def test_local_channel_intake_composes_fixed_routes_without_managed_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def forbidden_credential(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("local channel intake requested managed identity")

    monkeypatch.setattr(production, "ManagedIdentityCredential", forbidden_credential)

    app = production.build_channel_attachment_application(_environment(tmp_path))

    assert {route.path for route in app.routes} == {
        "/health/live",
        "/health/ready",
        "/internal/document-ingestion/channel-attachments/v1/auth-probe",
        "/internal/document-ingestion/channel-attachments/v1/admissions",
        "/internal/document-ingestion/channel-attachments/v1/{handoff_id}/content",
        "/internal/document-ingestion/channel-attachments/v1/{handoff_id}",
    }


def test_channel_intake_rejects_wrong_role_before_provider_allocation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    environment["FDAI_INGESTION_DEPLOYMENT_ROLE"] = "api"

    def forbidden_store(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("provider allocated before role validation")

    monkeypatch.setattr(production, "LocalDocumentObjectStore", forbidden_store)

    with pytest.raises(
        production.ChannelAttachmentProductionConfigurationError,
        match="MUST be channel-intake",
    ):
        production.build_channel_attachment_application(environment)


def test_channel_intake_rejects_duplicate_manifest_keys(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    environment["FDAI_CHANNEL_ATTACHMENT_PRINCIPAL_SCOPES_JSON"] = (
        '{"principal-example":{"scope_ref":"one","roles":["Contributor"]},'
        '"principal-example":{"scope_ref":"two","roles":["Owner"]}}'
    )

    with pytest.raises(ValueError, match="invalid JSON"):
        production.build_channel_attachment_application(environment)
