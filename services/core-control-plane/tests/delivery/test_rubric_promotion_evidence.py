from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.delivery.measurement.rubric_promotion_evidence import (
    ImmutableFileRubricPromotionReceiptSource,
    ManifestRubricPromotionReceiptVerifier,
    RubricPromotionEvidenceManifest,
)

from tests.core.quality_gate.test_rubric_promotion import _receipt


def _write_manifest(path: Path, *, digest: str | None = None) -> None:
    receipt = _receipt()
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "receipts": [
                    {
                        "receipt": receipt.as_json(),
                        "receipt_digest": digest or receipt.content_digest,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_manifest_source_and_verifier_share_exact_receipt(tmp_path: Path) -> None:
    path = tmp_path / "rubric-promotion.json"
    _write_manifest(path)

    manifest = RubricPromotionEvidenceManifest.load(path)
    source = ImmutableFileRubricPromotionReceiptSource(manifest)
    verifier = ManifestRubricPromotionReceiptVerifier(manifest)
    receipt = source.current("ops.restart-service")

    assert receipt is not None
    assert verifier.verify(receipt) is True
    assert source.current("ops.unknown") is None


def test_manifest_rejects_digest_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "rubric-promotion.json"
    _write_manifest(path, digest="f" * 64)

    with pytest.raises(ValueError, match="digest mismatch"):
        RubricPromotionEvidenceManifest.load(path)


def test_manifest_rejects_unknown_receipt_fields(tmp_path: Path) -> None:
    receipt = _receipt()
    value = receipt.as_json()
    value["unexpected"] = True
    path = tmp_path / "rubric-promotion.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "receipts": [{"receipt": value, "receipt_digest": receipt.content_digest}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="receipt shape is invalid"):
        RubricPromotionEvidenceManifest.load(path)
