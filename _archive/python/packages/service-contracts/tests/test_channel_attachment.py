from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai_ingestion_api_service.contract_codecs import (
    CHANNEL_ATTACHMENT_ADMISSION_CONSUMER_UNAVAILABLE,
    CHANNEL_ATTACHMENT_ADMISSION_CONSUMER_V1,
    CHANNEL_ATTACHMENT_RECEIPT_PRODUCER_V1,
)
from fdai_operator_service.contract_codecs import (
    CHANNEL_ATTACHMENT_ADMISSION_PRODUCER_V1,
    CHANNEL_ATTACHMENT_RECEIPT_CONSUMER_UNAVAILABLE,
    CHANNEL_ATTACHMENT_RECEIPT_CONSUMER_V1,
)
from pydantic import ValidationError

from fdai_service_contracts.channel_attachment import (
    ChannelAttachmentAdmissionReceipt,
    ChannelAttachmentAdmissionRequest,
    ChannelAttachmentCommitReceipt,
    ChannelAttachmentOutcome,
    ChannelAttachmentTerminalReceipt,
    channel_attachment_receipt_digest,
    channel_attachment_request_digest,
)
from fdai_service_contracts.compatibility import CompatibilityError, canonical_digest
from fdai_service_contracts.document import (
    DocumentIndexState,
    DocumentPurpose,
    DocumentState,
)
from fdai_service_contracts.schema import JsonSchemaContractValidator, PackageResourceSchemaRegistry

NOW = datetime(2026, 9, 14, 1, 2, tzinfo=UTC)
HANDOFF_ID = "channel-attachment-" + "a" * 64
REQUEST_DIGEST = "sha256:" + "b" * 64
UPLOAD_ID = UUID("00000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000002")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000003")


def _request_material(**updates: object) -> dict[str, object]:
    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "handoff_id": HANDOFF_ID,
        "idempotency_key": "message-1:attachment:0",
        "origin_digest": "sha256:" + "c" * 64,
        "ordinal": 0,
        "attributed_principal_id": "principal-1",
        "principal_manifest_digest": "sha256:" + "d" * 64,
        "conversation_ref": "channel:" + "e" * 40,
        "requested_purpose": "knowledge_base",
        "source_name": "evidence.txt",
        "media_type_hint": "text/plain",
        "declared_size": 12,
        "requested_at": NOW.isoformat().replace("+00:00", "Z"),
        "execution_authority": False,
    }
    material.update(updates)
    return material


def _request(**updates: object) -> ChannelAttachmentAdmissionRequest:
    material = _request_material(**updates)
    return ChannelAttachmentAdmissionRequest.model_validate(
        {**material, "request_digest": canonical_digest(material)}
    )


def _receipt(model: type, material: dict[str, object]):  # type: ignore[type-arg]
    return model.model_validate({**material, "receipt_digest": canonical_digest(material)})


def _terminal_material(**updates: object) -> dict[str, object]:
    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "receipt_kind": "terminal",
        "handoff_id": HANDOFF_ID,
        "request_digest": REQUEST_DIGEST,
        "upload_id": str(UPLOAD_ID),
        "document_id": str(DOCUMENT_ID),
        "version_id": str(VERSION_ID),
        "commit_receipt_digest": "sha256:" + "3" * 64,
        "observed_size": 12,
        "observed_sha256": "2" * 64,
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
    }
    material.update(updates)
    return material


def test_admission_request_is_digest_bound_and_frozen() -> None:
    request = _request()

    assert request.request_digest == channel_attachment_request_digest(request)
    with pytest.raises(ValidationError):
        request.ordinal = 1  # type: ignore[misc]


@pytest.mark.parametrize("name", ["../evidence.txt", "folder/evidence.txt", ".", "bad\u202ename"])
def test_admission_request_rejects_unsafe_source_names(name: str) -> None:
    with pytest.raises(ValidationError, match="safe leaf"):
        _request(source_name=name)


def test_admission_request_rejects_unsupported_purpose_and_digest_mismatch() -> None:
    with pytest.raises(ValidationError, match="purpose is not supported"):
        _request(requested_purpose=DocumentPurpose.MANUAL_DISTILLATION.value)
    with pytest.raises(ValidationError, match="digest does not match"):
        ChannelAttachmentAdmissionRequest.model_validate(
            {**_request_material(), "request_digest": "sha256:" + "f" * 64}
        )


def test_admission_receipt_requires_ordered_aware_expiry() -> None:
    material = {
        "schema_version": "1.0.0",
        "receipt_kind": "admission",
        "handoff_id": HANDOFF_ID,
        "request_digest": REQUEST_DIGEST,
        "policy_digest": "sha256:" + "1" * 64,
        "max_content_bytes": 1024,
        "accepted_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "execution_authority": False,
    }
    receipt = _receipt(ChannelAttachmentAdmissionReceipt, material)
    assert receipt.receipt_digest == channel_attachment_receipt_digest(receipt)

    invalid = {**material, "expires_at": NOW.isoformat().replace("+00:00", "Z")}
    with pytest.raises(ValidationError, match="expire after acceptance"):
        _receipt(ChannelAttachmentAdmissionReceipt, invalid)


