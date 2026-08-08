"""Tests for diagnostic mechanism ontology projection."""

from __future__ import annotations

import pytest
from fdai.core.ontology_platform.diagnostic_projection import (
    build_diagnostic_catalog_projection,
)


def _mechanism(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "id": "kubernetes_missing_dependency_reducer",
        "status": "semantic_generalized",
        "source_commits": ["a" * 40],
        "benchmark_measured": True,
        "semantic_generalized": True,
        "operationalized": False,
        "provider_validated": True,
        "action_validated": False,
        "outcome_validated": False,
        "azure_validated": True,
    }
    record.update(overrides)
    return record


def test_projects_mechanism_and_independent_validation_axes() -> None:
    projection = build_diagnostic_catalog_projection([_mechanism()], benchmark_id="sregym")

    assert len(projection.objects) == 8
    assert len(projection.links) == 7
    mechanism = projection.objects[0]
    assert mechanism.id == "diagnostic-mechanism:kubernetes_missing_dependency_reducer"
    assert mechanism.properties["provider_validated"] is True
    assert mechanism.properties["operationalized"] is False
    receipts = {
        item.properties["validation_axis"]: item
        for item in projection.objects
        if item.object_type == "BenchmarkValidation"
    }
    assert receipts["azure_validated"].properties["passed"] is True
    assert receipts["operationalized"].properties["passed"] is False
    assert all(item.id.startswith("benchmark-validation:") for item in receipts.values())
    assert {item.link_type for item in projection.links} == {"mechanism_validated_by"}


def test_preserves_available_provider_evidence_in_content_addressed_receipt() -> None:
    projection = build_diagnostic_catalog_projection(
        [
            _mechanism(
                provider_validation_kind="live",
                provider_validation_evidence="Bounded positive and negative provider drill.",
            )
        ],
        benchmark_id="sregym",
    )

    receipt = next(
        item
        for item in projection.objects
        if item.object_type == "BenchmarkValidation"
        and item.properties["validation_axis"] == "provider_validated"
    )
    assert receipt.properties["validation_kind"] == "live"
    assert receipt.properties["evidence_summary"].startswith("Bounded positive")
    assert receipt.properties["evidence_digest"].startswith("sha256:")


def test_preserves_rejected_mechanism_hardening_as_negative_knowledge() -> None:
    projection = build_diagnostic_catalog_projection(
        [
            _mechanism(
                id="kubernetes_webhook_fail_open_recovery_seed",
                status="rejected",
                semantic_generalized=False,
                provider_validated=False,
                azure_validated=False,
                source_hardening="Fail-open recovery would widen mutation authority.",
            )
        ],
        benchmark_id="sregym",
    )

    assert projection.objects[0].properties["status"] == "rejected"
    assert "widen mutation authority" in projection.objects[0].properties["source_hardening"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"source_commits": []}, "source_commits"),
        ({"source_commits": ["z" * 40]}, "source_commits"),
        ({"provider_validated": "yes"}, "provider_validated"),
    ],
)
def test_rejects_incomplete_mechanism_provenance(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_diagnostic_catalog_projection(
            [_mechanism(**overrides)],
            benchmark_id="sregym",
        )


def test_rejects_duplicate_mechanism_identity() -> None:
    with pytest.raises(ValueError, match="duplicate diagnostic mechanism"):
        build_diagnostic_catalog_projection(
            [_mechanism(), _mechanism()],
            benchmark_id="sregym",
        )
