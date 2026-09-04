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
    ObjectSetTruncationReason,
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
from fdai.core.operational_context import AuthenticatedPrincipalContext
from fdai.core.operational_context.console_projection import project_context_snapshot
from fdai.core.operational_context.models import (
    OperationalContextEvidenceLink,
    OperationalContextEvidencePath,
    OperationalContextSnapshot,
    SourceFreshness,
)
from fdai.shared.contracts.models import Autonomy, OntologyReleaseRef
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

CUTOFF = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
PRINCIPAL = "principal-example"
PRINCIPAL_SCOPE = "sha256:" + "c" * 64

# The secured object's own `source_ref` property that a bound path's
# `provenance_refs` MUST equal (see project_context_snapshot's provenance
# binding check). Keyed by the same fixture ids used across this module.
_PROVENANCE_REF_BY_OBJECT_ID: dict[str, str] = {
    "resource-example": "inventory-generation:example",
    "workload-example": "service-catalog:example",
}


def _snapshot() -> OperationalContextSnapshot:
    link = OperationalContextEvidenceLink(
        link_type="workload_runs_on",
        from_id="workload-example",
        to_id="resource-example",
    )
    return OperationalContextSnapshot(
        snapshot_id="context-example",
        target_resource_id="resource-example",
        cutoff=CUTOFF,
        recorded_at=CUTOFF,
        catalog_versions=(("ontology", DIGEST),),
        service_ids=(),
        workload_ids=("workload-example",),
        objective_ids=(),
        service_objective_ids=(),
        recovery_objective_ids=(),
        cost_objective_ids=(),
        constraint_ids=(),
        ownership_ids=(),
        dependency_ids=("workload-example",),
        source_freshness=(
            SourceFreshness(source="inventory", observed_at=CUTOFF, max_age_seconds=300),
        ),
        evidence_links=(link,),
        evidence_paths=(
            OperationalContextEvidencePath(
                object_id="resource-example",
                object_type="Resource",
                revision=2,
                effective_from=None,
                effective_to=None,
                provenance_refs=("inventory-generation:example",),
                links=(),
            ),
            OperationalContextEvidencePath(
                object_id="workload-example",
                object_type="Workload",
                revision=1,
                effective_from=None,
                effective_to=None,
                provenance_refs=("service-catalog:example",),
                links=(link,),
            ),
        ),
        temporal_exclusions=(),
        stale_sources=(),
        conflicts=(),
        autonomy_ceiling=Autonomy.ENFORCE_AUTO,
    )


def _secured_result(
    *,
    principal_scope_digest: str | None = PRINCIPAL_SCOPE,
    release_digest: str = DIGEST,
    cutoff: datetime = CUTOFF,
    complete: bool = True,
    truncated: bool = False,
    object_ids: tuple[str, ...] = ("resource-example", "workload-example"),
    source_complete: bool = True,
) -> SecuredObjectSetQueryResult:
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=cutoff,
        purpose="operator_context",
        limit=100,
    )
    objects = tuple(
        OntologyObjectRecord(
            id=item,
            object_type="Workload" if item == "workload-example" else "Resource",
            properties={
                "id": item,
                "source_ref": _PROVENANCE_REF_BY_OBJECT_ID.get(item, ""),
            },
            revision=2 if item == "resource-example" else 1,
        )
        for item in object_ids
    )
    links = (
        OntologyLinkRecord(
            link_type="workload_runs_on",
            from_id="workload-example",
            to_id="resource-example",
        ),
    )
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(
            objects=objects,
            links=links,
            truncated=truncated,
            source_complete=source_complete,
        ),
        concrete_types=("Resource", "Workload"),
        truncated=truncated,
        truncation_reason=ObjectSetTruncationReason.RESULT_LIMIT if truncated else None,
    )
    return SecuredObjectSetQueryResult(
        materialization=materialization,
        receipt=SecuredObjectSetQueryReceipt(
            ontology_release=OntologyReleaseRef(digest=release_digest),
            projected_result_digest=_projected_result_digest(materialization),
            purpose="operator_context",
            caller_role="reader",
            principal_scope_digest=principal_scope_digest,
            observation_cutoff=cutoff,
            as_of_skew_seconds=0,
            returned_object_count=len(objects),
            returned_link_count=len(links),
            source_complete=source_complete,
            complete=complete and not truncated,
            truncated=truncated,
            truncation_reason=ObjectSetTruncationReason.RESULT_LIMIT if truncated else None,
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


def _authenticated_context(
    result: SecuredObjectSetQueryResult,
) -> AuthenticatedPrincipalContext:
    authority = SecuredQueryReceiptAuthority(now=lambda: CUTOFF)
    authority.issue(
        result,
        DecisionEvidenceAdmission(
            receipt_digest="sha256:" + "d" * 64,
            verification_bundle_digest="sha256:" + "e" * 64,
            evidence_digest=result.receipt.projected_result_digest,
            scope_digest=secured_query_scope_digest(result.receipt),
            purpose_id=result.receipt.purpose,
            source_revision=result.receipt.ontology_release.digest,
            verified_at=CUTOFF - timedelta(minutes=1),
            valid_until=CUTOFF + timedelta(minutes=1),
        ),
    )
    invocation = FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role="reader",
        purposes=("operator_context",),
        evidence_refs=(result.receipt.projected_result_digest,),
    )
    return AuthenticatedPrincipalContext(
        principal_ref=PRINCIPAL,
        principal_scope_digest=PRINCIPAL_SCOPE,
        purpose="operator_context",
        receipt_authority=authority,
        invocation_context=invocation,
        verification_context=authority.verification_context,
    )


def _link_metadata(*, source_revision: str) -> LinkObservationMetadata:
    return LinkObservationMetadata(
        state_fact=StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.PROVIDER,
            source_identity="inventory-provider",
            source_revision=source_revision,
            effective_at=CUTOFF,
            recorded_at=CUTOFF,
            evidence_cutoff=CUTOFF,
            freshness_ceiling_seconds=300,
            completeness=1.0,
            synthetic=False,
            evidence_refs=("inventory-observation",),
        ),
        verification_method="provider-readback",
        verified=True,
        verifier_identity="inventory-verifier",
        verifier_revision="verifier-r1",
        verification_receipt_ref="verification-receipt-r1",
        inventory_generation="inventory-generation-r1",
        mapping_id="mapping-r1",
        mapping_revision="mapping-revision-r1",
        source_schema_version="2026-08-27",
        source_schema_digest="sha256:" + "e" * 64,
    )


