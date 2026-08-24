"""Strict immutable-file source for governed rubric promotion receipts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from fdai.core.quality_gate.promotion import RubricPromotionReceipt

_SCHEMA_VERSION = "1.0.0"
_MAX_RECEIPTS = 1_000
_MAX_FILE_BYTES = 4 * 1024 * 1024
_RECEIPT_FIELDS = frozenset(field.name for field in fields(RubricPromotionReceipt))


@dataclass(frozen=True, slots=True)
class RubricPromotionReceiptAttestation:
    receipt: RubricPromotionReceipt
    receipt_digest: str

    def __post_init__(self) -> None:
        if self.receipt_digest != self.receipt.content_digest:
            raise ValueError("rubric promotion receipt digest mismatch")


@dataclass(frozen=True, slots=True)
class RubricPromotionEvidenceManifest:
    receipts: tuple[RubricPromotionReceiptAttestation, ...]

    def __post_init__(self) -> None:
        if len(self.receipts) > _MAX_RECEIPTS:
            raise ValueError("rubric promotion manifest exceeds its receipt limit")
        action_types = [item.receipt.action_type_name for item in self.receipts]
        if len(set(action_types)) != len(action_types):
            raise ValueError("rubric promotion manifest ActionTypes MUST be unique")

    @classmethod
    def load(cls, path: Path) -> RubricPromotionEvidenceManifest:
        if path.stat().st_size > _MAX_FILE_BYTES:
            raise ValueError("rubric promotion manifest exceeds its size limit")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or set(raw) != {"schema_version", "receipts"}:
            raise ValueError("rubric promotion manifest shape is invalid")
        if raw["schema_version"] != _SCHEMA_VERSION:
            raise ValueError("rubric promotion manifest schema version is unsupported")
        items = raw["receipts"]
        if not isinstance(items, list) or len(items) > _MAX_RECEIPTS:
            raise ValueError("rubric promotion manifest receipts are invalid")
        return cls(receipts=tuple(_decode_attestation(item) for item in items))


class ImmutableFileRubricPromotionReceiptSource:
    """Expose the exact manifest receipt selected for each ActionType."""

    def __init__(self, manifest: RubricPromotionEvidenceManifest) -> None:
        self._receipts = {item.receipt.action_type_name: item.receipt for item in manifest.receipts}

    def current(self, action_type_name: str) -> RubricPromotionReceipt | None:
        return self._receipts.get(action_type_name)


class ManifestRubricPromotionReceiptVerifier:
    """Accept only receipts whose complete digest is attested by the manifest."""

    def __init__(self, manifest: RubricPromotionEvidenceManifest) -> None:
        self._digests = {
            item.receipt.action_type_name: item.receipt_digest for item in manifest.receipts
        }

    def verify(self, receipt: RubricPromotionReceipt) -> bool:
        return self._digests.get(receipt.action_type_name) == receipt.content_digest


def _decode_attestation(value: object) -> RubricPromotionReceiptAttestation:
    if not isinstance(value, dict) or set(value) != {"receipt", "receipt_digest"}:
        raise ValueError("rubric promotion receipt attestation shape is invalid")
    receipt_digest = value["receipt_digest"]
    if not isinstance(receipt_digest, str):
        raise ValueError("rubric promotion receipt digest MUST be a string")
    return RubricPromotionReceiptAttestation(
        receipt=_decode_receipt(value["receipt"]),
        receipt_digest=receipt_digest,
    )


def _decode_receipt(value: object) -> RubricPromotionReceipt:
    if not isinstance(value, Mapping) or set(value) != _RECEIPT_FIELDS:
        raise ValueError("rubric promotion receipt shape is invalid")
    decoded: dict[str, Any] = dict(value)
    decoded["gaps"] = _string_tuple(decoded["gaps"], field_name="gaps")
    for name in (
        "baseline_catch_ci",
        "treatment_catch_ci",
        "baseline_false_positive_ci",
        "treatment_false_positive_ci",
    ):
        decoded[name] = _float_pair(decoded[name], field_name=name)
    for name in ("sealed_at", "reviewed_at", "expires_at"):
        decoded[name] = _datetime(decoded[name], field_name=name)
    return RubricPromotionReceipt(**decoded)


def _string_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"rubric promotion receipt {field_name} MUST be a string list")
    return tuple(value)


def _float_pair(value: object, *, field_name: str) -> tuple[float, float]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(not isinstance(item, (int, float)) or isinstance(item, bool) for item in value)
    ):
        raise ValueError(f"rubric promotion receipt {field_name} MUST be a numeric pair")
    return float(value[0]), float(value[1])


def _datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"rubric promotion receipt {field_name} MUST be an RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"rubric promotion receipt {field_name} MUST be an RFC 3339 string"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError(f"rubric promotion receipt {field_name} MUST include a timezone")
    return parsed


__all__ = [
    "ImmutableFileRubricPromotionReceiptSource",
    "ManifestRubricPromotionReceiptVerifier",
    "RubricPromotionEvidenceManifest",
    "RubricPromotionReceiptAttestation",
]
