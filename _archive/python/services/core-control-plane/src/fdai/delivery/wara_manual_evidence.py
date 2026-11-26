"""Admit signed manual WARA evidence from explicitly trusted deployment sources."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from dataclasses import fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from fdai.core.wara.models import WaraAssessmentRequest, WaraEvidenceReceipt
from fdai.rule_catalog.schema.wara_assessment import WaraAssessmentCatalog, canonical_digest

_MAXIMUM_BYTES = 1_048_576
_RECEIPT_ADAPTER = TypeAdapter(WaraEvidenceReceipt)


class WaraManualTrustBinding(BaseModel):
    """A deployment-installed public key, not authority supplied by an evidence file."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    key_id: str = Field(min_length=1, max_length=128)
    producer: str = Field(min_length=1, max_length=128)
    public_key_base64: str = Field(min_length=1, max_length=128)
    workload_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    valid_from: datetime
    valid_until: datetime
    revoked: bool = False


class _TrustFile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: str
    bindings: tuple[WaraManualTrustBinding, ...] = Field(min_length=1, max_length=64)


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key_id: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any]
    signature_base64: str = Field(min_length=1, max_length=128)


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: str
    producer: str
    workload_id: str
    scope_digest: str
    framework_revision: str
    crosswalk_digest: str
    ontology_release: str
    inventory_generation: str
    receipts: tuple[dict[str, Any], ...] = Field(max_length=393)


def manual_evidence_signing_bytes(key_id: str, payload: dict[str, Any]) -> bytes:
    """Return the exact canonical material signed by the authorized evidence producer."""

    return json.dumps(
        {"key_id": key_id, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _read_bounded(path: Path) -> bytes:
    with path.open("rb") as stream:
        body = stream.read(_MAXIMUM_BYTES + 1)
    if len(body) > _MAXIMUM_BYTES:
        raise ValueError("WARA manual evidence file exceeds the byte limit")
    return body


class SignedWaraManualEvidenceSource:
    """Read signed, exact-scope receipts without granting execution or approval authority."""

    def __init__(self, *, evidence_file: Path, trust_file: Path) -> None:
        self._evidence_file = evidence_file
        self._trust_file = trust_file

    async def read(
        self, request: WaraAssessmentRequest, catalog: WaraAssessmentCatalog
    ) -> tuple[WaraEvidenceReceipt, ...]:
        try:
            body, trust_body = await asyncio.gather(
                asyncio.to_thread(_read_bounded, self._evidence_file),
                asyncio.to_thread(_read_bounded, self._trust_file),
            )
        except OSError as exc:
            raise ValueError("WARA manual evidence source could not be read") from exc
        return admit_signed_manual_evidence(
            body, trust_body=trust_body, request=request, catalog=catalog
        )


def admit_signed_manual_evidence(
    body: bytes,
    *,
    trust_body: bytes,
    request: WaraAssessmentRequest,
    catalog: WaraAssessmentCatalog,
) -> tuple[WaraEvidenceReceipt, ...]:
    """Verify source authenticity and pins before normal runtime evidence qualification."""

    if len(body) > _MAXIMUM_BYTES or len(trust_body) > _MAXIMUM_BYTES:
        raise ValueError("WARA manual evidence input exceeds the byte limit")
    try:
        envelope = _Envelope.model_validate_json(body)
        trust = _TrustFile.model_validate_json(trust_body)
        payload = _Payload.model_validate_json(json.dumps(envelope.payload))
    except ValueError as exc:
        raise ValueError("WARA manual evidence or trust schema is invalid") from exc
    if trust.schema_version != "1.0.0" or payload.schema_version != "1.0.0":
        raise ValueError("WARA manual evidence schema version is unsupported")
    key_ids = [binding.key_id for binding in trust.bindings]
    if len(key_ids) != len(set(key_ids)):
        raise ValueError("WARA manual evidence trust key identities are duplicated")
    binding = next((item for item in trust.bindings if item.key_id == envelope.key_id), None)
    if binding is None or binding.revoked:
        raise ValueError("WARA manual evidence signing key is not trusted")
    if (
        binding.valid_from.tzinfo is None
        or binding.valid_until.tzinfo is None
        or not binding.valid_from <= request.evaluated_at <= binding.valid_until
        or request.workload_id not in binding.workload_ids
        or payload.producer != binding.producer
    ):
        raise ValueError("WARA manual evidence producer is not authorized for this scope")
    try:
        key_bytes = base64.b64decode(binding.public_key_base64, validate=True)
        signature = base64.b64decode(envelope.signature_base64, validate=True)
        Ed25519PublicKey.from_public_bytes(key_bytes).verify(
            signature, manual_evidence_signing_bytes(envelope.key_id, envelope.payload)
        )
    except (ValueError, binascii.Error, InvalidSignature) as exc:
        raise ValueError("WARA manual evidence signature is invalid") from exc
    expected_pins = (
        request.workload_id,
        request.scope_digest,
        request.framework_revision,
        request.crosswalk_digest,
        request.ontology_release,
        request.inventory_generation,
    )
    if (
        payload.workload_id,
        payload.scope_digest,
        payload.framework_revision,
        payload.crosswalk_digest,
        payload.ontology_release,
        payload.inventory_generation,
    ) != expected_pins:
        raise ValueError("WARA manual evidence does not match the current assessment")
    records = {record.aprl_guid: record for record in catalog.recommendations}
    allowed_fields = {item.name for item in fields(WaraEvidenceReceipt)}
    receipts: list[WaraEvidenceReceipt] = []
    seen: set[str] = set()
    attestation_digest = canonical_digest(
        {
            "key_id": envelope.key_id,
            "payload": envelope.payload,
            "trust_binding": binding.model_dump(mode="json"),
        }
    )
    for raw in payload.receipts:
        if set(raw) - allowed_fields:
            raise ValueError("WARA manual evidence receipt contains unsupported fields")
        try:
            receipt = _RECEIPT_ADAPTER.validate_json(json.dumps(raw), strict=True)
        except ValueError as exc:
            raise ValueError("WARA manual evidence receipt schema is invalid") from exc
        record = records.get(receipt.recommendation_id)
        if (
            record is None
            or record.manual_evidence is None
            or receipt.producer != binding.producer
            or receipt.producer != record.manual_evidence.authoritative_producer
            or receipt.evidence_kind != record.manual_evidence.kind
            or receipt.scope_digest != request.scope_digest
            or receipt.source_revision != request.framework_revision
            or receipt.inventory_generation != request.inventory_generation
            or receipt.recommendation_id in seen
        ):
            raise ValueError("WARA manual evidence receipt is outside its producer contract")
        seen.add(receipt.recommendation_id)
        # Retain the signed artifact identity; the referenced evidence remains independently hashed.
        receipts.append(
            replace(
                receipt,
                evidence_ref=f"wara-manual:{attestation_digest}#{receipt.recommendation_id}",
            )
        )
    return tuple(sorted(receipts, key=lambda item: item.recommendation_id))


__all__ = [
    "SignedWaraManualEvidenceSource",
    "WaraManualTrustBinding",
    "admit_signed_manual_evidence",
    "manual_evidence_signing_bytes",
]
