from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.operational_context import (
    OperationalEvidenceMaterial,
    OperationalEvidenceReadRequest,
    OperationalEvidenceReadService,
)
from fdai.shared.contracts.models import Autonomy

NOW = datetime(2026, 8, 24, 1, tzinfo=UTC)
RELEASE = "sha256:" + "a" * 64


def _request() -> OperationalEvidenceReadRequest:
    return OperationalEvidenceReadRequest(
        ontology_release_digest=RELEASE,
        catalog_revision="catalog-r1",
        purpose="incident-review",
        scope=("resource-example",),
        cutoff=NOW,
    )


class _Source:
    def __init__(self, material: OperationalEvidenceMaterial | None = None) -> None:
        self.material = material

    async def collect(self, request: OperationalEvidenceReadRequest) -> OperationalEvidenceMaterial:
        return self.material or OperationalEvidenceMaterial(
            ontology_release_digest=request.ontology_release_digest,
            catalog_revision=request.catalog_revision,
            purpose=request.purpose,
            scope=request.scope,
            cutoff=request.cutoff,
        )


async def test_runtime_evidence_read_is_bounded_and_has_no_authority() -> None:
    result = await OperationalEvidenceReadService(
        source=_Source(),
        clock=lambda: NOW,
        max_items=8,
        max_bytes=16_384,
    ).read(_request())

    assert result.execution_authority is False
    assert result.mutation_authority is False
    assert result.bundle.autonomy_ceiling is Autonomy.SHADOW_ONLY
    assert result.bundle.ontology_release_digest == RELEASE
    assert result.bundle.max_items == 8
    assert result.bundle.max_bytes == 16_384


async def test_runtime_evidence_read_rejects_source_identity_drift() -> None:
    request = _request()
    source = _Source(
        replace(
            await _Source().collect(request),
            purpose="different-purpose",
        )
    )

    with pytest.raises(ValueError, match="source identity"):
        await OperationalEvidenceReadService(source=source, clock=lambda: NOW).read(request)
