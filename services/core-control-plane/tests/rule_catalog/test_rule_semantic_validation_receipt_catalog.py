from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    CohortMetric,
    SurfaceValidationReceipt,
    ValidationDecision,
)
from fdai.rule_catalog.schema.rule_semantic_validation_receipt_catalog import (
    SemanticValidationReceiptCatalogError,
    load_semantic_validation_receipts,
)

_A = "sha256:" + "a" * 64
_B = "sha256:" + "b" * 64


def _receipt() -> SurfaceValidationReceipt:
    return SurfaceValidationReceipt(
        surface_digest=_A,
        generation_digest=_B,
        catalog_digest=_A,
        dataset_digest=_B,
        evaluator_ref="heimdall:test@1",
        evaluation_policy_digest=_A,
        training_query_digests=(_A,),
        evaluation_query_digests=(_B,),
        cohort_metrics=(
            CohortMetric(
                cohort="en-exact",
                metric="recall-at-5",
                value=1.0,
                sample_count=1,
            ),
        ),
        failure_codes=(),
        decision=ValidationDecision.PASS,
    )


def _payload(receipt: SurfaceValidationReceipt) -> dict[str, object]:
    return {
        "schema_version": receipt.schema_version,
        "surface_digest": receipt.surface_digest,
        "generation_digest": receipt.generation_digest,
        "catalog_digest": receipt.catalog_digest,
        "dataset_digest": receipt.dataset_digest,
        "evaluator_ref": receipt.evaluator_ref,
        "evaluation_policy_digest": receipt.evaluation_policy_digest,
        "training_query_digests": list(receipt.training_query_digests),
        "evaluation_query_digests": list(receipt.evaluation_query_digests),
        "cohort_metrics": [
            {
                "cohort": item.cohort,
                "metric": item.metric,
                "value": item.value,
                "sample_count": item.sample_count,
            }
            for item in receipt.cohort_metrics
        ],
        "failure_codes": list(receipt.failure_codes),
        "decision": receipt.decision.value,
        "validation_authority": receipt.validation_authority,
    }


def _write(root: Path, name: str, payload: object) -> None:
    (root / name).write_text(json.dumps(payload), encoding="utf-8")


def test_receipt_loads_from_its_content_address(tmp_path: Path) -> None:
    receipt = _receipt()
    _write(tmp_path, f"{receipt.digest.removeprefix('sha256:')}.json", _payload(receipt))

    loaded = load_semantic_validation_receipts(tmp_path)

    assert loaded == {receipt.digest: receipt}


def test_receipt_catalog_rejects_wrong_content_address(tmp_path: Path) -> None:
    receipt = _receipt()
    _write(tmp_path, f"{'0' * 64}.json", _payload(receipt))

    with pytest.raises(SemanticValidationReceiptCatalogError, match="filename does not match"):
        load_semantic_validation_receipts(tmp_path)


@pytest.mark.parametrize("artifact_kind", ("symlink", "fifo"))
def test_receipt_catalog_rejects_non_regular_artifacts(
    tmp_path: Path,
    artifact_kind: str,
) -> None:
    artifact = tmp_path / f"{'0' * 64}.json"
    if artifact_kind == "symlink":
        target = tmp_path / "target"
        target.write_text("{}", encoding="utf-8")
        artifact.symlink_to(target)
    else:
        os.mkfifo(artifact)

    with pytest.raises(SemanticValidationReceiptCatalogError, match="regular file"):
        load_semantic_validation_receipts(tmp_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("decision", "hold", "pass"),
        ("validation_authority", "promotion", "validation_only"),
        ("unexpected", True, "Additional properties"),
    ),
)
def test_receipt_catalog_rejects_nonpassing_authority_or_extra_fields(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    receipt = _receipt()
    payload = _payload(receipt)
    payload[field] = value
    _write(tmp_path, f"{receipt.digest.removeprefix('sha256:')}.json", payload)

    with pytest.raises(SemanticValidationReceiptCatalogError, match=message):
        load_semantic_validation_receipts(tmp_path)
