"""Deterministic network-path competency fixtures over secured ontology evidence."""

from __future__ import annotations

import hashlib
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
)
from fdai.core.ontology_platform.network_path import (
    NETWORK_PATH_FUNCTION_NAME,
    NETWORK_PATH_PURPOSE,
    NetworkPathResult,
    NetworkPathStatus,
    NetworkSegmentStatus,
    evaluate_network_path,
    network_path_function,
    network_path_function_type,
)
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.shared.contracts.models import CeilingRole, OntologyRelease
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
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

EVALUATED_AT = datetime(2026, 8, 8, 12, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[3]


def _resource(resource_id: str, resource_type: str) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=resource_id,
        object_type="Resource",
        properties={"id": resource_id, "type": resource_type},
    )


def _metadata(
    *,
    verified: bool = True,
    stale: bool = False,
    evidence_ref: str = "inventory-receipt-1",
    verification_receipt_ref: str = "network-verification-1",
    evidence_cutoff: datetime | None = None,
    effective_at: datetime | None = None,
    recorded_at: datetime | None = None,
    freshness_ceiling_seconds: int | None = None,
) -> LinkObservationMetadata:
    cutoff = evidence_cutoff or EVALUATED_AT - timedelta(seconds=600 if stale else 20)
    return LinkObservationMetadata(
        state_fact=StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.PROVIDER,
            source_identity="inventory-reader",
            source_revision="inventory-revision-1",
            effective_at=effective_at or cutoff - timedelta(seconds=10),
            recorded_at=recorded_at or cutoff + timedelta(seconds=10),
            evidence_cutoff=cutoff,
            freshness_ceiling_seconds=(
                freshness_ceiling_seconds
                if freshness_ceiling_seconds is not None
                else 60
                if stale
                else 300
            ),
            completeness=1.0,
            synthetic=False,
            evidence_refs=(evidence_ref,),
        ),
        verification_method=("provider-readback" if verified else "inventory-observation"),
        verified=verified,
        verifier_identity=("network-verifier" if verified else None),
        verifier_revision=("verifier-revision-1" if verified else None),
        verification_receipt_ref=(verification_receipt_ref if verified else None),
    )


def _link(
    from_id: str,
    link_type: str,
    to_id: str,
    *,
    metadata: LinkObservationMetadata | None = None,
) -> OntologyLinkRecord:
    evidence = metadata or _metadata()
    return OntologyLinkRecord(
        link_type=link_type,
        from_id=from_id,
        to_id=to_id,
        properties={LINK_OBSERVATION_METADATA_PROPERTY: evidence.to_mapping()},
    )


def _secured_result(
    *,
    objects: tuple[OntologyObjectRecord, ...],
    links: tuple[OntologyLinkRecord, ...],
    ontology_release: OntologyRelease | None = None,
    complete: bool = True,
    observation_cutoff: datetime = EVALUATED_AT,
) -> SecuredObjectSetQueryResult:
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=observation_cutoff,
        purpose="network-path-verification",
        limit=100,
    )
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(objects=objects, links=links, truncated=not complete),
        concrete_types=("Resource",),
        truncated=not complete,
        truncation_reason=("traversal_limit" if not complete else None),
    )
    receipt = SecuredObjectSetQueryReceipt(
        ontology_release=(ontology_release or build_ontology_release()).ref(),
        projected_result_digest=_projected_result_digest(materialization),
        purpose=definition.purpose,
        caller_role="reader",
        observation_cutoff=observation_cutoff,
        as_of_skew_seconds=0,
        returned_object_count=len(objects),
        returned_link_count=len(links),
        complete=complete,
        truncated=not complete,
        truncation_reason=("traversal_limit" if not complete else None),
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
    )
    return SecuredObjectSetQueryResult(materialization=materialization, receipt=receipt)