def test_commit_receipt_binds_received_document_and_content_digest() -> None:
    material = {
        "schema_version": "1.0.0",
        "receipt_kind": "commit",
        "handoff_id": HANDOFF_ID,
        "request_digest": REQUEST_DIGEST,
        "upload_id": str(UPLOAD_ID),
        "document_id": str(DOCUMENT_ID),
        "version_id": str(VERSION_ID),
        "observed_size": 12,
        "observed_sha256": "2" * 64,
        "state": "received",
        "committed_at": NOW.isoformat().replace("+00:00", "Z"),
        "execution_authority": False,
    }
    receipt = _receipt(ChannelAttachmentCommitReceipt, material)
    assert receipt.state is DocumentState.RECEIVED
    assert receipt.receipt_digest == channel_attachment_receipt_digest(receipt)


def test_terminal_ready_requires_exact_query_visible_citation() -> None:
    receipt = _receipt(ChannelAttachmentTerminalReceipt, _terminal_material())

    assert receipt.outcome is ChannelAttachmentOutcome.READY
    assert receipt.observed_sha256 == "2" * 64
    with pytest.raises(ValidationError, match="not query-visible"):
        _receipt(
            ChannelAttachmentTerminalReceipt,
            _terminal_material(index_state=DocumentIndexState.BUILDING.value),
        )
    with pytest.raises(ValidationError, match="not query-visible"):
        _receipt(
            ChannelAttachmentTerminalReceipt,
            _terminal_material(citation=f"doc:{DOCUMENT_ID}:{UPLOAD_ID}"),
        )


def test_handover_stays_pending_until_draft_projection_is_ready() -> None:
    pending = _receipt(
        ChannelAttachmentTerminalReceipt,
        _terminal_material(
            requested_purpose=DocumentPurpose.HANDOVER_BOOTSTRAP.value,
            outcome=ChannelAttachmentOutcome.PENDING.value,
            citation=None,
        ),
    )
    assert pending.outcome is ChannelAttachmentOutcome.PENDING

    ready = _receipt(
        ChannelAttachmentTerminalReceipt,
        _terminal_material(
            requested_purpose=DocumentPurpose.HANDOVER_BOOTSTRAP.value,
            handover_draft_ready=True,
        ),
    )
    assert ready.handover_draft_ready is True


def test_pending_and_rejected_receipts_cannot_smuggle_citations() -> None:
    with pytest.raises(ValidationError, match="cannot carry a result"):
        _receipt(
            ChannelAttachmentTerminalReceipt,
            _terminal_material(outcome="pending", document_state="extracting"),
        )
    rejected = _receipt(
        ChannelAttachmentTerminalReceipt,
        _terminal_material(
            outcome="rejected",
            document_state=DocumentState.HELD.value,
            index_state=DocumentIndexState.FAILED.value,
            active=False,
            available=False,
            citation=None,
            reason_code="document_held",
        ),
    )
    assert rejected.reason_code == "document_held"


def test_packaged_schemas_validate_request_and_receipt_models() -> None:
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    request = _request()
    terminal = _receipt(ChannelAttachmentTerminalReceipt, _terminal_material())

    validator.validate(
        "channel-attachment-admission",
        request.model_dump(mode="json"),
        version="1.0.0",
    )
    validator.validate(
        "channel-attachment-receipt",
        terminal.model_dump(mode="json"),
        version="1.0.0",
    )


def test_active_handoff_codecs_require_consumer_first_rollout() -> None:
    request_payload = _request().model_dump(mode="json")
    request_wire = CHANNEL_ATTACHMENT_ADMISSION_PRODUCER_V1.encode(request_payload)
    assert CHANNEL_ATTACHMENT_ADMISSION_CONSUMER_V1.decode(request_wire) == request_payload
    with pytest.raises(CompatibilityError, match="rejects version"):
        CHANNEL_ATTACHMENT_ADMISSION_CONSUMER_UNAVAILABLE.decode(request_wire)

    receipt_payload = _receipt(ChannelAttachmentTerminalReceipt, _terminal_material()).model_dump(
        mode="json"
    )
    receipt_wire = CHANNEL_ATTACHMENT_RECEIPT_PRODUCER_V1.encode(receipt_payload)
    assert CHANNEL_ATTACHMENT_RECEIPT_CONSUMER_V1.decode(receipt_wire) == receipt_payload
    with pytest.raises(CompatibilityError, match="rejects version"):
        CHANNEL_ATTACHMENT_RECEIPT_CONSUMER_UNAVAILABLE.decode(receipt_wire)
