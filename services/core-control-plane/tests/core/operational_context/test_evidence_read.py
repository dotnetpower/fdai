from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

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
from fdai.core.ontology_platform.query_receipt_authority import (
    SecuredQueryReceiptAuthority,
    secured_query_scope_digest,
)
from fdai.core.operational_context import (
    AuthenticatedPrincipalContext,
    OperationalContextSnapshot,
    OperationalEvidenceMaterial,
    OperationalEvidenceReadRequest,
    OperationalEvidenceReadService,
)
from fdai.core.operational_context.evidence_bundle import build_operational_evidence_bundle
from fdai.core.operational_context.evidence_bundle_identity import (
    bind_evidence_item_source,
    bundle_body,
)
from fdai.core.operational_context.evidence_bundle_models import (
    CatalogEvidenceItem,
    OperationalEvidenceBundle,
    canonical_json,
)
from fdai.core.operational_context.evidence_bundle_sources import (
    EvidenceTemporalScope,
    VerifiedEvidenceSourceReceipt,
)
from fdai.core.operational_context.evidence_read import (
    _response_overhead,
    _serialized_response_size,
)
from fdai.shared.contracts.models import Autonomy, OntologyReleaseRef
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
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
    authority = SecuredQueryReceiptAuthority(now=lambda: NOW)
    if result is not None:
        authority.issue(
            result,
            DecisionEvidenceAdmission(
                receipt_digest="sha256:" + "d" * 64,
                verification_bundle_digest="sha256:" + "e" * 64,
                evidence_digest=result.receipt.projected_result_digest,
                scope_digest=secured_query_scope_digest(result.receipt),
                purpose_id=result.receipt.purpose,
                source_revision=result.receipt.ontology_release.digest,
                verified_at=NOW - timedelta(minutes=1),
                valid_until=NOW + timedelta(minutes=1),
            ),
        )
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
        catalog_versions=(("ontology", RELEASE), ("catalog", "catalog-r1")),
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
    assert (
        _serialized_response_size(
            result.bundle, result.context_metadata, principal_ref=result.principal_ref
        )
        <= 16_384
    )


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


async def test_runtime_evidence_read_rejects_context_snapshot_cutoff_drift() -> None:
    request = _request()
    drifted_snapshot = replace(_context_snapshot(), cutoff=NOW.replace(hour=2))
    source = _Source(
        replace(
            await _Source().collect(request),
            context_snapshot=drifted_snapshot,
            secured_context_result=_secured_context(),
        )
    )

    with pytest.raises(ValueError, match="context snapshot cutoff"):
        await OperationalEvidenceReadService(source=source, clock=lambda: NOW).read(
            request,
            authenticated_context=_authenticated_context(_secured_context()),
        )


async def test_runtime_evidence_read_rejects_context_snapshot_release_drift() -> None:
    request = _request()
    drifted_snapshot = replace(
        _context_snapshot(),
        catalog_versions=(("ontology", "sha256:" + "9" * 64), ("catalog", "catalog-r1")),
    )
    source = _Source(
        replace(
            await _Source().collect(request),
            context_snapshot=drifted_snapshot,
            secured_context_result=_secured_context(),
        )
    )

    with pytest.raises(ValueError, match="context snapshot release"):
        await OperationalEvidenceReadService(source=source, clock=lambda: NOW).read(
            request,
            authenticated_context=_authenticated_context(_secured_context()),
        )


async def test_runtime_evidence_read_rejects_context_snapshot_catalog_revision_drift() -> None:
    request = _request()
    drifted_snapshot = replace(
        _context_snapshot(),
        catalog_versions=(("ontology", RELEASE), ("catalog", "catalog-r2")),
    )
    source = _Source(
        replace(
            await _Source().collect(request),
            context_snapshot=drifted_snapshot,
            secured_context_result=_secured_context(),
        )
    )

    with pytest.raises(ValueError, match="context snapshot catalog revision"):
        await OperationalEvidenceReadService(source=source, clock=lambda: NOW).read(
            request,
            authenticated_context=_authenticated_context(_secured_context()),
        )


async def test_runtime_evidence_read_rejects_context_snapshot_missing_catalog_revision() -> None:
    request = _request()
    drifted_snapshot = replace(
        _context_snapshot(),
        catalog_versions=(("ontology", RELEASE),),
    )
    source = _Source(
        replace(
            await _Source().collect(request),
            context_snapshot=drifted_snapshot,
            secured_context_result=_secured_context(),
        )
    )

    with pytest.raises(ValueError, match="context snapshot catalog revision"):
        await OperationalEvidenceReadService(source=source, clock=lambda: NOW).read(
            request,
            authenticated_context=_authenticated_context(_secured_context()),
        )


async def test_runtime_evidence_read_rejects_context_snapshot_target_outside_scope() -> None:
    request = _request()
    drifted_snapshot = replace(_context_snapshot(), target_resource_id="other-resource")
    source = _Source(
        replace(
            await _Source().collect(request),
            context_snapshot=drifted_snapshot,
            secured_context_result=_secured_context(),
        )
    )

    with pytest.raises(ValueError, match="context snapshot target"):
        await OperationalEvidenceReadService(source=source, clock=lambda: NOW).read(
            request,
            authenticated_context=_authenticated_context(_secured_context()),
        )