def test_complete_vm_path_reports_every_verified_segment() -> None:
    query_result = _secured_result(
        objects=(
            _resource("vm-1", "compute.vm"),
            _resource("nic-1", "network.nic"),
            _resource("route-1", "network.route"),
            _resource("vnet-1", "network.vnet"),
            _resource("vnet-2", "network.vnet"),
            _resource("nic-2", "network.nic"),
            _resource("vm-2", "compute.vm"),
        ),
        links=(
            _link("nic-1", "attached_to", "vm-1"),
            _link("nic-1", "routes_to", "route-1"),
            _link("route-1", "routes_to", "vnet-1"),
            _link(
                "vnet-1",
                "peered_with",
                "vnet-2",
                metadata=_metadata(
                    evidence_ref="inventory-receipt-peer-forward",
                    verification_receipt_ref="network-verification-peer-forward",
                ),
            ),
            _link(
                "vnet-2",
                "peered_with",
                "vnet-1",
                metadata=_metadata(
                    evidence_ref="inventory-receipt-peer-reverse",
                    verification_receipt_ref="network-verification-peer-reverse",
                ),
            ),
            _link("vnet-2", "contains", "nic-2"),
            _link("nic-2", "attached_to", "vm-2"),
        ),
    )

    result = evaluate_network_path(
        query_result,
        source_id="vm-1",
        target_id="vm-2",
        evaluated_at=EVALUATED_AT,
        max_depth=8,
        max_segments=32,
    )

    assert result.status is NetworkPathStatus.VERIFIED
    assert result.reachability_verified is True
    assert [segment.status for segment in result.segments] == [NetworkSegmentStatus.VERIFIED] * 6
    assert [(segment.from_id, segment.link_type, segment.to_id) for segment in result.segments] == [
        ("vm-1", "attached_to", "nic-1"),
        ("nic-1", "routes_to", "route-1"),
        ("route-1", "routes_to", "vnet-1"),
        ("vnet-1", "peered_with", "vnet-2"),
        ("vnet-2", "contains", "nic-2"),
        ("nic-2", "attached_to", "vm-2"),
    ]
    assert result.segments[3].stored_edges == (
        "vnet-1|peered_with|vnet-2",
        "vnet-2|peered_with|vnet-1",
    )


def test_one_unverified_segment_prevents_reachability_claim() -> None:
    query_result = _secured_result(
        objects=(_resource("nic-1", "network.nic"), _resource("route-1", "network.route")),
        links=(
            _link(
                "nic-1",
                "routes_to",
                "route-1",
                metadata=_metadata(verified=False),
            ),
        ),
    )

    result = evaluate_network_path(
        query_result,
        source_id="nic-1",
        target_id="route-1",
        evaluated_at=EVALUATED_AT,
        max_depth=2,
        max_segments=4,
    )

    assert result.status is NetworkPathStatus.UNVERIFIED
    assert result.reachability_verified is None
    assert result.segments[0].status is NetworkSegmentStatus.UNVERIFIED
    assert result.segments[0].reason_codes == ("not_independently_verified",)


def test_stale_segment_is_reported_without_reachability_claim() -> None:
    query_result = _secured_result(
        objects=(_resource("nic-1", "network.nic"), _resource("route-1", "network.route")),
        links=(
            _link(
                "nic-1",
                "routes_to",
                "route-1",
                metadata=_metadata(stale=True),
            ),
        ),
    )

    result = evaluate_network_path(
        query_result,
        source_id="nic-1",
        target_id="route-1",
        evaluated_at=EVALUATED_AT,
        max_depth=2,
        max_segments=4,
    )

    assert result.status is NetworkPathStatus.STALE
    assert result.reachability_verified is None
    assert result.segments[0].status is NetworkSegmentStatus.STALE
    assert result.segments[0].reason_codes == ("evidence_stale",)


def test_missing_endpoint_is_explicit_and_never_means_unreachable() -> None:
    query_result = _secured_result(
        objects=(_resource("vm-1", "compute.vm"),),
        links=(),
    )

    result = evaluate_network_path(
        query_result,
        source_id="vm-1",
        target_id="vm-missing",
        evaluated_at=EVALUATED_AT,
        max_depth=4,
        max_segments=8,
    )

    assert result.status is NetworkPathStatus.MISSING_ENDPOINT
    assert result.reachability_verified is None
    assert result.segments[0].status is NetworkSegmentStatus.MISSING
    assert result.segments[0].reason_codes == ("missing_target",)


def test_cycle_is_bounded_and_reported_when_no_path_is_observed() -> None:
    query_result = _secured_result(
        objects=(
            _resource("vm-1", "compute.vm"),
            _resource("nic-1", "network.nic"),
            _resource("route-1", "network.route"),
            _resource("vm-2", "compute.vm"),
        ),
        links=(
            _link("nic-1", "attached_to", "vm-1"),
            _link("nic-1", "routes_to", "route-1"),
            _link("route-1", "routes_to", "nic-1"),
        ),
    )

    result = evaluate_network_path(
        query_result,
        source_id="vm-1",
        target_id="vm-2",
        evaluated_at=EVALUATED_AT,
        max_depth=8,
        max_segments=16,
    )

    assert result.status is NetworkPathStatus.CYCLE_DETECTED
    assert result.cycle_detected is True
    assert result.reachability_verified is None


