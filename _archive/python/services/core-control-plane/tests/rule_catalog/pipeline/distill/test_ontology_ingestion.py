"""Tests for the governed envelope-to-ontology provenance bridge."""

from __future__ import annotations

from uuid import UUID

import pytest
from fdai.rule_catalog.pipeline.distill.ontology_ingestion import (
    manual_document_from_envelope,
)
from fdai.shared.contracts import (
    DocumentEnvelope,
    DocumentPurpose,
    ProtectionState,
    StructuralUnit,
)


def _envelope(
    *,
    units: tuple[StructuralUnit, ...] | None = None,
    protection: ProtectionState = ProtectionState.NONE,
) -> DocumentEnvelope:
    return DocumentEnvelope(
        document_id=UUID(int=1),
        version_id=UUID(int=2),
        source_sha256="a" * 64,
        media_type="application/pdf",
        observed_format="pdf",
        size_bytes=100,
        collection_id="collection-a",
        purposes=(DocumentPurpose.MANUAL_DISTILLATION,),
        protection_state=protection,
        access_descriptor_ref="access:manuals",
        units=units
        or (
            StructuralUnit(
                unit_id="page-1-block-1",
                kind="page",
                locator="pdf/page:1/block:1",
                text="Checkout service is owned by Platform team.",
            ),
        ),
        extractor_name="stdlib-safe",
        extractor_version="1.1.0",
    )


def test_bridge_preserves_structural_locator_and_source_lineage() -> None:
    document = manual_document_from_envelope(_envelope())

    assert document.text == "Checkout service is owned by Platform team."
    assert document.source_ref.endswith("/versions/00000000-0000-0000-0000-000000000002")
    assert document.metadata["source_sha256"] == "a" * 64
    assert document.line_provenance[0].line_number == 1
    assert document.line_provenance[0].source_format == "pdf"
    assert document.line_provenance[0].unit_id == "page-1-block-1"
    assert document.line_provenance[0].locator == "pdf/page:1/block:1"


@pytest.mark.parametrize("duplicate", ("unit_id", "locator"))
def test_bridge_rejects_ambiguous_structural_identity(duplicate: str) -> None:
    first = _envelope().units[0]
    second = StructuralUnit(
        unit_id=first.unit_id if duplicate == "unit_id" else "page-1-block-2",
        kind="page",
        locator=first.locator if duplicate == "locator" else "pdf/page:1/block:2",
        text="Checkout service depends on Billing service.",
    )

    with pytest.raises(ValueError, match="MUST be unique"):
        manual_document_from_envelope(_envelope(units=(first, second)))


def test_bridge_rejects_nonextractable_protection_and_empty_text() -> None:
    with pytest.raises(ValueError, match="extractable"):
        manual_document_from_envelope(_envelope(protection=ProtectionState.PASSWORD_ENCRYPTED))
    with pytest.raises(ValueError, match="at least one"):
        manual_document_from_envelope(
            _envelope(
                units=(
                    StructuralUnit(
                        unit_id="empty",
                        kind="page",
                        locator="pdf/page:1/block:1",
                        text=" \n ",
                    ),
                )
            )
        )
