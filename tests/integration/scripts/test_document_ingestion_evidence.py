"""Content-free governed document lifecycle evidence tests."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from scripts.evaluation.document_ingestion_evidence import (
    DocumentEvidenceError,
    main,
    summarize_evidence,
)


def _receipt() -> dict[str, object]:
    stages = (
        "upload",
        "scan",
        "protection_inspection",
        "extraction",
        "indexing",
        "citation",
        "deletion",
        "restart",
        "provider_failure",
    )
    observations = [
        {
            "stage": stage,
            "latency_ms": index * 10,
            "queue_delay_ms": index,
            "storage_bytes": index * 100,
            "outcome": "failure" if stage == "provider_failure" else "success",
            "document_ref": "receipt-document-1",
        }
        for index, stage in enumerate(stages, start=1)
    ]
    observations.append(
        {
            "stage": "upload",
            "latency_ms": 1000,
            "queue_delay_ms": 100,
            "storage_bytes": 1500,
            "outcome": "success",
            "document_ref": "receipt-document-2",
        }
    )
    return {
        "schema_version": "1.0.0",
        "revision": "a" * 40,
        "corpus_reviewed": True,
        "contains_sensitive_data": False,
        "window_seconds": 10,
        "services": [
            "core-control-plane",
            "document-ingestion-api",
            "document-processing-worker",
            "isolated-executor",
            "operator-service",
        ],
        "observations": observations,
    }


def test_summarizes_required_baselines_with_nearest_rank_percentiles() -> None:
    summary = summarize_evidence(_receipt())

    assert summary["service_count"] == 5
    assert summary["observation_count"] == 10
    assert summary["storage_growth_bytes"] == 1400
    assert summary["failure_rate"] == 0.1
    assert summary["throughput_documents_per_second"] == 0.1
    upload = summary["stage_latency"]["upload"]  # type: ignore[index]
    assert upload == {"p50_ms": 10.0, "p95_ms": 1000.0, "samples": 2}


def test_rejects_nonfinite_throughput_from_a_finite_window() -> None:
    receipt = _receipt()
    receipt["window_seconds"] = 5e-324

    with pytest.raises(DocumentEvidenceError, match="throughput.*finite"):
        summarize_evidence(receipt)


def test_keeps_small_windows_when_the_derived_rate_is_finite() -> None:
    receipt = _receipt()
    receipt["window_seconds"] = 1e-300

    summary = summarize_evidence(receipt)

    assert summary["throughput_documents_per_second"] == pytest.approx(1e300)
    json.dumps(summary, allow_nan=False)


@pytest.mark.parametrize("field", ["window_seconds", "latency_ms", "queue_delay_ms"])
def test_rejects_unrepresentable_numeric_values_as_typed_evidence_errors(field: str) -> None:
    receipt = _receipt()
    if field == "window_seconds":
        receipt[field] = 10**400
    else:
        observations = receipt["observations"]
        assert isinstance(observations, list)
        observations[0][field] = 10**400

    with pytest.raises(DocumentEvidenceError, match=f"{field}.*finite"):
        summarize_evidence(receipt)


@pytest.mark.parametrize("window_seconds", [5e-324, 10**400])
def test_cli_rejects_numeric_overflow_without_publishing_or_overwriting(
    window_seconds: float | int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt = _receipt()
    receipt["window_seconds"] = window_seconds
    input_path = tmp_path / "receipt.json"
    output_path = tmp_path / "summary.json"
    input_path.write_text(json.dumps(receipt), encoding="utf-8")
    output_path.write_text("retained-report", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["evidence", str(input_path), "--output", str(output_path)])

    with pytest.raises(SystemExit, match="document evidence validation failed:.*finite"):
        main()

    assert output_path.read_text(encoding="utf-8") == "retained-report"
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("corpus_reviewed", False, "independent review"),
        ("contains_sensitive_data", True, "non-sensitive"),
        ("services", ["document-ingestion-api"], "five-service"),
    ],
)
def test_rejects_evidence_without_governed_corpus_or_topology(
    field: str, value: object, message: str
) -> None:
    receipt = _receipt()
    receipt[field] = value

    with pytest.raises(DocumentEvidenceError, match=message):
        summarize_evidence(receipt)


def test_rejects_missing_lifecycle_stage() -> None:
    receipt = _receipt()
    observations = receipt["observations"]
    assert isinstance(observations, list)
    receipt["observations"] = [
        observation for observation in observations if observation["stage"] != "deletion"
    ]

    with pytest.raises(DocumentEvidenceError, match="missing stages: deletion"):
        summarize_evidence(receipt)


def test_rejects_document_content_at_any_depth() -> None:
    receipt = deepcopy(_receipt())
    observations = receipt["observations"]
    assert isinstance(observations, list)
    observations[0]["details"] = {"document_text": "not allowed"}

    with pytest.raises(DocumentEvidenceError, match="document_text"):
        summarize_evidence(receipt)


def test_requires_an_explicit_provider_failure_observation() -> None:
    receipt = _receipt()
    observations = receipt["observations"]
    assert isinstance(observations, list)
    for observation in observations:
        if observation["stage"] == "provider_failure":
            observation["outcome"] = "success"

    with pytest.raises(DocumentEvidenceError, match="explicit failure"):
        summarize_evidence(receipt)