def test_unilateral_peering_is_not_a_symmetric_path() -> None:
    query_result = _secured_result(
        objects=(_resource("vnet-1", "network.vnet"), _resource("vnet-2", "network.vnet")),
        links=(_link("vnet-1", "peered_with", "vnet-2"),),
    )

    result = evaluate_network_path(
        query_result,
        source_id="vnet-1",
        target_id="vnet-2",
        evaluated_at=EVALUATED_AT,
        max_depth=2,
        max_segments=4,
    )

    assert result.status is NetworkPathStatus.NO_PATH_EVIDENCE
    assert result.invalid_peering_edges == 1
    assert result.reachability_verified is None


def test_reciprocal_peering_rejects_reused_direction_receipt() -> None:
    reused = _metadata(verification_receipt_ref="network-verification-reused")
    query_result = _secured_result(
        objects=(_resource("vnet-1", "network.vnet"), _resource("vnet-2", "network.vnet")),
        links=(
            _link("vnet-1", "peered_with", "vnet-2", metadata=reused),
            _link("vnet-2", "peered_with", "vnet-1", metadata=reused),
        ),
    )

    result = evaluate_network_path(
        query_result,
        source_id="vnet-1",
        target_id="vnet-2",
        evaluated_at=EVALUATED_AT,
        max_depth=2,
        max_segments=4,
    )

    assert result.status is NetworkPathStatus.UNVERIFIED
    assert result.segments[0].reason_codes == ("peering_receipt_reused",)


@pytest.mark.parametrize(
    ("metadata", "reason"),
    (
        (
            _metadata(recorded_at=EVALUATED_AT + timedelta(seconds=1)),
            "evidence_recorded_after_cutoff",
        ),
        (
            _metadata(
                evidence_cutoff=EVALUATED_AT + timedelta(seconds=1),
                effective_at=EVALUATED_AT + timedelta(seconds=1),
                recorded_at=EVALUATED_AT + timedelta(seconds=2),
            ),
            "evidence_effective_after_cutoff",
        ),
        (
            _metadata(freshness_ceiling_seconds=31_536_001),
            "freshness_ceiling_exceeded",
        ),
    ),
)
def test_segment_time_and_freshness_are_bounded_to_query_cutoff(
    metadata: LinkObservationMetadata,
    reason: str,
) -> None:
    query_result = _secured_result(
        objects=(_resource("nic-1", "network.nic"), _resource("route-1", "network.route")),
        links=(_link("nic-1", "routes_to", "route-1", metadata=metadata),),
    )

    result = evaluate_network_path(
        query_result,
        source_id="nic-1",
        target_id="route-1",
        evaluated_at=EVALUATED_AT,
        max_depth=2,
        max_segments=4,
    )

    assert result.status is NetworkPathStatus.UNVERIFIED
    assert reason in result.segments[0].reason_codes


def test_freshness_timestamp_overflow_is_unverified() -> None:
    cutoff = datetime.max.replace(tzinfo=UTC)
    metadata = _metadata(
        evidence_cutoff=cutoff,
        effective_at=cutoff - timedelta(seconds=1),
        recorded_at=cutoff,
        freshness_ceiling_seconds=1,
    )
    query_result = _secured_result(
        objects=(_resource("nic-1", "network.nic"), _resource("route-1", "network.route")),
        links=(_link("nic-1", "routes_to", "route-1", metadata=metadata),),
        observation_cutoff=cutoff,
    )

    result = evaluate_network_path(
        query_result,
        source_id="nic-1",
        target_id="route-1",
        evaluated_at=cutoff,
        max_depth=2,
        max_segments=4,
    )

    assert result.status is NetworkPathStatus.UNVERIFIED
    assert result.segments[0].reason_codes == ("freshness_overflow",)


