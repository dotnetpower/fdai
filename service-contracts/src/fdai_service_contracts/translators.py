"""Explicit lossless compatibility translators for additive service envelopes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.compatibility import CompatibilityError


def operator_core_request_1_1_to_1_0(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Drop the optional 1.1 context digest for a Core 1.0 consumer."""

    return _project(
        payload,
        (
            "schema_version",
            "request_id",
            "correlation_id",
            "idempotency_key",
            "resource_ref",
            "request_kind",
            "requested_at",
        ),
    )


def core_operator_projection_1_1_to_1_0(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Drop the optional 1.1 evidence digest for an Operator 1.0 consumer."""

    return _project(
        payload,
        (
            "schema_version",
            "projection_id",
            "request_id",
            "correlation_id",
            "idempotency_key",
            "status",
            "recorded_at",
            "payload",
        ),
    )


def document_ingestion_activity_1_1_to_1_0(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Drop the optional 1.1 record digest for a document Worker 1.0 consumer."""

    return _project(
        payload,
        (
            "schema_version",
            "activity_id",
            "upload_id",
            "document_id",
            "idempotency_key",
            "sequence",
            "action",
            "occurred_at",
            "record",
        ),
    )


def _project(payload: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise CompatibilityError(f"translator input is missing required fields: {missing}")
    projected = {field: payload[field] for field in fields}
    projected["schema_version"] = "1.0.0"
    return projected


__all__ = [
    "core_operator_projection_1_1_to_1_0",
    "document_ingestion_activity_1_1_to_1_0",
    "operator_core_request_1_1_to_1_0",
]