def test_projects_bounded_context_from_matching_secured_receipt() -> None:
    secured_result = _secured_result()
    projection = project_context_snapshot(
        snapshot=_snapshot(),
        secured_result=secured_result,
        authenticated_context=_authenticated_context(secured_result),
    )

    assert projection["ontology_release_digest"] == DIGEST
    assert projection["query_result_digest"] == secured_result.receipt.projected_result_digest
    assert projection["complete"] is True
    assert projection["mutation_authority"] is False
    assert projection["execution_authority"] is False
    assert projection["object_count"] == 2
    assert projection["link_count"] == 1
    assert projection["workload_ids"] == ["workload-example"]
    assert projection["dependency_ids"] == ["workload-example"]
    assert projection["ownership_ids"] == []
    assert projection["semantic_coverage"] == {
        "services": 0,
        "workloads": 1,
        "objectives": 0,
        "constraints": 0,
        "ownership": 0,
        "dependencies": 1,
    }
    assert projection["evidence_paths"][1]["revision"] == 1
    assert "properties" not in projection["evidence_paths"][1]
    assert projection["evidence_paths"][0]["provenance_refs"] == ["inventory-generation:example"]
    assert projection["evidence_paths"][1]["provenance_refs"] == ["service-catalog:example"]


def test_rejects_context_identity_missing_from_secured_result() -> None:
    snapshot = replace(_snapshot(), ownership_ids=("ownership-missing",))
    secured = _secured_result()

    with pytest.raises(ValueError, match="complete object coverage"):
        project_context_snapshot(
            snapshot=snapshot,
            secured_result=secured,
            authenticated_context=_authenticated_context(secured),
        )


