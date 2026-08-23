"""Immutable operational promotion evidence source tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.measurement import (
    CausalPromotionReceipt,
    OperationalPromotionBatch,
    OperationalPromotionRecord,
    PromotionEvidenceCohort,
)
from fdai.delivery.measurement.operational_promotion_evidence import (
    ImmutableFileOperationalPromotionEvidenceSource,
    ManifestCausalPromotionReceiptVerifier,
    ManifestOperationalPromotionUnitVerifier,
    OperationalPromotionEvidenceManifest,
)
from fdai.shared.contracts.models import CausalEvidenceGrade

_REVISION = "a" * 40
_ACTION_DIGEST = "b" * 64


def _batch() -> OperationalPromotionBatch:
    causal = CausalPromotionReceipt(
        hypothesis_id="hypothesis-1",
        hypothesis_revision_digest="c" * 64,
        evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        status="supported",
    )
    record = OperationalPromotionRecord(
        sample_id="sample-1",
        measurement_unit_id="unit-1",
        audit_sequence=1,
        action_type_name="ops.scale-out",
        action_type_version="1.0.0",
        action_type_digest=_ACTION_DIGEST,
        fdai_revision=_REVISION,
        scenario_set_version="v2026.08",
        scenario_case_id="case-1",
        cohort=PromotionEvidenceCohort.LIVE_SHADOW,
        observed_at=datetime(2026, 8, 22, tzinfo=UTC),
        correct=True,
        policy_escape=False,
        executed=True,
        rolled_back=False,
        recurrence_window_complete=True,
        recurrence=False,
        causal_receipt=causal,
        simulation_requires_review=False,
        evidence_refs=(causal.content_digest, "d" * 64),
    )
    return OperationalPromotionBatch(
        fdai_revision=_REVISION,
        scenario_set_version="v2026.08",
        action_type_name="ops.scale-out",
        action_type_version="1.0.0",
        action_type_digest=_ACTION_DIGEST,
        sealed_at=datetime(2026, 8, 23, tzinfo=UTC),
        records=(record,),
    )


def _batch_mapping(batch: OperationalPromotionBatch) -> dict[str, object]:
    record = batch.records[0]
    causal = record.causal_receipt
    return {
        "schema_version": "1.0.0",
        "fdai_revision": batch.fdai_revision,
        "scenario_set_version": batch.scenario_set_version,
        "action_type_name": batch.action_type_name,
        "action_type_version": batch.action_type_version,
        "action_type_digest": batch.action_type_digest,
        "sealed_at": batch.sealed_at.isoformat(),
        "records": [
            {
                "sample_id": record.sample_id,
                "measurement_unit_id": record.measurement_unit_id,
                "audit_sequence": record.audit_sequence,
                "action_type_name": record.action_type_name,
                "action_type_version": record.action_type_version,
                "action_type_digest": record.action_type_digest,
                "fdai_revision": record.fdai_revision,
                "scenario_set_version": record.scenario_set_version,
                "scenario_case_id": record.scenario_case_id,
                "cohort": record.cohort.value,
                "observed_at": record.observed_at.isoformat(),
                "correct": record.correct,
                "policy_escape": record.policy_escape,
                "executed": record.executed,
                "rolled_back": record.rolled_back,
                "recurrence_window_complete": record.recurrence_window_complete,
                "recurrence": record.recurrence,
                "causal_receipt": {
                    "hypothesis_id": causal.hypothesis_id,
                    "hypothesis_revision_digest": causal.hypothesis_revision_digest,
                    "evidence_grade": causal.evidence_grade.value,
                    "status": causal.status,
                    "closure": causal.closure,
                },
                "simulation_requires_review": record.simulation_requires_review,
                "evidence_refs": list(record.evidence_refs),
            }
        ],
    }


def _write_manifest(tmp_path: Path, batch: OperationalPromotionBatch) -> Path:
    batch_path = tmp_path / "batch.json"
    batch_path.write_text(json.dumps(_batch_mapping(batch)), encoding="utf-8")
    causal_digest = batch.records[0].causal_receipt.content_digest
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "batches": [
                    {
                        "action_type_name": batch.action_type_name,
                        "path": batch_path.name,
                        "content_digest": batch.content_digest,
                    }
                ],
                "causal_receipt_digests": [causal_digest],
                "unit_evidence_refs": {
                    "unit-1": list(batch.records[0].evidence_refs),
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


async def test_exact_manifest_batch_and_verifiers_accept(tmp_path: Path) -> None:
    batch = _batch()
    manifest = OperationalPromotionEvidenceManifest.load(_write_manifest(tmp_path, batch))
    source = ImmutableFileOperationalPromotionEvidenceSource(manifest)

    loaded = await source.load_batch(
        action_type_name=batch.action_type_name,
        fdai_revision=batch.fdai_revision,
        scenario_set_version=batch.scenario_set_version,
    )

    assert loaded == batch
    assert ManifestCausalPromotionReceiptVerifier(manifest).verify(loaded.records[0].causal_receipt)
    assert ManifestOperationalPromotionUnitVerifier(manifest).verify(loaded.records[0])


async def test_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    batch = _batch()
    manifest_path = _write_manifest(tmp_path, batch)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["batches"][0]["content_digest"] = "e" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    source = ImmutableFileOperationalPromotionEvidenceSource(
        OperationalPromotionEvidenceManifest.load(manifest_path)
    )

    with pytest.raises(ValueError, match="batch digest mismatch"):
        await source.load_batch(
            action_type_name=batch.action_type_name,
            fdai_revision=batch.fdai_revision,
            scenario_set_version=batch.scenario_set_version,
        )


def test_batch_path_cannot_escape_manifest_directory(tmp_path: Path) -> None:
    batch = _batch()
    manifest_path = _write_manifest(tmp_path, batch)
    outside = tmp_path.parent / "outside-batch.json"
    outside.write_text(json.dumps(_batch_mapping(batch)), encoding="utf-8")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["batches"][0]["path"] = "../outside-batch.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="escapes its manifest directory"):
        OperationalPromotionEvidenceManifest.load(manifest_path)


def test_manifest_symlink_is_rejected(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, _batch())
    symlink_path = tmp_path / "manifest-link.json"
    symlink_path.symlink_to(manifest_path)

    with pytest.raises(ValueError, match="MUST be a regular file"):
        OperationalPromotionEvidenceManifest.load(symlink_path)


def test_manifest_over_byte_limit_is_rejected(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(b" " * (1024 * 1024 + 1))

    with pytest.raises(ValueError, match="exceeds its byte limit"):
        OperationalPromotionEvidenceManifest.load(manifest_path)


async def test_batch_symlink_replacement_is_rejected(tmp_path: Path) -> None:
    batch = _batch()
    manifest = OperationalPromotionEvidenceManifest.load(_write_manifest(tmp_path, batch))
    attestation = manifest.batches[0]
    replacement = tmp_path / "replacement.json"
    replacement.write_text(json.dumps(_batch_mapping(batch)), encoding="utf-8")
    attestation.path.unlink()
    attestation.path.symlink_to(replacement)

    with pytest.raises(ValueError, match="MUST be a regular file"):
        await ImmutableFileOperationalPromotionEvidenceSource(manifest).load_batch(
            action_type_name=batch.action_type_name,
            fdai_revision=batch.fdai_revision,
            scenario_set_version=batch.scenario_set_version,
        )


async def test_non_text_causal_closure_is_rejected(tmp_path: Path) -> None:
    batch = _batch()
    manifest_path = _write_manifest(tmp_path, batch)
    batch_path = tmp_path / "batch.json"
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    payload["records"][0]["causal_receipt"]["closure"] = 7
    batch_path.write_text(json.dumps(payload), encoding="utf-8")
    source = ImmutableFileOperationalPromotionEvidenceSource(
        OperationalPromotionEvidenceManifest.load(manifest_path)
    )

    with pytest.raises(ValueError, match="closure MUST be non-empty text or null"):
        await source.load_batch(
            action_type_name=batch.action_type_name,
            fdai_revision=batch.fdai_revision,
            scenario_set_version=batch.scenario_set_version,
        )