async def test_runtime_evidence_read_rejects_secured_receipt_release_drift() -> None:
    request = _request()
    secured = _secured_context()
    drifted_secured = secured.model_copy(
        update={
            "receipt": secured.receipt.model_copy(
                update={"ontology_release": OntologyReleaseRef(digest="sha256:" + "9" * 64)}
            )
        }
    )
    source = _Source(
        replace(
            await _Source().collect(request),
            context_snapshot=_context_snapshot(),
            secured_context_result=drifted_secured,
        )
    )

    with pytest.raises(ValueError, match="secured Context receipt release"):
        await OperationalEvidenceReadService(source=source, clock=lambda: NOW).read(
            request,
            authenticated_context=_authenticated_context(secured),
        )


async def test_runtime_evidence_read_rejects_secured_receipt_cutoff_drift() -> None:
    request = _request()
    secured = _secured_context()
    drifted_secured = secured.model_copy(
        update={
            "receipt": secured.receipt.model_copy(
                update={"observation_cutoff": NOW.replace(hour=2)}
            )
        }
    )
    source = _Source(
        replace(
            await _Source().collect(request),
            context_snapshot=_context_snapshot(),
            secured_context_result=drifted_secured,
        )
    )

    with pytest.raises(ValueError, match="secured Context receipt cutoff"):
        await OperationalEvidenceReadService(source=source, clock=lambda: NOW).read(
            request,
            authenticated_context=_authenticated_context(secured),
        )


def test_response_overhead_reserves_bytes_for_principal_and_authority_fields() -> None:
    short_overhead = _response_overhead(None, principal_ref="p")
    long_overhead = _response_overhead(None, principal_ref="p" * 11)

    assert long_overhead - short_overhead == 10
    assert short_overhead > len('"principal_ref":"p"')


def _empty_bundle() -> OperationalEvidenceBundle:
    return build_operational_evidence_bundle(
        cutoff=NOW,
        trusted_recorded_at=NOW,
        ontology_release_digest=RELEASE,
        catalog_revision="catalog-r1",
        purpose="incident-review",
        scope=("resource-example",),
        claims=(),
        max_items=8,
        max_bytes=16_384,
        autonomy_ceiling=Autonomy.SHADOW_ONLY,
    )


def _expected_response_body(
    bundle: OperationalEvidenceBundle, context_metadata: object, principal_ref: str
) -> dict[str, object]:
    return {
        "bundle": bundle_body(
            cutoff=bundle.cutoff,
            trusted_recorded_at=bundle.trusted_recorded_at,
            ontology_release_digest=bundle.ontology_release_digest,
            catalog_revision=bundle.catalog_revision,
            purpose=bundle.purpose,
            scope=bundle.scope,
            claims=bundle.claims,
            ontology=bundle.ontology,
            state=bundle.state,
            catalog=bundle.catalog,
            documents=bundle.documents,
            citation_manifest=bundle.citation_manifest,
            conflicts=bundle.conflicts,
            missing_paths=bundle.missing_paths,
            evidence_issues=bundle.evidence_issues,
            hold_reasons=bundle.hold_reasons,
            max_items=bundle.max_items,
            max_bytes=bundle.max_bytes,
            used_items=bundle.used_items,
            used_bytes=bundle.used_bytes,
            autonomy_ceiling=bundle.autonomy_ceiling,
        ),
        "bundle_id": bundle.bundle_id,
        "digest": bundle.digest,
        "context_metadata": context_metadata,
        "principal_ref": principal_ref,
        "execution_authority": False,
        "mutation_authority": False,
    }


def test_serialized_response_size_includes_actual_bundle_id_and_digest() -> None:
    bundle = _empty_bundle()

    expected = len(canonical_json(_expected_response_body(bundle, None, PRINCIPAL)).encode("utf-8"))
    without_identity = len(
        canonical_json(
            {
                k: v
                for k, v in _expected_response_body(bundle, None, PRINCIPAL).items()
                if k not in ("bundle_id", "digest")
            }
        ).encode("utf-8")
    )

    assert _serialized_response_size(bundle, None, principal_ref=PRINCIPAL) == expected
    # Omitting bundle_id/digest would have silently undercounted every response by their bytes.
    assert expected > without_identity


def test_response_overhead_reserves_exact_bytes_for_bundle_identity_fields() -> None:
    bundle = _empty_bundle()

    # bundle_id/digest are fixed-length SHA-256 identifiers, so the placeholder-based overhead
    # reserved before the real bundle exists must equal the overhead computed from real values.
    placeholder_overhead = _response_overhead(None, principal_ref=PRINCIPAL)
    real_identity_overhead = len(
        canonical_json(
            {
                "bundle": {},
                "bundle_id": bundle.bundle_id,
                "digest": bundle.digest,
                "context_metadata": None,
                "principal_ref": PRINCIPAL,
                "execution_authority": False,
                "mutation_authority": False,
            }
        ).encode("utf-8")
    ) - len(canonical_json({}).encode("utf-8"))

    assert placeholder_overhead == real_identity_overhead


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
        max_bytes=2_048,
    ).read(request, authenticated_context=_authenticated_context(_secured_context()))

    assert (
        _serialized_response_size(
            result.bundle, result.context_metadata, principal_ref=result.principal_ref
        )
        <= 2_048
    )


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
    assert (
        _serialized_response_size(
            result.bundle, result.context_metadata, principal_ref=result.principal_ref
        )
        <= 16_384
    )


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
