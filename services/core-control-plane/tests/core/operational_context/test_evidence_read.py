from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
)
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.core.operational_context import (
    AuthenticatedPrincipalContext,
    OperationalContextSnapshot,
    OperationalEvidenceMaterial,
    OperationalEvidenceReadRequest,
    OperationalEvidenceReadService,
)
from fdai.shared.contracts.models import Autonomy, OntologyReleaseRef
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord

NOW = datetime(2026, 8, 24, 1, tzinfo=UTC)
RELEASE = "sha256:" + "a" * 64
PRINCIPAL = "principal-example"
PRINCIPAL_SCOPE = "sha256:" + "c" * 64


def _request() -> OperationalEvidenceReadRequest:
    return OperationalEvidenceReadRequest(
        ontology_release_digest=RELEASE,
        catalog_revision="catalog-r1",
        purpose="incident-review",
        scope=("resource-example",),
        cutoff=NOW,
    )


def _authenticated_context() -> AuthenticatedPrincipalContext:
    return AuthenticatedPrincipalContext(
        principal_ref=PRINCIPAL,
        principal_scope_digest=PRINCIPAL_SCOPE,
        purpose="incident-review",
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


def _secured_context() -> SecuredObjectSetQueryResult:
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="incident-review",
        limit=8,
    )
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(
            objects=(
                OntologyObjectRecord(
                    id="resource-example",
                    object_type="Resource",
                    properties={"id": "resource-example"},
                ),
            ),
        ),
        concrete_types=("Resource",),
        truncated=False,
    )
    return SecuredObjectSetQueryResult(
        materialization=materialization,
        receipt=SecuredObjectSetQueryReceipt(
            ontology_release=OntologyReleaseRef(digest=RELEASE),
            projected_result_digest=_projected_result_digest(materialization),
            purpose="incident-review",
            caller_role="reader",
            principal_scope_digest=PRINCIPAL_SCOPE,
            observation_cutoff=NOW,
            as_of_skew_seconds=0,
            returned_object_count=1,
            returned_link_count=0,
            complete=True,
            truncated=False,
            redactions=ObjectSetRedactionSummary(
                objects_with_redactions=0,
                redacted_identity_count=0,
                access_scope_count=0,
                purpose_binding_count=0,
                undeclared_property_count=0,
                links_with_redactions=0,
                redacted_link_property_count=0,
                removed_link_count=0,
            ),
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
        )


async def test_runtime_evidence_read_is_bounded_and_has_no_authority() -> None:
    result = await OperationalEvidenceReadService(
        source=_Source(),
        clock=lambda: NOW,
        max_items=8,
        max_bytes=16_384,
    ).read(_request(), authenticated_context=_authenticated_context())

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
    ).read(_request(), authenticated_context=_authenticated_context())

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
        await OperationalEvidenceReadService(source=source, clock=lambda: NOW).read(
            request,
            authenticated_context=_authenticated_context(),
        )
