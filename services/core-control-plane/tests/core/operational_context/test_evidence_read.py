from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fdai.core.operational_context import (
    OperationalContextSnapshot,
    OperationalEvidenceMaterial,
    OperationalEvidenceReadRequest,
    OperationalEvidenceReadService,
)
from fdai.shared.contracts.models import Autonomy

NOW = datetime(2026, 8, 24, 1, tzinfo=UTC)
RELEASE = "sha256:" + "a" * 64
PRINCIPAL = "principal-example"


def _request() -> OperationalEvidenceReadRequest:
    return OperationalEvidenceReadRequest(
        ontology_release_digest=RELEASE,
        catalog_revision="catalog-r1",
        purpose="incident-review",
        scope=("resource-example",),
        cutoff=NOW,
        principal_ref=PRINCIPAL,
    )


def _context_snapshot() -> OperationalContextSnapshot:
    return OperationalContextSnapshot(
        snapshot_id="context-example",
        target_resource_id="resource-example",
        cutoff=NOW,
        recorded_at=NOW,
        catalog_versions=(("ontology", RELEASE),),
        service_ids=(),
        workload_ids=(),
        objective_ids=(),
        service_objective_ids=(),
        recovery_objective_ids=(),
        cost_objective_ids=(),
        constraint_ids=(),
        ownership_ids=(),
        dependency_ids=(),
        source_freshness=(),
        evidence_links=(),
        evidence_paths=(),
        temporal_exclusions=(),
        stale_sources=(),
        conflicts=(),
        autonomy_ceiling=Autonomy.ENFORCE_AUTO,
    )


def _secured_context() -> object:
    return SimpleNamespace(
        receipt=SimpleNamespace(
            principal_ref=PRINCIPAL,
            ontology_release=SimpleNamespace(digest=RELEASE),
            projected_result_digest="sha256:" + "b" * 64,
            purpose="incident-review",
            observation_cutoff=NOW,
            complete=True,
            truncated=False,
            truncation_reason=None,
            execution_authority=False,
        ),
        materialization=SimpleNamespace(
            graph=SimpleNamespace(objects=(), links=()),
        ),
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
            principal_ref=request.principal_ref,
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


async def test_runtime_evidence_read_binds_receipt_verified_context_metadata() -> None:
    source = _Source(
        replace(
            await _Source().collect(_request()),
            context_snapshot=_context_snapshot(),
            secured_context_result=_secured_context(),
        )
    )

    result = await OperationalEvidenceReadService(
        source=source,
        clock=lambda: NOW,
    ).read(_request())

    assert result.principal_ref == PRINCIPAL
    assert result.context_metadata is not None
    assert result.context_metadata["principal_ref"] == PRINCIPAL
    assert result.context_metadata["complete"] is True


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