def test_evaluation_cutoff_must_equal_secured_observation_cutoff() -> None:
    query_result = _secured_result(
        objects=(_resource("nic-1", "network.nic"), _resource("route-1", "network.route")),
        links=(_link("nic-1", "routes_to", "route-1"),),
    )

    with pytest.raises(ValueError, match="observation cutoff"):
        evaluate_network_path(
            query_result,
            source_id="nic-1",
            target_id="route-1",
            evaluated_at=EVALUATED_AT + timedelta(microseconds=1),
            max_depth=2,
            max_segments=4,
        )


def test_incomplete_graph_returns_query_incomplete() -> None:
    query_result = _secured_result(
        objects=(_resource("nic-1", "network.nic"), _resource("route-1", "network.route")),
        links=(),
        complete=False,
    )

    result = evaluate_network_path(
        query_result,
        source_id="nic-1",
        target_id="route-1",
        evaluated_at=EVALUATED_AT,
        max_depth=2,
        max_segments=4,
    )

    assert result.status is NetworkPathStatus.UNVERIFIED
    assert result.reason_codes == ("query_incomplete",)


def test_irrelevant_links_do_not_consume_network_segment_limit() -> None:
    query_result = _secured_result(
        objects=(
            _resource("nic-1", "network.nic"),
            _resource("route-1", "network.route"),
            _resource("other-1", "example.other"),
            _resource("other-2", "example.other"),
        ),
        links=(
            _link("nic-1", "routes_to", "route-1"),
            _link("other-1", "unrelated", "other-2"),
        ),
    )

    result = evaluate_network_path(
        query_result,
        source_id="nic-1",
        target_id="route-1",
        evaluated_at=EVALUATED_AT,
        max_depth=2,
        max_segments=1,
    )

    assert result.status is NetworkPathStatus.VERIFIED
    assert result.examined_segments == 1


def test_function_artifact_digest_is_derived_from_module_source() -> None:
    import fdai.core.ontology_platform.network_path as network_path_module

    source = Path(inspect.getsourcefile(network_path_module) or "").read_bytes()

    assert network_path_function_type().artifact_digest == (
        f"sha256:{hashlib.sha256(source).hexdigest()}"
    )


class _ReceiptVerifier:
    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted
        self.calls: list[dict[str, Any]] = []

    def verify(self, **kwargs: Any) -> bool:
        self.calls.append(kwargs)
        return self.accepted


def test_depth_and_segment_caps_stop_traversal() -> None:
    query_result = _secured_result(
        objects=(
            _resource("nic-1", "network.nic"),
            _resource("route-1", "network.route"),
            _resource("vnet-1", "network.vnet"),
        ),
        links=(
            _link("nic-1", "routes_to", "route-1"),
            _link("route-1", "routes_to", "vnet-1"),
        ),
    )

    depth_result = evaluate_network_path(
        query_result,
        source_id="nic-1",
        target_id="vnet-1",
        evaluated_at=EVALUATED_AT,
        max_depth=1,
        max_segments=8,
    )
    segment_result = evaluate_network_path(
        query_result,
        source_id="nic-1",
        target_id="vnet-1",
        evaluated_at=EVALUATED_AT,
        max_depth=4,
        max_segments=1,
    )

    assert depth_result.status is NetworkPathStatus.LIMIT_EXCEEDED
    assert depth_result.reason_codes == ("depth_limit",)
    assert segment_result.status is NetworkPathStatus.LIMIT_EXCEEDED
    assert segment_result.reason_codes == ("segment_limit",)
    assert segment_result.examined_segments == 0