@pytest.mark.parametrize(
    ("secured_result", "message"),
    (
        (_secured_result(principal_scope_digest="sha256:" + "d" * 64), "principal"),
        (_secured_result(release_digest="sha256:" + "c" * 64), "release"),
        (_secured_result(cutoff=datetime(2026, 8, 14, 0, 1, tzinfo=UTC)), "cutoff"),
        (_secured_result(object_ids=("resource-example",)), "object coverage"),
        (_secured_result(complete=False, source_complete=False), "unavailable"),
        (_secured_result(truncated=True), "unavailable"),
    ),
)
def test_rejects_receipt_or_coverage_mismatch(secured_result: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        project_context_snapshot(
            snapshot=_snapshot(),
            secured_result=secured_result,  # type: ignore[arg-type]
            authenticated_context=_authenticated_context(
                secured_result  # type: ignore[arg-type]
            ),
        )


def test_rejects_stale_snapshot_context() -> None:
    stale = replace(_snapshot(), stale_sources=("inventory",))
    secured = _secured_result()

    with pytest.raises(ValueError, match="unavailable"):
        project_context_snapshot(
            snapshot=stale,
            secured_result=secured,
            authenticated_context=_authenticated_context(secured),
        )


def test_rejects_object_type_revision_and_temporal_path_forgery() -> None:
    secured = _secured_result()
    forged_object = replace(secured.materialization.graph.objects[1], object_type="Resource")
    forged_graph = replace(
        secured.materialization.graph,
        objects=(secured.materialization.graph.objects[0], forged_object),
    )
    forged_materialization = secured.materialization.model_copy(update={"graph": forged_graph})
    forged = secured.model_copy(
        update={
            "materialization": forged_materialization,
            "receipt": secured.receipt.model_copy(
                update={"projected_result_digest": _projected_result_digest(forged_materialization)}
            ),
        }
    )
    context = _authenticated_context(forged)
    with pytest.raises(ValueError, match="object type or revision"):
        project_context_snapshot(
            snapshot=_snapshot(),
            secured_result=forged,
            authenticated_context=context,
        )

    temporal_snapshot = replace(
        _snapshot(),
        evidence_paths=(
            replace(
                _snapshot().evidence_paths[0],
                effective_from=datetime(2026, 8, 13, tzinfo=UTC),
            ),
            _snapshot().evidence_paths[1],
        ),
    )
    with pytest.raises(ValueError, match="temporal identity"):
        project_context_snapshot(
            snapshot=temporal_snapshot,
            secured_result=secured,
            authenticated_context=_authenticated_context(secured),
        )


def test_rejects_provenance_refs_unbound_from_secured_properties() -> None:
    secured = _secured_result()

    forged_snapshot = replace(
        _snapshot(),
        evidence_paths=(
            replace(
                _snapshot().evidence_paths[0],
                provenance_refs=("forged-provenance:unbound",),
            ),
            _snapshot().evidence_paths[1],
        ),
    )
    with pytest.raises(ValueError, match="provenance refs"):
        project_context_snapshot(
            snapshot=forged_snapshot,
            secured_result=secured,
            authenticated_context=_authenticated_context(secured),
        )

    omitted_snapshot = replace(
        _snapshot(),
        evidence_paths=(
            replace(_snapshot().evidence_paths[0], provenance_refs=()),
            _snapshot().evidence_paths[1],
        ),
    )
    with pytest.raises(ValueError, match="provenance refs"):
        project_context_snapshot(
            snapshot=omitted_snapshot,
            secured_result=secured,
            authenticated_context=_authenticated_context(secured),
        )


def test_rejects_forged_receipt_digest() -> None:
    secured = _secured_result()
    forged = secured.model_copy(
        update={
            "receipt": secured.receipt.model_copy(
                update={"projected_result_digest": "sha256:" + "d" * 64}
            )
        }
    )
    with pytest.raises(ValueError, match="not issued"):
        project_context_snapshot(
            snapshot=_snapshot(),
            secured_result=forged,
            authenticated_context=_authenticated_context(secured),
        )


def test_rejects_issued_receipt_completeness_forgery() -> None:
    secured = _secured_result(complete=False, source_complete=False)
    context = _authenticated_context(secured)
    forged = secured.model_copy(
        update={
            "receipt": secured.receipt.model_copy(update={"complete": True}),
        }
    )

    with pytest.raises(ValueError, match="not issued"):
        project_context_snapshot(
            snapshot=_snapshot(),
            secured_result=forged,
            authenticated_context=context,
        )


def test_rejects_issued_receipt_principal_scope_relabelling() -> None:
    secured = _secured_result(
        principal_scope_digest="sha256:" + "d" * 64,
    )
    context = _authenticated_context(secured)
    forged = secured.model_copy(
        update={
            "receipt": secured.receipt.model_copy(
                update={"principal_scope_digest": PRINCIPAL_SCOPE}
            ),
        }
    )

    with pytest.raises(ValueError, match="not issued"):
        project_context_snapshot(
            snapshot=_snapshot(),
            secured_result=forged,
            authenticated_context=context,
        )


def test_rejects_link_observation_metadata_drift() -> None:
    secured = _secured_result()
    secured_metadata = _link_metadata(source_revision="source-r1")
    secured_link = replace(
        secured.materialization.graph.links[0],
        properties={LINK_OBSERVATION_METADATA_PROPERTY: secured_metadata.to_mapping()},
    )
    secured_graph = replace(secured.materialization.graph, links=(secured_link,))
    secured_materialization = secured.materialization.model_copy(update={"graph": secured_graph})
    secured = secured.model_copy(
        update={
            "materialization": secured_materialization,
            "receipt": secured.receipt.model_copy(
                update={
                    "projected_result_digest": _projected_result_digest(secured_materialization)
                }
            ),
        }
    )
    snapshot_metadata = _link_metadata(source_revision="source-r2")
    snapshot_link = replace(_snapshot().evidence_links[0], observation_metadata=snapshot_metadata)
    snapshot = replace(
        _snapshot(),
        evidence_links=(snapshot_link,),
        evidence_paths=(
            _snapshot().evidence_paths[0],
            replace(_snapshot().evidence_paths[1], links=(snapshot_link,)),
        ),
    )

    with pytest.raises(ValueError, match="link observation metadata"):
        project_context_snapshot(
            snapshot=snapshot,
            secured_result=secured,
            authenticated_context=_authenticated_context(secured),
        )
