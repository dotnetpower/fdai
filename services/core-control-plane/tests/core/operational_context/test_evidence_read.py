from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.ontology_platform.functions import FunctionInvocationContext
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
from fdai.core.ontology_platform.query_receipt_authority import SecuredQueryReceiptAuthority
from fdai.core.operational_context import (
    AuthenticatedPrincipalContext,
    OperationalContextSnapshot,
    OperationalEvidenceMaterial,
    OperationalEvidenceReadRequest,
    OperationalEvidenceReadService,
)
from fdai.core.operational_context.evidence_bundle_identity import bind_evidence_item_source
from fdai.core.operational_context.evidence_bundle_models import CatalogEvidenceItem
from fdai.core.operational_context.evidence_bundle_sources import (
    EvidenceTemporalScope,
    VerifiedEvidenceSourceReceipt,
)
from fdai.core.operational_context.evidence_read import _serialized_response_size
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


def _authenticated_context(
    result: SecuredObjectSetQueryResult | None = None,
) -> AuthenticatedPrincipalContext:
    authority = SecuredQueryReceiptAuthority()
    if result is not None:
        authority.issue(result)
        evidence_refs = (result.receipt.projected_result_digest,)
    else:
        evidence_refs = ()
    return AuthenticatedPrincipalContext(
        principal_ref=PRINCIPAL,
        principal_scope_digest=PRINCIPAL_SCOPE,
        purpose="incident-review",
        receipt_authority=authority,
        invocation_context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role="reader",
            purposes=("incident-review",),
            evidence_refs=evidence_refs,
        ),
        verification_context=authority.verification_context,
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


def _catalog_item(index: int) -> CatalogEvidenceItem:
    catalog_ref = f"rule:example-{index}@1"
    source = VerifiedEvidenceSourceReceipt.create(
        ontology_release_digest=RELEASE,
        catalog_revision="catalog-r1",
        document_revision=None,
        source_identity="catalog-as-code",
        source_revision=f"catalog-item-{index}",
        authenticated_source="principal:catalog-as-code",
        content_digest="sha256:" + "2" * 64,
        purpose="incident-review",
        scope=("resource-example",),
        redaction_summary=("metadata_only",),
        temporal_scope=EvidenceTemporalScope(
            effective_from=NOW,
            effective_to=None,
            evidence_cutoff=NOW,
            recorded_at=NOW,
        ),
        freshness_ceiling_seconds=60,
        completeness=1.0,
        synthetic=False,
        conflicts=(),
        verification_method="deterministic-validator",
        verifier_identity="evidence-verifier",
        verification_receipt_ref=f"verification:catalog-item-{index}",
    )
    return bind_evidence_item_source(
        CatalogEvidenceItem(
            evidence_ref=f"catalog:rule:example-{index}",
            source=source,
            catalog_ref=catalog_ref,
        ),
        membership_evidence={"catalog_ref": catalog_ref},
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
    assert result.bundle.max_bytes < 16_384
    assert _serialized_response_size(result.bundle, result.context_metadata) <= 16_384


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
    ).read(
        _request(),
        authenticated_context=_authenticated_context(_secured_context()),
    )

    assert result.principal_ref == PRINCIPAL
    assert result.context_metadata is not None
    assert result.context_metadata["principal_ref"] == PRINCIPAL
    assert result.context_metadata["complete"] is True


async def test_runtime_evidence_read_bounds_bundle_and_context_response_together() -> None:
    request = _request()
    source = _Source(
        replace(
            await _Source().collect(request),
            context_snapshot=_context_snapshot(),
            secured_context_result=_secured_context(),
        )
    )

    result = await OperationalEvidenceReadService(
        source=source,
        clock=lambda: NOW,
        max_bytes=1_280,
    ).read(request, authenticated_context=_authenticated_context(_secured_context()))

    assert _serialized_response_size(result.bundle, result.context_metadata) <= 1_280


async def test_runtime_evidence_read_reserves_context_bytes_before_bundle_truncation() -> None:
    request = _request()
    secured = _secured_context()
    source = _Source(
        replace(
            await _Source().collect(request),
            catalog=tuple(_catalog_item(index) for index in range(128)),
            context_snapshot=_context_snapshot(),
            secured_context_result=secured,
        )
    )

    result = await OperationalEvidenceReadService(
        source=source,
        clock=lambda: NOW,
        max_bytes=16_384,
    ).read(request, authenticated_context=_authenticated_context(secured))

    assert result.bundle.max_bytes < 16_384
    assert result.bundle.used_items < 128
    assert "context_budget_truncated" in result.bundle.hold_reasons
    assert _serialized_response_size(result.bundle, result.context_metadata) <= 16_384


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