async def test_exact_release_function_receipt_pins_network_result() -> None:
    declaration = network_path_function_type()
    schema_registry = PackageResourceSchemaRegistry()
    object_types = load_object_type_catalog(
        REPO_ROOT / "rule-catalog" / "vocabulary" / "object-types",
        schema_registry=schema_registry,
    )
    link_types = load_link_type_catalog(
        REPO_ROOT / "rule-catalog" / "vocabulary" / "link-types",
        schema_registry=schema_registry,
        object_types=object_types,
    )
    network_link_types = tuple(
        item
        for item in link_types
        if item.name in {"attached_to", "contains", "peered_with", "routes_to"}
    )
    release = build_ontology_release(
        object_types=object_types,
        link_types=network_link_types,
        function_types=(declaration,),
    )
    query_result = _secured_result(
        objects=(_resource("nic-1", "network.nic"), _resource("route-1", "network.route")),
        links=(_link("nic-1", "routes_to", "route-1"),),
        ontology_release=release,
    )
    registry = OntologyFunctionRegistry(release=release)
    verifier = _ReceiptVerifier()
    verification_context = object()
    registry.register_contextual(
        declaration,
        network_path_function(
            release,
            receipt_verifier=verifier,
            verification_context=verification_context,
        ),
    )

    result, receipt = await registry.invoke_with_receipt(
        NETWORK_PATH_FUNCTION_NAME,
        {
            "query_result": query_result.model_dump(mode="json"),
            "source_id": "nic-1",
            "target_id": "route-1",
            "evaluated_at": EVALUATED_AT.isoformat(),
            "max_depth": 2,
            "max_segments": 4,
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("network-path-verification",),
            evidence_refs=(query_result.receipt.projected_result_digest,),
        ),
    )

    assert isinstance(result, NetworkPathResult)
    assert result.status is NetworkPathStatus.VERIFIED
    assert receipt.function_ref.catalog_digest == release.digest
    assert receipt.function_ref.name == NETWORK_PATH_FUNCTION_NAME
    assert receipt.evidence_refs == (query_result.receipt.projected_result_digest,)
    assert verifier.calls == [
        {
            "receipt": query_result.receipt,
            "invocation_context": FunctionInvocationContext(
                caller_agent="Bragi",
                caller_role=CeilingRole.READER,
                purposes=(NETWORK_PATH_PURPOSE,),
                evidence_refs=(query_result.receipt.projected_result_digest,),
            ),
            "expected_release": release.ref(),
            "expected_purpose": NETWORK_PATH_PURPOSE,
            "expected_result_digest": query_result.receipt.projected_result_digest,
            "verification_context": verification_context,
        }
    ]

    stale_query_result = _secured_result(
        objects=(_resource("nic-1", "network.nic"), _resource("route-1", "network.route")),
        links=(_link("nic-1", "routes_to", "route-1"),),
    )
    with pytest.raises(ValueError, match="exact ontology release"):
        await registry.invoke(
            NETWORK_PATH_FUNCTION_NAME,
            {
                "query_result": stale_query_result.model_dump(mode="json"),
                "source_id": "nic-1",
                "target_id": "route-1",
                "evaluated_at": EVALUATED_AT.isoformat(),
                "max_depth": 2,
                "max_segments": 4,
            },
            context=FunctionInvocationContext(
                caller_agent="Bragi",
                caller_role=CeilingRole.READER,
                purposes=("network-path-verification",),
            ),
        )


async def test_network_function_rejects_unverified_or_context_mismatched_receipt() -> None:
    declaration = network_path_function_type()
    release = build_ontology_release(function_types=(declaration,))
    query_result = _secured_result(
        objects=(_resource("nic-1", "network.nic"), _resource("route-1", "network.route")),
        links=(_link("nic-1", "routes_to", "route-1"),),
        ontology_release=release,
    )
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        network_path_function(
            release,
            receipt_verifier=_ReceiptVerifier(accepted=False),
            verification_context=object(),
        ),
    )
    arguments = {
        "query_result": query_result.model_dump(mode="json"),
        "source_id": "nic-1",
        "target_id": "route-1",
        "evaluated_at": EVALUATED_AT.isoformat(),
        "max_depth": 2,
        "max_segments": 4,
    }

    with pytest.raises(PermissionError, match="receipt verification"):
        await registry.invoke(
            NETWORK_PATH_FUNCTION_NAME,
            arguments,
            context=FunctionInvocationContext(
                caller_agent="Bragi",
                caller_role=CeilingRole.READER,
                purposes=(NETWORK_PATH_PURPOSE,),
                evidence_refs=(query_result.receipt.projected_result_digest,),
            ),
        )

    accepting_registry = OntologyFunctionRegistry(release=release)
    accepting_registry.register_contextual(
        declaration,
        network_path_function(
            release,
            receipt_verifier=_ReceiptVerifier(),
            verification_context=object(),
        ),
    )
    with pytest.raises(PermissionError, match="invocation context"):
        await accepting_registry.invoke(
            NETWORK_PATH_FUNCTION_NAME,
            arguments,
            context=FunctionInvocationContext(
                caller_agent="Bragi",
                caller_role=CeilingRole.READER,
                purposes=(NETWORK_PATH_PURPOSE,),
                evidence_refs=("self-minted-receipt",),
            ),
        )
