"""Version and rolling-upgrade compatibility for document worker messages."""

from __future__ import annotations

from typing import Any

import pytest

from fdai.shared.contracts import DocumentWorkerAuditEvent, DocumentWorkerIndexCommand
from fdai.shared.contracts.compatibility import check_schema_compatibility
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator

_UPLOAD_ID = "00000000-0000-0000-0000-000000000501"


def _legacy_audit_payload() -> dict[str, object]:
    return {
        "producer_principal": "Saga",
        "kind": "document_ingestion",
        "audited_topic": "object.verdict",
        "stage": "received",
        "decision": "admit",
        "upload_id": _UPLOAD_ID,
    }


def _legacy_index_payload() -> dict[str, object]:
    return {
        "producer_principal": "Muninn",
        "kind": "document_ingestion",
        "stage": "indexing",
        "command": "index",
        "upload_id": _UPLOAD_ID,
    }


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (DocumentWorkerAuditEvent, _legacy_audit_payload()),
        (DocumentWorkerIndexCommand, _legacy_index_payload()),
    ],
)
def test_new_consumer_accepts_legacy_producer_without_schema_version(
    model: Any,
    payload: dict[str, object],
) -> None:
    parsed = model.model_validate(payload)

    assert parsed.schema_version == "1.0.0"


@pytest.mark.parametrize(
    ("schema_name", "model", "payload"),
    [
        ("document-worker-audit", DocumentWorkerAuditEvent, _legacy_audit_payload()),
        ("document-worker-index", DocumentWorkerIndexCommand, _legacy_index_payload()),
    ],
)
def test_new_producer_payload_validates_and_remains_readable_by_legacy_consumer(
    schema_name: str,
    model: Any,
    payload: dict[str, object],
) -> None:
    produced = model.model_validate(payload).model_dump(mode="json")
    JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(schema_name, produced)

    assert produced["schema_version"] == "1.0.0"
    assert produced["kind"] == "document_ingestion"
    assert produced["upload_id"] == _UPLOAD_ID


@pytest.mark.parametrize("schema_name", ["document-worker-audit", "document-worker-index"])
def test_schema_version_field_is_an_additive_legacy_schema_change(schema_name: str) -> None:
    current = dict(PackageResourceSchemaRegistry().get(schema_name))
    current_properties = dict(current["properties"])
    current["properties"] = current_properties
    legacy = dict(current)
    legacy_properties = dict(current_properties)
    legacy_properties.pop("schema_version")
    legacy["properties"] = legacy_properties

    assert check_schema_compatibility(legacy, current).is_compatible


def test_worker_contract_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        DocumentWorkerIndexCommand.model_validate(
            {**_legacy_index_payload(), "untrusted_operation": "delete"}
        )


def test_worker_contract_rejects_unsupported_schema_version() -> None:
    with pytest.raises(ValueError):
        DocumentWorkerAuditEvent.model_validate(
            {**_legacy_audit_payload(), "schema_version": "2.0.0"}
        )
