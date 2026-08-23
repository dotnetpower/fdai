"""Verified immutable-file evidence source for operational promotion measurement."""

from __future__ import annotations

import asyncio
import json
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fdai.core.measurement import (
    CausalPromotionReceipt,
    OperationalPromotionBatch,
    OperationalPromotionRecord,
    PromotionEvidenceCohort,
)
from fdai.shared.contracts.models import CausalEvidenceGrade

_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_BATCH_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class OperationalPromotionBatchAttestation:
    """Expected immutable identity for one mounted promotion batch."""

    action_type_name: str
    path: Path
    content_digest: str


@dataclass(frozen=True, slots=True)
class OperationalPromotionEvidenceManifest:
    """Deployment-reviewed evidence bounds used by source and verifiers."""

    batches: tuple[OperationalPromotionBatchAttestation, ...]
    causal_receipt_digests: frozenset[str]
    unit_evidence_refs: Mapping[str, frozenset[str]]

    @classmethod
    def load(cls, path: Path) -> OperationalPromotionEvidenceManifest:
        """Load one strict manifest without accepting inline evidence records."""
        raw = _object(json.loads(_read_bounded_regular_file(path, _MAX_MANIFEST_BYTES)), "manifest")
        _exact_fields(
            raw,
            {"schema_version", "batches", "causal_receipt_digests", "unit_evidence_refs"},
            "manifest",
        )
        if raw["schema_version"] != "1.0.0":
            raise ValueError("unsupported operational promotion evidence manifest")
        base = path.parent.resolve(strict=True)
        batches = tuple(
            OperationalPromotionBatchAttestation(
                action_type_name=_text(item, "action_type_name"),
                path=_bounded_batch_path(base, _text(item, "path")),
                content_digest=_digest_text(item, "content_digest"),
            )
            for item in _object_list(raw["batches"], "batches")
        )
        if len({item.action_type_name for item in batches}) != len(batches):
            raise ValueError("operational promotion manifest ActionTypes MUST be unique")
        causal = frozenset(_digest_value(item) for item in _list(raw, "causal_receipt_digests"))
        units_raw = _object(raw["unit_evidence_refs"], "unit_evidence_refs")
        units = {
            unit_id: frozenset(_digest_value(item) for item in _list_value(refs, unit_id))
            for unit_id, refs in units_raw.items()
        }
        if not batches or not causal or not units or any(not refs for refs in units.values()):
            raise ValueError("operational promotion evidence manifest MUST be complete")
        return cls(
            batches=batches,
            causal_receipt_digests=causal,
            unit_evidence_refs=units,
        )

    @property
    def action_type_names(self) -> frozenset[str]:
        return frozenset(item.action_type_name for item in self.batches)


class ImmutableFileOperationalPromotionEvidenceSource:
    """Load only exact-digest batches declared by a reviewed manifest."""

    def __init__(self, manifest: OperationalPromotionEvidenceManifest) -> None:
        self._batches = {item.action_type_name: item for item in manifest.batches}

    async def load_batch(
        self,
        *,
        action_type_name: str,
        fdai_revision: str,
        scenario_set_version: str,
    ) -> OperationalPromotionBatch:
        attestation = self._batches.get(action_type_name)
        if attestation is None:
            raise ValueError("operational promotion ActionType is not attested")
        text = await asyncio.to_thread(
            _read_bounded_regular_file,
            attestation.path,
            _MAX_BATCH_BYTES,
        )
        batch = _decode_batch(json.loads(text))
        if batch.content_digest != attestation.content_digest:
            raise ValueError("operational promotion batch digest mismatch")
        if batch.fdai_revision != fdai_revision:
            raise ValueError("operational promotion batch revision mismatch")
        if batch.scenario_set_version != scenario_set_version:
            raise ValueError("operational promotion batch scenario mismatch")
        if batch.action_type_name != action_type_name:
            raise ValueError("operational promotion batch ActionType mismatch")
        return batch


class ManifestCausalPromotionReceiptVerifier:
    """Accept only causal receipts content-addressed by the reviewed manifest."""

    def __init__(self, manifest: OperationalPromotionEvidenceManifest) -> None:
        self._allowed = manifest.causal_receipt_digests

    def verify(self, receipt: CausalPromotionReceipt) -> bool:
        return receipt.content_digest in self._allowed


class ManifestOperationalPromotionUnitVerifier:
    """Accept only exact evidence references assigned to a measurement unit."""

    def __init__(self, manifest: OperationalPromotionEvidenceManifest) -> None:
        self._allowed = dict(manifest.unit_evidence_refs)

    def verify(self, record: OperationalPromotionRecord) -> bool:
        expected = self._allowed.get(record.measurement_unit_id)
        return expected is not None and frozenset(record.evidence_refs) == expected


def _decode_batch(value: object) -> OperationalPromotionBatch:
    raw = _object(value, "batch")
    _exact_fields(
        raw,
        {
            "schema_version",
            "fdai_revision",
            "scenario_set_version",
            "action_type_name",
            "action_type_version",
            "action_type_digest",
            "sealed_at",
            "records",
        },
        "batch",
    )
    if raw["schema_version"] != "1.0.0":
        raise ValueError("unsupported operational promotion batch schema")
    records = tuple(_decode_record(item) for item in _object_list(raw["records"], "records"))
    return OperationalPromotionBatch(
        fdai_revision=_text(raw, "fdai_revision"),
        scenario_set_version=_text(raw, "scenario_set_version"),
        action_type_name=_text(raw, "action_type_name"),
        action_type_version=_text(raw, "action_type_version"),
        action_type_digest=_digest_text(raw, "action_type_digest"),
        sealed_at=_timestamp(raw, "sealed_at"),
        records=records,
    )


