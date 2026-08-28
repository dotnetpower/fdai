"""Issued Kubernetes Pod restart and recovery query tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.kubernetes_pod_lifecycle_cohort_queries import (
    KUBERNETES_POD_LIFECYCLE_COHORT_FUNCTION_NAME,
    kubernetes_pod_lifecycle_cohort_function,
    kubernetes_pod_lifecycle_cohort_function_type,
)
from fdai.core.ontology_platform.kubernetes_pod_recovery_evidence import (
    KubernetesPodRecoveryEvidenceResult,
    KubernetesPodRecoveryStatus,
)
from fdai.core.ontology_platform.kubernetes_pod_recovery_queries import (
    KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
    KUBERNETES_POD_RESTART_HISTORY_CONCEPT,
    evaluate_kubernetes_pod_recovery_graph,
    kubernetes_pod_recovery_function,
    kubernetes_pod_recovery_function_type,
)
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
    ObjectTraversal,
)
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.core.ontology_platform.query_receipt_authority import SecuredQueryReceiptAuthority
from fdai.shared.contracts.models import CeilingRole, OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    STATE_FACT_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

_CUTOFF = datetime(2026, 8, 25, 16, 0, tzinfo=UTC)
_POD_ID = "cluster:example/kubernetes/pod/example"
_REPLICA_SET_ID = "cluster:example/kubernetes/replica-set/example"
_DEPLOYMENT_ID = "cluster:example/kubernetes/deployment/example"


def _metadata() -> StateFactMetadata:
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="kubernetes-api-inventory",
        source_revision="generation-1",
        effective_at=_CUTOFF,
        recorded_at=_CUTOFF,
        evidence_cutoff=_CUTOFF,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("kubernetes:pod:example",),
    )


def _resource_type() -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "type": PropertyDecl(type=PropertyType.STRING, required=True),
            "properties": PropertyDecl(type=PropertyType.OBJECT),
        },
    )


def _secured(*, release=None) -> SecuredObjectSetQueryResult:  # type: ignore[no-untyped-def]
    pod = _resource(
        _POD_ID,
        "kubernetes.pod",
        phase="Running",
        uid="pod-uid-new",
        cluster_ref="cluster-a",
        namespace="default",
        owner_uid="rs-uid",
        root_controller_uid="deployment-uid",
        root_controller_kind="Deployment",
        created_at=(_CUTOFF - timedelta(minutes=4)).isoformat(),
        ready=True,
        container_count=1,
        ready_container_count=1,
        restart_count=1,
    )
    return _secured_result(objects=(pod,), release=release)


def _owner_results(
    *, release=None
) -> tuple[SecuredObjectSetQueryResult, SecuredObjectSetQueryResult]:  # type: ignore[no-untyped-def]
    pod = _resource(_POD_ID, "kubernetes.pod")
    replica_set = _resource(_REPLICA_SET_ID, "kubernetes.replica-set")
    deployment = _resource(
        _DEPLOYMENT_ID,
        "kubernetes.deployment",
        uid="deployment-uid",
        desired_replicas=1,
        ready_replicas=1,
        available_replicas=1,
        unavailable_replicas=0,
    )
    return (
        _secured_result(
            objects=(pod, replica_set),
            links=(_ownership(_POD_ID, _REPLICA_SET_ID),),
            root_ids=(_POD_ID,),
            release=release,
        ),
        _secured_result(
            objects=(replica_set, deployment),
            links=(_ownership(_REPLICA_SET_ID, _DEPLOYMENT_ID),),
            root_ids=(_REPLICA_SET_ID,),
            release=release,
        ),
    )


def _resource(resource_id: str, resource_type: str, **properties: object) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=resource_id,
        object_type="Resource",
        properties={
            "id": resource_id,
            "type": resource_type,
            "properties": {
                **properties,
                STATE_FACT_METADATA_PROPERTY: _metadata().to_mapping(),
            },
        },
    )


def _ownership(child_id: str, owner_id: str) -> OntologyLinkRecord:
    return OntologyLinkRecord(
        link_type="kubernetes_owned_by",
        from_id=child_id,
        to_id=owner_id,
        properties={
            LINK_OBSERVATION_METADATA_PROPERTY: LinkObservationMetadata(
                state_fact=_metadata(),
                verification_method="deterministic-cross-check",
                verified=True,
                verifier_identity="inventory-relationship-verifier",
                verifier_revision="verifier-1",
                verification_receipt_ref=f"verification:{child_id}:{owner_id}",
            ).to_mapping()
        },
    )


def _secured_result(
    *,
    objects: tuple[OntologyObjectRecord, ...],
    links: tuple[OntologyLinkRecord, ...] = (),
    root_ids: tuple[str, ...] = (),
    release=None,  # type: ignore[no-untyped-def]
) -> SecuredObjectSetQueryResult:
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        root_ids=root_ids,
        traversal=(
            ObjectTraversal(
                link_types=("kubernetes_owned_by",),
                direction="outgoing",
                max_depth=1,
            )
            if root_ids
            else None
        ),
        as_of=_CUTOFF,
        purpose="operations-review",
        limit=8,
    )
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(objects=objects, links=links, truncated=False),
        concrete_types=("Resource",),
        truncated=False,
    )
    receipt = SecuredObjectSetQueryReceipt(
        ontology_release=(release or build_ontology_release()).ref(),
        projected_result_digest=_projected_result_digest(materialization),
        purpose="operations-review",
        caller_role="reader",
        observation_cutoff=_CUTOFF,
        as_of_skew_seconds=0,
        returned_object_count=len(objects),
        returned_link_count=len(links),
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
    )
    return SecuredObjectSetQueryResult(materialization=materialization, receipt=receipt)


def _restart_history() -> dict[str, object]:
    return {
        "concept_id": KUBERNETES_POD_RESTART_HISTORY_CONCEPT,
        "resource_id": "cluster:example/kubernetes/pod/example",
        "unit": "count",
        "start": (_CUTOFF - timedelta(minutes=30)).isoformat(),
        "end": _CUTOFF.isoformat(),
        "samples": [{"timestamp": _CUTOFF.isoformat(), "value": 1.0}],
        "complete": True,
        "evidence_refs": ["metric:pod-restart:example"],
        "missing_reason": None,
    }


def test_exact_pod_graph_reports_recovered_without_claiming_cause() -> None:
    controller_result, deployment_result = _owner_results()
    result = evaluate_kubernetes_pod_recovery_graph(
        _secured(),
        controller_result=controller_result,
        deployment_result=deployment_result,
        restart_history=_restart_history(),
        cutoff=_CUTOFF,
    )

    assert result.status is KubernetesPodRecoveryStatus.RECOVERED
    assert result.recovery_verified is True
    assert result.cause_claim_supported is False
    assert result.execution_authority is False


def test_pod_recovery_function_is_read_only_and_source_derived() -> None:
    declaration = kubernetes_pod_recovery_function_type()

    assert declaration.name == KUBERNETES_POD_RECOVERY_FUNCTION_NAME
    assert declaration.network_allowed is False
    assert declaration.credentials_allowed is False
    assert declaration.purpose_bindings == ["operations-review"]


async def test_pod_recovery_function_accepts_only_issued_receipt() -> None:
    resource = _resource_type()
    declaration = kubernetes_pod_recovery_function_type()
    release = build_ontology_release(
        object_types=(resource,),
        function_types=(declaration,),
    )
    secured = _secured(release=release)
    controller_result, deployment_result = _owner_results(release=release)
    authority = SecuredQueryReceiptAuthority()
    for query_result in (secured, controller_result, deployment_result):
        authority.issue(query_result)
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        kubernetes_pod_recovery_function(
            release,
            receipt_verifier=authority,
            verification_context=authority.verification_context,
        ),
    )
    context = FunctionInvocationContext(
        caller_agent="Heimdall",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
        evidence_refs=tuple(
            sorted(
                result.receipt.projected_result_digest
                for result in (secured, controller_result, deployment_result)
            )
        ),
    )

    result, receipt = await registry.invoke_with_receipt(
        KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
        {
            "pod_query_result": secured.model_dump(mode="json"),
            "controller_query_result": controller_result.model_dump(mode="json"),
            "deployment_query_result": deployment_result.model_dump(mode="json"),
            "restart_history": _restart_history(),
        },
        context=context,
    )

    assert isinstance(result, KubernetesPodRecoveryEvidenceResult)
    assert result.recovery_verified is True
    assert receipt.function_ref.catalog_digest == release.digest

    held = await registry.invoke(
        KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
        {
            "pod_query_result": secured.model_dump(mode="json"),
            "controller_query_result": controller_result.model_dump(mode="json"),
            "deployment_query_result": deployment_result.model_dump(mode="json"),
            "restart_history": _restart_history(),
            "lifecycle_cohort": {
                "rows": [],
                "complete": False,
                "truncation_reason": "lifecycle_cursor_stale",
            },
        },
        context=context,
    )
    assert isinstance(held, KubernetesPodRecoveryEvidenceResult)
    assert held.status is KubernetesPodRecoveryStatus.INSUFFICIENT_EVIDENCE
    assert held.recovery_verified is False

    supported = await registry.invoke(
        KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
        {
            "pod_query_result": secured.model_dump(mode="json"),
            "controller_query_result": controller_result.model_dump(mode="json"),
            "deployment_query_result": deployment_result.model_dump(mode="json"),
            "restart_history": _restart_history(),
            "lifecycle_cohort": {
                "rows": [
                    {
                        "row_id": "old-failure",
                        "values": {
                            "pod_id": "pod-old",
                            "pod_uid": "pod-uid-old",
                            "cluster_ref": "cluster-a",
                            "namespace": "default",
                            "object_uid": "pod-uid-old",
                            "owner_uid": "rs-uid",
                            "root_controller_uid": "deployment-uid",
                            "root_controller_kind": "Deployment",
                            "identity_observed_at": (_CUTOFF - timedelta(minutes=7)).isoformat(),
                            "identity_source_revision": "sha256:" + "a" * 64,
                            "identity_evidence_ref": "kubernetes-pod-lifecycle:" + "b" * 64,
                            "reason": "Failed",
                            "category": "failed",
                            "event_type": "Warning",
                            "event_time": (_CUTOFF - timedelta(minutes=6)).isoformat(),
                            "recorded_time": (_CUTOFF - timedelta(minutes=5)).isoformat(),
                            "source_revision": "100",
                            "evidence_ref": "old-failure",
                        },
                    }
                ],
                "complete": True,
                "truncation_reason": None,
                "window_start": (_CUTOFF - timedelta(minutes=30)).isoformat(),
            },
        },
        context=context,
    )
    assert isinstance(supported, KubernetesPodRecoveryEvidenceResult)
    assert supported.complete is True
    assert not any(gap.startswith("replacement_evidence_") for gap in supported.evidence_gaps)

    replacement_context = {
        "old_pod": {
            "pod_id": "pod-old",
            "pod_uid": "pod-uid-old",
            "cluster_id": "cluster-a",
            "namespace": "default",
            "owner_uid": "rs-uid",
            "root_controller_uid": "deployment-uid",
            "root_controller_kind": "Deployment",
            "created_at": (_CUTOFF - timedelta(hours=1)).isoformat(),
            "phase": "Failed",
            "ready": False,
            "container_count": 1,
            "ready_container_count": 0,
            "waiting_reasons": [],
            "workload_revision": None,
            "metadata": _metadata().to_mapping(),
            "evidence_refs": ["pod-old"],
        },
        "candidates": [
            {
                "pod_id": "pod-new",
                "pod_uid": "pod-uid-new",
                "cluster_id": "cluster-a",
                "namespace": "default",
                "owner_uid": "rs-uid",
                "root_controller_uid": "deployment-uid",
                "root_controller_kind": "Deployment",
                "created_at": (_CUTOFF - timedelta(minutes=4)).isoformat(),
                "phase": "Running",
                "ready": True,
                "container_count": 1,
                "ready_container_count": 1,
                "waiting_reasons": [],
                "workload_revision": None,
                "metadata": _metadata().to_mapping(),
                "evidence_refs": ["pod-new"],
            }
        ],
        "deployment": {
            "deployment_id": "deployment-uid",
            "desired_replicas_before": 1,
            "desired_replicas_after": 1,
            "ready_replicas": 1,
            "available_replicas": 1,
            "unavailable_replicas": 0,
            "metadata": _metadata().to_mapping(),
            "evidence_refs": ["deployment"],
        },
        "correlation_window_start": (_CUTOFF - timedelta(minutes=30)).isoformat(),
    }
    assert replacement_context["candidates"]
    held_replacement = await registry.invoke(
        KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
        {
            "pod_query_result": secured.model_dump(mode="json"),
            "controller_query_result": controller_result.model_dump(mode="json"),
            "deployment_query_result": deployment_result.model_dump(mode="json"),
            "restart_history": _restart_history(),
            "lifecycle_cohort": {
                "rows": [
                    {
                        "row_id": "lifecycle-1",
                        "values": {
                            "pod_id": "pod-old",
                            "pod_uid": "pod-uid-old",
                            "cluster_ref": "cluster-a",
                            "namespace": "default",
                            "object_uid": "pod-uid-old",
                            "owner_uid": "rs-uid",
                            "root_controller_uid": "deployment-uid",
                            "root_controller_kind": "Deployment",
                            "identity_observed_at": (_CUTOFF - timedelta(minutes=7)).isoformat(),
                            "identity_source_revision": "sha256:" + "a" * 64,
                            "identity_evidence_ref": "kubernetes-pod-lifecycle:" + "b" * 64,
                            "event_kind": "Started",
                            "classification": "started",
                            "status": "Normal",
                            "occurred_at": (_CUTOFF - timedelta(minutes=6)).isoformat(),
                            "recorded_time": (_CUTOFF - timedelta(minutes=5)).isoformat(),
                            "recorded_at": (_CUTOFF - timedelta(minutes=5)).isoformat(),
                            "source_revision": "100",
                            "evidence_ref": "lifecycle-started",
                        },
                    }
                ],
                "complete": True,
                "truncation_reason": None,
                "window_start": (_CUTOFF - timedelta(minutes=30)).isoformat(),
            },
        },
        context=context,
    )
    assert isinstance(held_replacement, KubernetesPodRecoveryEvidenceResult)
    assert held_replacement.status is KubernetesPodRecoveryStatus.INSUFFICIENT_EVIDENCE
    assert any(gap.startswith("replacement_evidence_") for gap in held_replacement.evidence_gaps)

    unissued = SecuredQueryReceiptAuthority()
    rejecting = OntologyFunctionRegistry(release=release)
    rejecting.register_contextual(
        declaration,
        kubernetes_pod_recovery_function(
            release,
            receipt_verifier=unissued,
            verification_context=unissued.verification_context,
        ),
    )
    with pytest.raises(PermissionError, match="receipt verification"):
        await rejecting.invoke(
            KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
            {
                "pod_query_result": secured.model_dump(mode="json"),
                "controller_query_result": controller_result.model_dump(mode="json"),
                "deployment_query_result": deployment_result.model_dump(mode="json"),
                "restart_history": _restart_history(),
            },
            context=context,
        )


async def test_confirmed_distinct_uid_replacement_recovers_new_pod_without_own_restart() -> None:
    """A genuinely new replacement Pod has never itself restarted.

    ``restart_not_observed_in_current_pod``/``restart_not_observed_in_window``
    are spurious in that case once an independent distinct-UID replacement is
    conclusively verified, and MUST NOT hold the composite result at
    ``INSUFFICIENT_EVIDENCE`` despite the confirmed replacement evidence.
    """
    resource = _resource_type()
    declaration = kubernetes_pod_recovery_function_type()
    release = build_ontology_release(
        object_types=(resource,),
        function_types=(declaration,),
    )
    new_pod = _resource(
        _POD_ID,
        "kubernetes.pod",
        phase="Running",
        uid="pod-uid-new",
        cluster_ref="cluster-a",
        namespace="default",
        owner_uid="rs-uid",
        root_controller_uid="deployment-uid",
        root_controller_kind="Deployment",
        created_at=(_CUTOFF - timedelta(minutes=4)).isoformat(),
        ready=True,
        container_count=1,
        ready_container_count=1,
        restart_count=0,
    )
    secured = _secured_result(objects=(new_pod,), release=release)
    controller_result, deployment_result = _owner_results(release=release)
    authority = SecuredQueryReceiptAuthority()
    for query_result in (secured, controller_result, deployment_result):
        authority.issue(query_result)
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        kubernetes_pod_recovery_function(
            release,
            receipt_verifier=authority,
            verification_context=authority.verification_context,
        ),
    )
    context = FunctionInvocationContext(
        caller_agent="Heimdall",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
        evidence_refs=tuple(
            sorted(
                result.receipt.projected_result_digest
                for result in (secured, controller_result, deployment_result)
            )
        ),
    )
    never_restarted_history = {
        "concept_id": KUBERNETES_POD_RESTART_HISTORY_CONCEPT,
        "resource_id": _POD_ID,
        "unit": "count",
        "start": (_CUTOFF - timedelta(minutes=30)).isoformat(),
        "end": _CUTOFF.isoformat(),
        "samples": [{"timestamp": _CUTOFF.isoformat(), "value": 0.0}],
        "complete": True,
        "evidence_refs": ["metric:pod-restart:example"],
        "missing_reason": None,
    }

    result = await registry.invoke(
        KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
        {
            "pod_query_result": secured.model_dump(mode="json"),
            "controller_query_result": controller_result.model_dump(mode="json"),
            "deployment_query_result": deployment_result.model_dump(mode="json"),
            "restart_history": never_restarted_history,
            "lifecycle_cohort": {
                "rows": [
                    {
                        "row_id": "old-failure",
                        "values": {
                            "pod_id": "pod-old",
                            "pod_uid": "pod-uid-old",
                            "cluster_ref": "cluster-a",
                            "namespace": "default",
                            "object_uid": "pod-uid-old",
                            "owner_uid": "rs-uid",
                            "root_controller_uid": "deployment-uid",
                            "root_controller_kind": "Deployment",
                            "identity_observed_at": (_CUTOFF - timedelta(minutes=7)).isoformat(),
                            "identity_source_revision": "sha256:" + "a" * 64,
                            "identity_evidence_ref": "kubernetes-pod-lifecycle:" + "b" * 64,
                            "reason": "Failed",
                            "category": "failed",
                            "event_type": "Warning",
                            "event_time": (_CUTOFF - timedelta(minutes=6)).isoformat(),
                            "recorded_time": (_CUTOFF - timedelta(minutes=5)).isoformat(),
                            "source_revision": "100",
                            "evidence_ref": "old-failure",
                        },
                    }
                ],
                "complete": True,
                "truncation_reason": None,
                "window_start": (_CUTOFF - timedelta(minutes=30)).isoformat(),
            },
        },
        context=context,
    )

    assert isinstance(result, KubernetesPodRecoveryEvidenceResult)
    assert result.status is KubernetesPodRecoveryStatus.RECOVERED
    assert result.recovery_verified is True
    assert result.complete is True
    assert not result.evidence_gaps
    assert "old-failure" in result.evidence_refs


async def test_same_uid_restart_without_historical_identity_is_not_penalized() -> None:
    """A same-UID restart legitimately has no distinct historical predecessor.

    A retained lifecycle cohort that observed only the current Pod's own
    identity MUST NOT be treated as missing replacement evidence: the Pod's
    own restart-count and deployment evidence already fully determine
    recovery on their own.
    """
    resource = _resource_type()
    declaration = kubernetes_pod_recovery_function_type()
    release = build_ontology_release(
        object_types=(resource,),
        function_types=(declaration,),
    )
    secured = _secured(release=release)
    controller_result, deployment_result = _owner_results(release=release)
    authority = SecuredQueryReceiptAuthority()
    for query_result in (secured, controller_result, deployment_result):
        authority.issue(query_result)
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        kubernetes_pod_recovery_function(
            release,
            receipt_verifier=authority,
            verification_context=authority.verification_context,
        ),
    )
    context = FunctionInvocationContext(
        caller_agent="Heimdall",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
        evidence_refs=tuple(
            sorted(
                result.receipt.projected_result_digest
                for result in (secured, controller_result, deployment_result)
            )
        ),
    )

    result = await registry.invoke(
        KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
        {
            "pod_query_result": secured.model_dump(mode="json"),
            "controller_query_result": controller_result.model_dump(mode="json"),
            "deployment_query_result": deployment_result.model_dump(mode="json"),
            "restart_history": _restart_history(),
            "lifecycle_cohort": {
                "rows": [],
                "complete": True,
                "truncation_reason": None,
                "window_start": (_CUTOFF - timedelta(minutes=30)).isoformat(),
            },
        },
        context=context,
    )

    assert isinstance(result, KubernetesPodRecoveryEvidenceResult)
    assert result.status is KubernetesPodRecoveryStatus.RECOVERED
    assert result.recovery_verified is True
    assert result.complete is True
    assert not any(gap.startswith("replacement_evidence_") for gap in result.evidence_gaps)


async def test_incomplete_pod_diagnosis_holds_the_composite_recovery_result() -> None:
    """An incomplete safety-critical Pod diagnosis MUST hold the composite result.

    The semantic runtime answers Pod recovery investigations from this
    composite ``KubernetesPodRecoveryEvidenceResult``. If the exact diagnosis
    QueryTable it is fused with is incomplete, that incompleteness MUST be
    reflected here rather than silently treated as a fully answered,
    trustworthy recovery evidence result.
    """
    resource = _resource_type()
    declaration = kubernetes_pod_recovery_function_type()
    release = build_ontology_release(
        object_types=(resource,),
        function_types=(declaration,),
    )
    secured = _secured(release=release)
    controller_result, deployment_result = _owner_results(release=release)
    authority = SecuredQueryReceiptAuthority()
    for query_result in (secured, controller_result, deployment_result):
        authority.issue(query_result)
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        kubernetes_pod_recovery_function(
            release,
            receipt_verifier=authority,
            verification_context=authority.verification_context,
        ),
    )
    context = FunctionInvocationContext(
        caller_agent="Heimdall",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
        evidence_refs=tuple(
            sorted(
                result.receipt.projected_result_digest
                for result in (secured, controller_result, deployment_result)
            )
        ),
    )

    held = await registry.invoke(
        KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
        {
            "pod_query_result": secured.model_dump(mode="json"),
            "controller_query_result": controller_result.model_dump(mode="json"),
            "deployment_query_result": deployment_result.model_dump(mode="json"),
            "restart_history": _restart_history(),
            "diagnosis_result": {
                "rows": [],
                "complete": False,
                "truncation_reason": "log_window_unavailable",
            },
        },
        context=context,
    )

    assert isinstance(held, KubernetesPodRecoveryEvidenceResult)
    assert held.status is KubernetesPodRecoveryStatus.INSUFFICIENT_EVIDENCE
    assert held.complete is False
    assert held.recovery_verified is False
    assert "pod_diagnosis_log_window_unavailable" in held.evidence_gaps

    answered = await registry.invoke(
        KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
        {
            "pod_query_result": secured.model_dump(mode="json"),
            "controller_query_result": controller_result.model_dump(mode="json"),
            "deployment_query_result": deployment_result.model_dump(mode="json"),
            "restart_history": _restart_history(),
            "diagnosis_result": {
                "rows": [
                    {
                        "row_id": "kubernetes-pod-diagnosis",
                        "values": {"evidence_refs": ["kubernetes-pod-diagnosis:example"]},
                    }
                ],
                "complete": True,
                "truncation_reason": None,
            },
        },
        context=context,
    )

    assert isinstance(answered, KubernetesPodRecoveryEvidenceResult)
    assert answered.status is KubernetesPodRecoveryStatus.RECOVERED
    assert answered.recovery_verified is True
    assert "kubernetes-pod-diagnosis:example" in answered.evidence_refs


async def test_pod_lifecycle_cohort_query_uses_secured_controller_lineage() -> None:
    resource = _resource_type()
    declaration = kubernetes_pod_lifecycle_cohort_function_type()
    release = build_ontology_release(
        object_types=(resource,),
        function_types=(declaration,),
    )
    secured = _secured(release=release)
    controller_result, deployment_result = _owner_results(release=release)
    authority = SecuredQueryReceiptAuthority()
    query_results = (secured, controller_result, deployment_result)
    for query_result in query_results:
        authority.issue(query_result)

    class _Reader:
        async def read_pod_lifecycle_cohort(self, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs == {
                "current_pod_id": _POD_ID,
                "current_pod_uid": "pod-uid-new",
                "namespace": "default",
                "root_controller_uid": "deployment-uid",
                "lookback_seconds": 1800,
                "observed_at": _CUTOFF,
            }
            return {
                "complete": True,
                "truncation_reason": None,
                "current_pod_uid": "pod-uid-new",
                "root_controller_uid": "deployment-uid",
                "window_start": (_CUTOFF - timedelta(minutes=30)).isoformat(),
                "rows": [],
                "attempt_ref": "cohort-attempt",
                "execution_authority": False,
            }

    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        kubernetes_pod_lifecycle_cohort_function(
            release,
            reader=_Reader(),
            receipt_verifier=authority,
            verification_context=authority.verification_context,
        ),
    )
    context = FunctionInvocationContext(
        caller_agent="Heimdall",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
        evidence_refs=tuple(
            sorted(result.receipt.projected_result_digest for result in query_results)
        ),
    )

    result = await registry.invoke(
        KUBERNETES_POD_LIFECYCLE_COHORT_FUNCTION_NAME,
        {
            "pod_query_result": secured.model_dump(mode="json"),
            "controller_query_result": controller_result.model_dump(mode="json"),
            "deployment_query_result": deployment_result.model_dump(mode="json"),
            "lookback_seconds": 1800,
        },
        context=context,
    )

    assert result["root_controller_uid"] == "deployment-uid"  # type: ignore[index]