def _decode_record(value: object) -> OperationalPromotionRecord:
    raw = _object(value, "record")
    _exact_fields(
        raw,
        {
            "sample_id",
            "measurement_unit_id",
            "audit_sequence",
            "action_type_name",
            "action_type_version",
            "action_type_digest",
            "fdai_revision",
            "scenario_set_version",
            "scenario_case_id",
            "cohort",
            "observed_at",
            "correct",
            "policy_escape",
            "executed",
            "rolled_back",
            "recurrence_window_complete",
            "recurrence",
            "causal_receipt",
            "simulation_requires_review",
            "evidence_refs",
        },
        "record",
    )
    causal_raw = _object(raw["causal_receipt"], "causal_receipt")
    _exact_fields(
        causal_raw,
        {"hypothesis_id", "hypothesis_revision_digest", "evidence_grade", "status", "closure"},
        "causal_receipt",
    )
    causal = CausalPromotionReceipt(
        hypothesis_id=_text(causal_raw, "hypothesis_id"),
        hypothesis_revision_digest=_digest_text(causal_raw, "hypothesis_revision_digest"),
        evidence_grade=CausalEvidenceGrade(_text(causal_raw, "evidence_grade")),
        status=_text(causal_raw, "status"),
        closure=_optional_text(causal_raw, "closure"),
    )
    return OperationalPromotionRecord(
        sample_id=_text(raw, "sample_id"),
        measurement_unit_id=_text(raw, "measurement_unit_id"),
        audit_sequence=_integer(raw, "audit_sequence"),
        action_type_name=_text(raw, "action_type_name"),
        action_type_version=_text(raw, "action_type_version"),
        action_type_digest=_digest_text(raw, "action_type_digest"),
        fdai_revision=_text(raw, "fdai_revision"),
        scenario_set_version=_text(raw, "scenario_set_version"),
        scenario_case_id=_text(raw, "scenario_case_id"),
        cohort=PromotionEvidenceCohort(_text(raw, "cohort")),
        observed_at=_timestamp(raw, "observed_at"),
        correct=_boolean(raw, "correct"),
        policy_escape=_boolean(raw, "policy_escape"),
        executed=_boolean(raw, "executed"),
        rolled_back=_boolean(raw, "rolled_back"),
        recurrence_window_complete=_boolean(raw, "recurrence_window_complete"),
        recurrence=_boolean(raw, "recurrence"),
        causal_receipt=causal,
        simulation_requires_review=_boolean(raw, "simulation_requires_review"),
        evidence_refs=tuple(_digest_value(item) for item in _list(raw, "evidence_refs")),
    )


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"operational promotion {name} MUST be an object")
    return value


def _bounded_batch_path(base: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError("operational promotion batch path MUST be relative to its manifest")
    resolved = (base / candidate).resolve(strict=True)
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError("operational promotion batch path escapes its manifest directory") from exc
    return resolved


def _read_bounded_regular_file(path: Path, max_bytes: int) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("operational promotion evidence MUST be a regular file") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("operational promotion evidence MUST be a regular file")
        if metadata.st_size > max_bytes:
            raise ValueError("operational promotion evidence exceeds its byte limit")
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            descriptor = -1
            text = stream.read(max_bytes + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(text.encode("utf-8")) > max_bytes:
        raise ValueError("operational promotion evidence exceeds its byte limit")
    return text


def _exact_fields(raw: Mapping[str, Any], expected: set[str], name: str) -> None:
    if set(raw) != expected:
        raise ValueError(f"operational promotion {name} fields do not match schema")


def _text(raw: Mapping[str, Any], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"operational promotion {name} MUST be non-empty text")
    return value


def _optional_text(raw: Mapping[str, Any], name: str) -> str | None:
    value = raw.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"operational promotion {name} MUST be non-empty text or null")
    return value


def _digest_text(raw: Mapping[str, Any], name: str) -> str:
    return _digest_value(_text(raw, name))


def _digest_value(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("operational promotion digest MUST be lowercase SHA-256")
    return value


def _integer(raw: Mapping[str, Any], name: str) -> int:
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"operational promotion {name} MUST be an integer")
    return value


def _boolean(raw: Mapping[str, Any], name: str) -> bool:
    value = raw.get(name)
    if not isinstance(value, bool):
        raise ValueError(f"operational promotion {name} MUST be boolean")
    return value


def _timestamp(raw: Mapping[str, Any], name: str) -> datetime:
    value = _text(raw, name)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"operational promotion {name} MUST be timezone-aware")
    return parsed


def _list(raw: Mapping[str, Any], name: str) -> list[object]:
    return _list_value(raw.get(name), name)


def _list_value(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"operational promotion {name} MUST be an array")
    return value


def _object_list(value: object, name: str) -> tuple[dict[str, Any], ...]:
    return tuple(_object(item, name) for item in _list_value(value, name))


__all__ = [
    "ImmutableFileOperationalPromotionEvidenceSource",
    "ManifestCausalPromotionReceiptVerifier",
    "ManifestOperationalPromotionUnitVerifier",
    "OperationalPromotionBatchAttestation",
    "OperationalPromotionEvidenceManifest",
]
