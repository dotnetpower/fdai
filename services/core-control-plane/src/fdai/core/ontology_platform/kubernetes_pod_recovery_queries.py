"""Issued exact-release Kubernetes Pod restart and recovery evidence query."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
    OntologyReleaseRef,
)
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    STATE_FACT_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactMetadata,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext
from .kubernetes_lifecycle_observation import KubernetesLifecycleObservation
from .kubernetes_pod_recovery_evidence import (
    KubernetesPodRecoveryEvidenceResult,
    KubernetesPodRecoveryStatus,
    PodOwnerDeploymentObservation,
    PodRecoveryObservation,
    PodRestartHistoryObservation,
    evaluate_kubernetes_pod_recovery,
)
from .kubernetes_pod_replacement_evidence import (
    KubernetesPodReplacementEvidenceResult,
    KubernetesPodReplacementStatus,
    PodLifecycleObservation,
    PodReplacementDeploymentObservation,
    evaluate_kubernetes_pod_replacement_from_lifecycle,
)
from .network_path import NetworkQueryReceiptVerifier
from .query_gateway import SecuredObjectSetQueryResult

KUBERNETES_POD_RECOVERY_FUNCTION_NAME = "query.kubernetes_pod_recovery_evidence"
KUBERNETES_POD_RECOVERY_PURPOSE = "operations-review"
KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT = "pod.restart"
KUBERNETES_POD_RESTART_HISTORY_CONCEPT = "pod.restart.history"


def _source_artifact_digest() -> str:
    source = Path(__file__).read_bytes()
    reducer = Path(__file__).with_name("kubernetes_pod_recovery_evidence.py").read_bytes()
    # ``_apply_confirmed_replacement`` and ``_default_replacement_context``
    # invoke the exact-target replacement reducer directly, so its behavior
    # is part of this function's declared artifact and MUST be included in
    # the digest alongside the restart-recovery reducer above.
    replacement_reducer = (
        Path(__file__).with_name("kubernetes_pod_replacement_evidence.py").read_bytes()
    )
    digest = hashlib.sha256(source + b"\0" + reducer + b"\0" + replacement_reducer)
    return f"sha256:{digest.hexdigest()}"


def kubernetes_pod_recovery_function_type() -> OntologyFunctionType:
    """Return the read-only deterministic Pod recovery declaration."""

    return OntologyFunctionType(
        name=KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
        version="1.4.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=_source_artifact_digest(),
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "pod_query_result",
                "controller_query_result",
                "deployment_query_result",
                "restart_history",
            ],
            "properties": {
                "pod_query_result": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "controller_query_result": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "deployment_query_result": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "restart_history": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "lifecycle_cohort": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "replacement_context": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "replacement_old_pod_query_result": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "replacement_candidates_query_result": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "diagnosis_result": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "cutoff": {"type": "string", "format": "date-time"},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "pod_id",
                "status",
                "complete",
                "restart_observed",
                "recovery_verified",
                "restart_history_complete",
                "restart_observed_in_window",
                "restart_delta",
                "restart_window_start",
                "restart_window_end",
                "owner_deployment_id",
                "deployment_recovery_verified",
                "waiting_reasons",
                "evidence_gaps",
                "evidence_refs",
                "cause_claim_supported",
                "execution_authority",
                "replacement_recovery_verified",
            ],
            "properties": {
                "pod_id": {"type": "string"},
                "status": {
                    "enum": [
                        "restart_observed_recovered",
                        "restart_observed_not_recovered",
                        "insufficient_evidence",
                        "conflicting_evidence",
                    ]
                },
                "complete": {"type": "boolean"},
                "restart_observed": {"type": "boolean"},
                "recovery_verified": {"type": "boolean"},
                "phase": {"type": ["string", "null"]},
                "ready": {"type": ["boolean", "null"]},
                "container_count": {"type": ["integer", "null"], "minimum": 0},
                "ready_container_count": {"type": ["integer", "null"], "minimum": 0},
                "restart_count": {"type": ["integer", "null"], "minimum": 0},
                "restart_history_complete": {"type": "boolean"},
                "restart_observed_in_window": {"type": "boolean"},
                "restart_delta": {"type": ["integer", "null"], "minimum": 0},
                "restart_window_start": {"type": "string", "format": "date-time"},
                "restart_window_end": {"type": "string", "format": "date-time"},
                "owner_deployment_id": {"type": "string"},
                "desired_replicas": {"type": ["integer", "null"], "minimum": 0},
                "ready_replicas": {"type": ["integer", "null"], "minimum": 0},
                "available_replicas": {"type": ["integer", "null"], "minimum": 0},
                "unavailable_replicas": {"type": ["integer", "null"], "minimum": 0},
                "deployment_recovery_verified": {"type": "boolean"},
                "waiting_reasons": {"type": "array", "maxItems": 32},
                "evidence_gaps": {"type": "array", "maxItems": 64},
                "evidence_refs": {"type": "array", "maxItems": 128},
                "cause_claim_supported": {"const": False},
                "execution_authority": {"const": False},
                "replacement_recovery_verified": {"type": "boolean"},
            },
        },
        read_sets=["Resource", "kubernetes_owned_by"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[KUBERNETES_POD_RECOVERY_PURPOSE],
        timeout_seconds=5,
        cpu_millis=1000,
        memory_bytes=134_217_728,
        max_output_bytes=131_072,
        network_allowed=False,
        credentials_allowed=False,
    )


def kubernetes_pod_recovery_function(
    ontology_release: OntologyRelease,
    *,
    receipt_verifier: NetworkQueryReceiptVerifier,
    verification_context: object,
) -> ContextualOntologyFunction:
    """Bind Pod recovery assessment to one composition-issued secured result."""

    if verification_context is None:
        raise ValueError("Kubernetes Pod recovery verification context MUST be non-null")
    expected_release = ontology_release.ref()

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        pod_result = SecuredObjectSetQueryResult.model_validate(arguments["pod_query_result"])
        controller_result = SecuredObjectSetQueryResult.model_validate(
            arguments["controller_query_result"]
        )
        deployment_result = SecuredObjectSetQueryResult.model_validate(
            arguments["deployment_query_result"]
        )
        replacement_old_result = _optional_secured_result(
            arguments.get("replacement_old_pod_query_result")
        )
        replacement_candidates_result = _optional_secured_result(
            arguments.get("replacement_candidates_query_result")
        )
        query_results = (
            pod_result,
            controller_result,
            deployment_result,
            *((replacement_old_result,) if replacement_old_result is not None else ()),
            *(
                (replacement_candidates_result,)
                if replacement_candidates_result is not None
                else ()
            ),
        )
        expected_evidence_refs = tuple(
            sorted(result.receipt.projected_result_digest for result in query_results)
        )
        for query_result in query_results:
            _authenticate_query_receipt(
                query_result,
                invocation_context=invocation_context,
                expected_release=expected_release,
                expected_evidence_refs=expected_evidence_refs,
                receipt_verifier=receipt_verifier,
                verification_context=verification_context,
            )
        cutoff = (
            datetime.fromisoformat(str(arguments["cutoff"]).replace("Z", "+00:00"))
            if "cutoff" in arguments
            else pod_result.receipt.observation_cutoff
        )
        if cutoff.tzinfo is None or any(
            cutoff != result.receipt.observation_cutoff for result in query_results
        ):
            raise ValueError("Kubernetes Pod recovery cutoff MUST equal the secured query cutoff")
        result = evaluate_kubernetes_pod_recovery_graph(
            pod_result,
            controller_result=controller_result,
            deployment_result=deployment_result,
            restart_history=arguments["restart_history"],
            cutoff=cutoff,
        )
        lifecycle_cohort = arguments.get("lifecycle_cohort")
        if isinstance(lifecycle_cohort, Mapping) and lifecycle_cohort.get("complete") is False:
            reason = lifecycle_cohort.get("truncation_reason")
            gap = (
                f"lifecycle_cohort_{reason}"
                if isinstance(reason, str) and reason
                else "lifecycle_cohort_incomplete"
            )
            result = result.model_copy(
                update={
                    "complete": False,
                    "recovery_verified": False,
                    "status": (
                        result.status
                        if result.status is KubernetesPodRecoveryStatus.CONFLICTING_EVIDENCE
                        else KubernetesPodRecoveryStatus.INSUFFICIENT_EVIDENCE
                    ),
                    "evidence_gaps": tuple(dict.fromkeys((*result.evidence_gaps, gap))),
                }
            )
        elif isinstance(lifecycle_cohort, Mapping) and lifecycle_cohort.get("complete") is True:
            replacement_context = arguments.get("replacement_context")
            explicit_replacement_context = replacement_context is not None
            if (
                replacement_context is None
                and replacement_old_result is not None
                and replacement_candidates_result is not None
            ):
                replacement_context = _replacement_context_from_query_results(
                    replacement_old_result,
                    replacement_candidates_result,
                    deployment_result=deployment_result,
                    cutoff=cutoff,
                )
            if replacement_context is None:
                replacement_context = _default_replacement_context(
                    pod_result,
                    deployment_result=deployment_result,
                    lifecycle_cohort=lifecycle_cohort,
                    candidate_result=replacement_candidates_result,
                )
            historical_identity_present = explicit_replacement_context or bool(
                _historical_replacement_rows(pod_result, lifecycle_cohort)
            )
            if replacement_context is None:
                if historical_identity_present:
                    # A distinct predecessor UID is on record but a replacement
                    # narrative could not be derived from it: a genuine gap.
                    result = result.model_copy(
                        update={
                            "complete": False,
                            "recovery_verified": False,
                            "status": KubernetesPodRecoveryStatus.INSUFFICIENT_EVIDENCE,
                            "evidence_gaps": tuple(
                                dict.fromkeys(
                                    (*result.evidence_gaps, "replacement_evidence_unavailable")
                                )
                            ),
                        }
                    )
                # else: the retained cohort holds only the current Pod's own
                # identity. That is a legitimate same-UID restart, not missing
                # replacement evidence, so the base result stands unchanged.
            elif isinstance(replacement_context, Mapping):
                replacement = _replacement_from_context(
                    replacement_context,
                    lifecycle_cohort=lifecycle_cohort,
                    cutoff=cutoff,
                )
                if replacement is not None and replacement.evidence_gaps:
                    result = result.model_copy(
                        update={
                            "complete": False,
                            "recovery_verified": False,
                            "status": (
                                KubernetesPodRecoveryStatus.CONFLICTING_EVIDENCE
                                if replacement.status
                                is KubernetesPodReplacementStatus.CONFLICTING_EVIDENCE
                                or result.status is KubernetesPodRecoveryStatus.CONFLICTING_EVIDENCE
                                else KubernetesPodRecoveryStatus.INSUFFICIENT_EVIDENCE
                            ),
                            "evidence_gaps": tuple(
                                dict.fromkeys(
                                    (
                                        *result.evidence_gaps,
                                        "replacement_evidence_"
                                        + "+".join(replacement.evidence_gaps),
                                    )
                                )
                            ),
                        }
                    )
                elif replacement is not None and replacement.recovery_verified:
                    result = _apply_confirmed_replacement(result, replacement)
        diagnosis_result = arguments.get("diagnosis_result")
        if isinstance(diagnosis_result, Mapping) and diagnosis_result.get("complete") is False:
            reason = diagnosis_result.get("truncation_reason")
            gap = (
                f"pod_diagnosis_{reason}"
                if isinstance(reason, str) and reason
                else "pod_diagnosis_incomplete"
            )
            result = result.model_copy(
                update={
                    "complete": False,
                    "recovery_verified": False,
                    "status": (
                        result.status
                        if result.status is KubernetesPodRecoveryStatus.CONFLICTING_EVIDENCE
                        else KubernetesPodRecoveryStatus.INSUFFICIENT_EVIDENCE
                    ),
                    "evidence_gaps": tuple(dict.fromkeys((*result.evidence_gaps, gap))),
                }
            )
        elif isinstance(diagnosis_result, Mapping) and diagnosis_result.get("complete") is True:
            diagnosis_refs = _diagnosis_evidence_refs(diagnosis_result)
            if diagnosis_refs:
                result = result.model_copy(
                    update={
                        "evidence_refs": tuple(
                            dict.fromkeys((*result.evidence_refs, *diagnosis_refs))
                        ),
                    }
                )
        return result

    return evaluate


def evaluate_kubernetes_pod_recovery_graph(
    secured: SecuredObjectSetQueryResult,
    *,
    controller_result: SecuredObjectSetQueryResult,
    deployment_result: SecuredObjectSetQueryResult,
    restart_history: object,
    cutoff: datetime,
) -> KubernetesPodRecoveryEvidenceResult:
    """Assess one exact secured Pod without provider I/O."""

    if cutoff.tzinfo is None:
        raise ValueError("Kubernetes Pod recovery cutoff MUST be timezone-aware")
    if secured.receipt.purpose != KUBERNETES_POD_RECOVERY_PURPOSE:
        raise ValueError("secured Pod recovery graph has the wrong purpose")
    objects = secured.materialization.graph.objects
    if len(objects) != 1:
        raise ValueError("secured Pod recovery query MUST return one Pod")
    pod = objects[0]
    if _resource_type(pod) != "kubernetes.pod":
        raise ValueError("secured Pod recovery target is not a Kubernetes Pod")
    properties = _resource_properties(pod)
    history = _restart_history_observation(restart_history, pod_id=pod.id)
    owner_deployment, ownership_gaps, ownership_refs = _owner_deployment_observation(
        pod=pod,
        controller_result=controller_result,
        deployment_result=deployment_result,
        cutoff=cutoff,
    )
    ready = properties.get("ready")
    if ready is not None and not isinstance(ready, bool):
        raise ValueError("Pod ready evidence MUST be boolean or null")
    reasons = properties.get("container_waiting_reasons", ())
    if not isinstance(reasons, Sequence) or isinstance(reasons, (str, bytes)):
        raise ValueError("Pod waiting reasons MUST be a sequence")
    query_results = (secured, controller_result, deployment_result)
    result = evaluate_kubernetes_pod_recovery(
        pod=PodRecoveryObservation(
            pod_id=pod.id,
            phase=_optional_text(properties, "phase"),
            ready=ready,
            container_count=_optional_int(properties, "container_count"),
            ready_container_count=_optional_int(properties, "ready_container_count"),
            restart_count=_optional_int(properties, "restart_count"),
            waiting_reasons=tuple(str(reason) for reason in reasons),
            metadata=_state_metadata(pod),
        ),
        restart_history=history,
        owner_deployment=owner_deployment,
        cutoff=cutoff,
        graph_complete=all(
            result.receipt.complete and not result.materialization.graph.truncated
            for result in query_results
        ),
        ownership_complete=not ownership_gaps,
    )
    evidence_refs = tuple(sorted(set((*result.evidence_refs, *ownership_refs))))
    if not ownership_gaps:
        return result.model_copy(update={"evidence_refs": evidence_refs})

    return result.model_copy(
        update={
            "complete": False,
            "recovery_verified": False,
            "evidence_gaps": tuple(dict.fromkeys((*result.evidence_gaps, *ownership_gaps))),
            "evidence_refs": evidence_refs,
        }
    )


def evaluate_kubernetes_pod_replacement_graph(
    *,
    old_pod: PodLifecycleObservation,
    candidates: tuple[PodLifecycleObservation, ...],
    lifecycle_observations: tuple[KubernetesLifecycleObservation, ...],
    deployment: PodReplacementDeploymentObservation | None,
    correlation_window_start: datetime,
    cutoff: datetime,
) -> KubernetesPodReplacementEvidenceResult:
    """Run the exact-target replacement reducer over retained lifecycle evidence."""

    return evaluate_kubernetes_pod_replacement_from_lifecycle(
        old_pod=old_pod,
        candidates=candidates,
        lifecycle_observations=lifecycle_observations,
        deployment=deployment,
        correlation_window_start=correlation_window_start,
        cutoff=cutoff,
    )


def _replacement_from_context(
    context: Mapping[str, Any],
    *,
    lifecycle_cohort: Mapping[str, Any],
    cutoff: datetime,
) -> KubernetesPodReplacementEvidenceResult | None:
    """Parse an exact replacement dependency bundle and invoke the reducer."""

    old_pod = _replacement_pod(context.get("old_pod"))
    raw_candidates = context.get("candidates")
    if (
        old_pod is None
        or not isinstance(raw_candidates, Sequence)
        or isinstance(raw_candidates, (str, bytes))
    ):
        raise ValueError("replacement context MUST contain old_pod and candidates")
    candidates = tuple(_replacement_pod(item) for item in raw_candidates)
    if any(item is None for item in candidates):
        raise ValueError("replacement context candidates MUST be valid Pods")
    deployment = _replacement_deployment(context.get("deployment"))
    raw_rows = lifecycle_cohort.get("rows")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise ValueError("lifecycle_cohort rows MUST be a sequence")
    observations = tuple(
        _lifecycle_observation(row.get("values")) for row in raw_rows if isinstance(row, Mapping)
    )
    if any(item is None for item in observations):
        raise ValueError("lifecycle_cohort rows MUST contain typed observations")
    window_start = _required_time(context, "correlation_window_start")
    return evaluate_kubernetes_pod_replacement_graph(
        old_pod=old_pod,
        candidates=tuple(item for item in candidates if item is not None),
        lifecycle_observations=tuple(item for item in observations if item is not None),
        deployment=deployment,
        correlation_window_start=window_start,
        cutoff=cutoff,
    )


def _historical_replacement_rows(
    pod_result: SecuredObjectSetQueryResult,
    lifecycle_cohort: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    """Return retained cohort rows recording this exact Pod's predecessor.

    An empty result legitimately means the retained cohort observed only the
    current Pod's own identity: a same-UID restart, not a replacement. That
    absence MUST NOT be conflated with missing replacement evidence.

    The durable cohort spans every Pod identity under the same root
    controller, so a sibling Pod under the same Deployment/ReplicaSet can
    share ``owner_uid``/``root_controller_uid`` with the current target
    while being a wholly unrelated replica. Timing and shared ownership
    alone MUST NOT correlate a row to this exact Pod's predecessor: a row is
    only accepted when it also carries the current target's own ``pod_id``,
    binding it to this exact Pod's identity slot rather than an arbitrary
    sibling.
    """

    pod_objects = pod_result.materialization.graph.objects
    if len(pod_objects) != 1:
        return ()
    pod = pod_objects[0]
    properties = _resource_properties(pod)
    current_uid = properties.get("uid")
    if not isinstance(current_uid, str) or not current_uid.strip():
        return ()
    raw_rows = lifecycle_cohort.get("rows")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        return ()
    typed_rows: tuple[Mapping[str, Any], ...] = tuple(
        cast(Mapping[str, Any], row["values"])
        for row in raw_rows
        if isinstance(row, Mapping) and isinstance(row.get("values"), Mapping)
    )
    return tuple(
        row
        for row in typed_rows
        if isinstance(row.get("object_uid"), str)
        and row["object_uid"] != current_uid
        and row.get("pod_id") == pod.id
    )


def _apply_confirmed_replacement(
    result: KubernetesPodRecoveryEvidenceResult,
    replacement: KubernetesPodReplacementEvidenceResult,
) -> KubernetesPodRecoveryEvidenceResult:
    """Expose a conclusively verified distinct-UID replacement as its own lane.

    ``status``/``complete``/``recovery_verified`` answer one narrow question:
    was THIS Pod's own restart observed and did it recover? A same-UID
    container restart answers that question directly through its own
    restart count. A distinct-UID replacement is a completely different
    narrative -- a different Pod object replaced the failed one -- and MUST
    NOT be folded into those restart-status fields: doing so would represent
    "a different Pod recovered" as "this Pod's restart was observed and
    recovered", conflating two distinct claims. Once an independent
    distinct-UID replacement is conclusively verified
    (``replacement.recovery_verified``), it is instead surfaced through the
    dedicated ``replacement_recovery_verified`` field. The restart-status
    fields, including any ``restart_not_observed_in_*`` gaps, are left
    exactly as computed by ``evaluate_kubernetes_pod_recovery``.
    """

    if replacement.status not in (
        KubernetesPodReplacementStatus.POD_REPLACEMENT,
        KubernetesPodReplacementStatus.ROLLOUT_REPLACEMENT,
    ):
        return result
    if not replacement.recovery_verified:
        return result
    merged_refs = tuple(
        dict.fromkeys(
            (
                *result.evidence_refs,
                *replacement.historical_evidence_refs,
                *replacement.current_evidence_refs,
            )
        )
    )
    return result.model_copy(
        update={
            "replacement_recovery_verified": True,
            "evidence_refs": merged_refs,
        }
    )


def _diagnosis_evidence_refs(diagnosis_result: Mapping[str, Any]) -> tuple[str, ...]:
    """Extract evidence references recorded on a complete Pod diagnosis QueryTable."""

    rows = diagnosis_result.get("rows")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return ()
    refs: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        values = row.get("values")
        if not isinstance(values, Mapping):
            continue
        row_refs = values.get("evidence_refs")
        if not isinstance(row_refs, Sequence) or isinstance(row_refs, (str, bytes)):
            continue
        refs.extend(ref for ref in row_refs if isinstance(ref, str))
    return tuple(dict.fromkeys(refs))


def _default_replacement_context(
    pod_result: SecuredObjectSetQueryResult,
    *,
    deployment_result: SecuredObjectSetQueryResult,
    lifecycle_cohort: Mapping[str, Any],
    candidate_result: SecuredObjectSetQueryResult | None = None,
) -> Mapping[str, Any] | None:
    """Translate complete lifecycle rows into a conservative exact replacement bundle."""

    pod_objects = pod_result.materialization.graph.objects
    if len(pod_objects) != 1:
        return None
    pod = pod_objects[0]
    properties = _resource_properties(pod)
    old_rows = _historical_replacement_rows(pod_result, lifecycle_cohort)
    if not old_rows:
        return None
    old_uids = tuple(sorted({str(row["object_uid"]) for row in old_rows}))
    if len(old_uids) != 1:
        return None
    old_uid = old_uids[0]
    old_rows = tuple(row for row in old_rows if row["object_uid"] == old_uid)
    deployment_objects = tuple(
        item
        for item in deployment_result.materialization.graph.objects
        if _resource_type(item) == "kubernetes.deployment"
    )
    deployment = deployment_objects[0] if len(deployment_objects) == 1 else None
    if deployment is None:
        return None
    deployment_properties = _resource_properties(deployment)
    root_controller_uid = _required_replacement_text(deployment_properties, "uid")
    enriched_properties = dict(properties)
    enriched_properties.setdefault("owner_uid", properties.get("controller_uid"))
    enriched_properties.setdefault("root_controller_uid", root_controller_uid)
    enriched_properties.setdefault("root_controller_kind", "Deployment")
    pod = replace(
        pod,
        properties={**pod.properties, "properties": enriched_properties},
    )
    current_metadata = _state_metadata(pod).to_mapping()
    identity_observed_at = _required_replacement_time(old_rows[0], "identity_observed_at")
    identity_revision = _required_replacement_text(
        old_rows[0],
        "identity_source_revision",
    )
    old_metadata = dict(current_metadata)
    old_metadata.update(
        {
            "source_identity": "kubernetes-api-inventory",
            "source_revision": identity_revision,
            "effective_at": identity_observed_at.isoformat(),
            "recorded_at": identity_observed_at.isoformat(),
            "evidence_cutoff": identity_observed_at.isoformat(),
            "completeness": 1.0,
            "synthetic": False,
            "conflicts": (),
        }
    )
    old_metadata["evidence_refs"] = tuple(
        dict.fromkeys(
            (
                _required_replacement_text(old_rows[0], "identity_evidence_ref"),
                *(
                    str(row["evidence_ref"])
                    for row in old_rows
                    if isinstance(row.get("evidence_ref"), str)
                ),
            )
        )
    )
    current = _replacement_record(pod, metadata=current_metadata)
    if candidate_result is not None and (
        not candidate_result.receipt.complete
        or candidate_result.receipt.truncated
        or candidate_result.materialization.graph.truncated
    ):
        return None
    candidate_objects = (
        tuple(
            item
            for item in candidate_result.materialization.graph.objects
            if _resource_type(item) == "kubernetes.pod"
        )
        if candidate_result is not None
        else (pod,)
    )
    if not candidate_objects or len(candidate_objects) > 32:
        return None
    old = dict(current)
    old["pod_id"] = _required_replacement_text(old_rows[0], "pod_id")
    old["pod_uid"] = old_uid
    old["owner_uid"] = _required_replacement_text(old_rows[0], "owner_uid")
    old["root_controller_uid"] = _required_replacement_text(
        old_rows[0],
        "root_controller_uid",
    )
    old["root_controller_kind"] = _required_replacement_text(
        old_rows[0],
        "root_controller_kind",
    )
    old["created_at"] = None
    old["phase"] = None
    old["ready"] = None
    old["ready_container_count"] = None
    old["metadata"] = old_metadata
    # ``old`` starts as a copy of ``current`` (the CURRENT Pod's own
    # record), so its top-level "evidence_refs" still holds the current
    # Pod's own refs at this point. This is the historical predecessor's
    # record: it MUST carry only historical identity/lifecycle evidence,
    # never the current Pod's own evidence.
    old["evidence_refs"] = list(cast(tuple[str, ...], old_metadata["evidence_refs"]))
    return {
        "old_pod": old,
        "candidates": [
            _replacement_record(item, metadata=_state_metadata(item).to_mapping())
            for item in candidate_objects
        ],
        "deployment": {
            "deployment_id": deployment.id,
            # Only the CURRENT (post-replacement) Deployment snapshot is
            # observed here; no historical "before" snapshot exists. Copying
            # the current value into "before" would fabricate agreement
            # with "after" and let the reducer treat that manufactured
            # equality as proof no scaling occurred. Leave it unavailable.
            "desired_replicas_before": None,
            "desired_replicas_after": _optional_replacement_int(
                deployment_properties, "desired_replicas"
            ),
            "ready_replicas": _optional_replacement_int(deployment_properties, "ready_replicas"),
            "available_replicas": _optional_replacement_int(
                deployment_properties, "available_replicas"
            ),
            "unavailable_replicas": _optional_replacement_int(
                deployment_properties, "unavailable_replicas"
            ),
            "metadata": _state_metadata(deployment).to_mapping(),
            "evidence_refs": list(_state_metadata(deployment).evidence_refs),
        },
        "correlation_window_start": _required_time(
            lifecycle_cohort,
            "window_start",
        ).isoformat(),
    }


def _optional_secured_result(value: object) -> SecuredObjectSetQueryResult | None:
    if value is None:
        return None
    return SecuredObjectSetQueryResult.model_validate(value)


def _replacement_context_from_query_results(
    old_result: SecuredObjectSetQueryResult,
    candidates_result: SecuredObjectSetQueryResult,
    *,
    deployment_result: SecuredObjectSetQueryResult,
    cutoff: datetime,
) -> Mapping[str, Any] | None:
    """Translate bounded historical/current Pod query results into reducer input."""

    if any(
        not result.receipt.complete
        or result.receipt.truncated
        or result.materialization.graph.truncated
        for result in (old_result, candidates_result)
    ):
        return None
    old_objects = tuple(
        item
        for item in old_result.materialization.graph.objects
        if _resource_type(item) == "kubernetes.pod"
    )
    candidate_objects = tuple(
        item
        for item in candidates_result.materialization.graph.objects
        if _resource_type(item) == "kubernetes.pod"
    )
    if len(old_objects) != 1 or not candidate_objects or len(candidate_objects) > 32:
        return None
    deployment_objects = tuple(
        item
        for item in deployment_result.materialization.graph.objects
        if _resource_type(item) == "kubernetes.deployment"
    )
    if len(deployment_objects) != 1:
        return None
    deployment = deployment_objects[0]
    deployment_properties = _resource_properties(deployment)
    deployment_metadata = _state_metadata(deployment).to_mapping()
    return {
        "old_pod": _replacement_record(
            old_objects[0],
            metadata=_state_metadata(old_objects[0]).to_mapping(),
        ),
        "candidates": [
            _replacement_record(
                item,
                metadata=_state_metadata(item).to_mapping(),
            )
            for item in candidate_objects
        ],
        "deployment": {
            "deployment_id": deployment.id,
            # Only the CURRENT (post-replacement) Deployment snapshot is
            # observed here; no historical "before" snapshot exists. Copying
            # the current value into "before" would fabricate agreement
            # with "after" and let the reducer treat that manufactured
            # equality as proof no scaling occurred. Leave it unavailable.
            "desired_replicas_before": None,
            "desired_replicas_after": _optional_replacement_int(
                deployment_properties, "desired_replicas"
            ),
            "ready_replicas": _optional_replacement_int(deployment_properties, "ready_replicas"),
            "available_replicas": _optional_replacement_int(
                deployment_properties, "available_replicas"
            ),
            "unavailable_replicas": _optional_replacement_int(
                deployment_properties, "unavailable_replicas"
            ),
            "metadata": deployment_metadata,
            "evidence_refs": list(cast(tuple[str, ...], deployment_metadata["evidence_refs"])),
        },
        "correlation_window_start": (cutoff - timedelta(minutes=30)).isoformat(),
    }


def _replacement_record(
    record: OntologyObjectRecord,
    *,
    metadata: Mapping[str, Any],
) -> dict[str, object]:
    """Return the bounded Pod fields used by the replacement reducer."""

    properties = _resource_properties(record)
    return {
        "pod_id": record.id,
        "pod_uid": _required_replacement_text(properties, "uid"),
        "cluster_id": _required_replacement_text(properties, "cluster_ref"),
        "namespace": _required_replacement_text(properties, "namespace"),
        "owner_uid": _optional_replacement_text(properties, "owner_uid"),
        "root_controller_uid": _optional_replacement_text(properties, "root_controller_uid"),
        "root_controller_kind": _optional_replacement_text(properties, "root_controller_kind"),
        "created_at": _optional_replacement_time(properties, "created_at"),
        "phase": _optional_replacement_text(properties, "phase"),
        "ready": properties.get("ready") if isinstance(properties.get("ready"), bool) else None,
        "container_count": _optional_replacement_int(properties, "container_count"),
        "ready_container_count": _optional_replacement_int(properties, "ready_container_count"),
        "waiting_reasons": _replacement_text_tuple(
            {"waiting_reasons": properties.get("container_waiting_reasons", ())},
            "waiting_reasons",
        ),
        "workload_revision": _optional_replacement_text(properties, "workload_revision"),
        "metadata": metadata,
        "evidence_refs": list(metadata["evidence_refs"]),
    }


def _replacement_pod(value: object) -> PodLifecycleObservation | None:
    if not isinstance(value, Mapping):
        return None
    metadata = value.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    return PodLifecycleObservation(
        pod_id=_required_replacement_text(value, "pod_id"),
        pod_uid=_required_replacement_text(value, "pod_uid"),
        cluster_id=_required_replacement_text(value, "cluster_id"),
        namespace=_required_replacement_text(value, "namespace"),
        owner_uid=_optional_replacement_text(value, "owner_uid"),
        root_controller_uid=_optional_replacement_text(value, "root_controller_uid"),
        root_controller_kind=_optional_replacement_text(value, "root_controller_kind"),
        created_at=_optional_replacement_time(value, "created_at"),
        phase=_optional_replacement_text(value, "phase"),
        ready=value.get("ready") if isinstance(value.get("ready"), bool) else None,
        container_count=_optional_replacement_int(value, "container_count"),
        ready_container_count=_optional_replacement_int(value, "ready_container_count"),
        waiting_reasons=_replacement_text_tuple(value, "waiting_reasons"),
        workload_revision=_optional_replacement_text(value, "workload_revision"),
        metadata=StateFactMetadata.from_mapping(metadata),
        evidence_refs=_replacement_text_tuple(value, "evidence_refs"),
    )


def _replacement_deployment(value: object) -> PodReplacementDeploymentObservation | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or not isinstance(value.get("metadata"), Mapping):
        raise ValueError("replacement deployment context MUST be typed")
    return PodReplacementDeploymentObservation(
        deployment_id=_required_replacement_text(value, "deployment_id"),
        desired_replicas_before=_optional_replacement_int(value, "desired_replicas_before"),
        desired_replicas_after=_optional_replacement_int(value, "desired_replicas_after"),
        ready_replicas=_optional_replacement_int(value, "ready_replicas"),
        available_replicas=_optional_replacement_int(value, "available_replicas"),
        unavailable_replicas=_optional_replacement_int(value, "unavailable_replicas"),
        metadata=StateFactMetadata.from_mapping(value["metadata"]),
        evidence_refs=_replacement_text_tuple(value, "evidence_refs"),
    )


def _lifecycle_observation(value: object) -> KubernetesLifecycleObservation | None:
    if not isinstance(value, Mapping):
        return None
    return KubernetesLifecycleObservation(
        cluster_ref=_required_replacement_text(value, "cluster_ref"),
        namespace=_optional_replacement_text(value, "namespace"),
        object_uid=_required_replacement_text(value, "object_uid"),
        owner_uid=_optional_replacement_text(value, "owner_uid"),
        reason=_required_replacement_alias(value, "reason", "event_kind"),
        category=_required_replacement_alias(value, "category", "classification"),
        event_type=_required_replacement_alias(value, "event_type", "status"),
        event_time=_required_replacement_alias_time(value, "event_time", "occurred_at"),
        recorded_time=_required_replacement_alias_time(
            value,
            "recorded_time",
            "recorded_at",
        ),
        source_revision=_required_replacement_text(value, "source_revision"),
        evidence_ref=_required_replacement_text(value, "evidence_ref"),
    )


def _required_time(value: Mapping[str, Any], key: str) -> datetime:
    parsed = _parse_time(value.get(key))
    if parsed is None:
        raise ValueError(f"{key} MUST be an ISO timestamp")
    return parsed


def _required_replacement_text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"replacement {key} MUST be non-empty text")
    return item.strip()


def _required_replacement_alias(value: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        if isinstance(value.get(key), str) and value[key].strip():
            return str(value[key]).strip()
    raise ValueError(f"replacement {keys[0]} MUST be non-empty text")


def _required_replacement_alias_time(value: Mapping[str, Any], *keys: str) -> datetime:
    for key in keys:
        parsed = _parse_time(value.get(key))
        if parsed is not None:
            return parsed
    raise ValueError(f"replacement {keys[0]} MUST be an ISO timestamp")


def _optional_replacement_text(value: Mapping[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    return _required_replacement_text(value, key)


def _optional_replacement_int(value: Mapping[str, Any], key: str) -> int | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError(f"replacement {key} MUST be a non-negative integer")
    return item


def _replacement_text_tuple(value: Mapping[str, Any], key: str) -> tuple[str, ...]:
    item = value.get(key)
    if not isinstance(item, Sequence) or isinstance(item, (str, bytes)):
        raise ValueError(f"replacement {key} MUST be a sequence")
    result = tuple(str(entry).strip() for entry in item)
    if any(not entry for entry in result):
        raise ValueError(f"replacement {key} MUST contain non-empty text")
    return result


def _required_replacement_time(value: Mapping[str, Any], key: str) -> datetime:
    parsed = _parse_time(value.get(key))
    if parsed is None:
        raise ValueError(f"replacement {key} MUST be an ISO timestamp")
    return parsed


def _optional_replacement_time(value: Mapping[str, Any], key: str) -> datetime | None:
    if value.get(key) is None:
        return None
    return _required_replacement_time(value, key)


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("replacement timestamps MUST include timezone")
        return value
    if not isinstance(value, str):
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("replacement timestamps MUST include timezone")
    return parsed


def _owner_deployment_observation(
    *,
    pod: OntologyObjectRecord,
    controller_result: SecuredObjectSetQueryResult,
    deployment_result: SecuredObjectSetQueryResult,
    cutoff: datetime,
) -> tuple[PodOwnerDeploymentObservation, tuple[str, ...], tuple[str, ...]]:
    controller_graph = controller_result.materialization.graph
    if controller_result.materialization.definition.root_ids != (pod.id,):
        raise ValueError("secured Pod controller query has the wrong root")
    replica_sets = tuple(
        record
        for record in controller_graph.objects
        if _resource_type(record) == "kubernetes.replica-set"
    )
    if len(replica_sets) != 1:
        raise ValueError("secured Pod controller query MUST return one ReplicaSet")
    replica_set = replica_sets[0]
    pod_links = tuple(
        link
        for link in controller_graph.links
        if link.link_type == "kubernetes_owned_by"
        and link.from_id == pod.id
        and link.to_id == replica_set.id
    )
    if len(pod_links) != 1:
        raise ValueError("secured Pod controller ownership path is invalid")

    deployment_graph = deployment_result.materialization.graph
    if deployment_result.materialization.definition.root_ids != (replica_set.id,):
        raise ValueError("secured Pod Deployment query has the wrong controller root")
    deployments = tuple(
        record
        for record in deployment_graph.objects
        if _resource_type(record) == "kubernetes.deployment"
    )
    if len(deployments) != 1:
        raise ValueError("secured Pod Deployment query MUST return one Deployment")
    deployment = deployments[0]
    deployment_links = tuple(
        link
        for link in deployment_graph.links
        if link.link_type == "kubernetes_owned_by"
        and link.from_id == replica_set.id
        and link.to_id == deployment.id
    )
    if len(deployment_links) != 1:
        raise ValueError("secured Pod Deployment ownership path is invalid")
    gaps, references = _ownership_evidence((*pod_links, *deployment_links), cutoff=cutoff)
    deployment_properties = _resource_properties(deployment)
    return (
        PodOwnerDeploymentObservation(
            deployment_id=deployment.id,
            desired_replicas=_optional_int(deployment_properties, "desired_replicas"),
            ready_replicas=_optional_int(deployment_properties, "ready_replicas"),
            available_replicas=_optional_int(deployment_properties, "available_replicas"),
            unavailable_replicas=_optional_int(
                deployment_properties,
                "unavailable_replicas",
            ),
            metadata=_state_metadata(deployment),
        ),
        gaps,
        references,
    )


def _ownership_evidence(
    links: tuple[OntologyLinkRecord, ...],
    *,
    cutoff: datetime,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    gaps: list[str] = []
    references: set[str] = set()
    for link in links:
        raw = link.properties.get(LINK_OBSERVATION_METADATA_PROPERTY)
        if not isinstance(raw, Mapping):
            gaps.append("pod_ownership_evidence_missing")
            continue
        metadata = LinkObservationMetadata.from_mapping(raw)
        references.update(metadata.state_fact.evidence_refs)
        if metadata.verification_receipt_ref is not None:
            references.add(metadata.verification_receipt_ref)
        if not metadata.verified:
            gaps.append("pod_ownership_evidence_unverified")
        evidence_cutoff = metadata.state_fact.evidence_cutoff.astimezone(UTC)
        normalized_cutoff = cutoff.astimezone(UTC)
        if evidence_cutoff > normalized_cutoff:
            gaps.append("pod_ownership_evidence_after_cutoff")
        elif (
            normalized_cutoff - evidence_cutoff
        ).total_seconds() > metadata.state_fact.freshness_ceiling_seconds:
            gaps.append("pod_ownership_evidence_stale")
        if metadata.state_fact.completeness < 1.0:
            gaps.append("pod_ownership_evidence_incomplete")
        if metadata.state_fact.synthetic:
            gaps.append("pod_ownership_evidence_synthetic")
        if metadata.state_fact.conflicts:
            gaps.append("pod_ownership_evidence_conflicting")
    return tuple(dict.fromkeys(gaps)), tuple(sorted(references))


def _restart_history_observation(
    value: object,
    *,
    pod_id: str,
) -> PodRestartHistoryObservation:
    if not isinstance(value, Mapping):
        raise ValueError("Pod restart history metric window is invalid")
    if (
        value.get("concept_id") != KUBERNETES_POD_RESTART_HISTORY_CONCEPT
        or value.get("resource_id") != pod_id
        or value.get("unit") != "count"
    ):
        raise ValueError("Pod restart history metric identity is invalid")
    start = _timestamp(value.get("start"), "restart_history.start")
    end = _timestamp(value.get("end"), "restart_history.end")
    complete = value.get("complete")
    missing_reason = value.get("missing_reason")
    if not isinstance(complete, bool) or (
        missing_reason is not None and not isinstance(missing_reason, str)
    ):
        raise ValueError("Pod restart history completeness is invalid")
    raw_samples = value.get("samples")
    if not isinstance(raw_samples, Sequence) or isinstance(raw_samples, (str, bytes)):
        raise ValueError("Pod restart history samples are invalid")
    total = 0.0
    for sample in raw_samples:
        if not isinstance(sample, Mapping):
            raise ValueError("Pod restart history sample is invalid")
        sample_value = sample.get("value")
        if isinstance(sample_value, bool) or not isinstance(sample_value, int | float):
            raise ValueError("Pod restart history sample value is invalid")
        converted = float(sample_value)
        if not math.isfinite(converted) or converted < 0:
            raise ValueError("Pod restart history sample value is invalid")
        total += converted
    if not total.is_integer():
        raise ValueError("Pod restart history delta MUST be an integer count")
    raw_refs = value.get("evidence_refs")
    if (
        not isinstance(raw_refs, Sequence)
        or isinstance(raw_refs, (str, bytes))
        or any(not isinstance(item, str) or not item for item in raw_refs)
    ):
        raise ValueError("Pod restart history evidence references are invalid")
    return PodRestartHistoryObservation(
        pod_id=pod_id,
        start=start,
        end=end,
        restart_delta=int(total) if complete else None,
        complete=complete,
        missing_reason=missing_reason,
        evidence_refs=tuple(raw_refs),
    )


def _timestamp(value: object, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} MUST be an RFC 3339 timestamp") from exc
    else:
        raise ValueError(f"{field} MUST be an RFC 3339 timestamp")
    if parsed.tzinfo is None:
        raise ValueError(f"{field} MUST be timezone-aware")
    return parsed


def _authenticate_query_receipt(
    query_result: SecuredObjectSetQueryResult,
    *,
    invocation_context: FunctionInvocationContext,
    expected_release: OntologyReleaseRef,
    expected_evidence_refs: tuple[str, ...],
    receipt_verifier: NetworkQueryReceiptVerifier,
    verification_context: object,
) -> None:
    receipt = query_result.receipt
    expected_digest = receipt.projected_result_digest
    if receipt.ontology_release != expected_release:
        raise ValueError("Kubernetes Pod recovery result has the wrong ontology release")
    if receipt.purpose != KUBERNETES_POD_RECOVERY_PURPOSE:
        raise ValueError("Kubernetes Pod recovery result has the wrong purpose")
    if (
        receipt.caller_role != invocation_context.caller_role
        or invocation_context.purposes != (KUBERNETES_POD_RECOVERY_PURPOSE,)
        or invocation_context.evidence_refs != expected_evidence_refs
    ):
        raise PermissionError("Kubernetes Pod recovery receipt does not match invocation context")
    if not receipt_verifier.verify(
        receipt=receipt,
        invocation_context=invocation_context,
        expected_release=expected_release,
        expected_purpose=KUBERNETES_POD_RECOVERY_PURPOSE,
        expected_result_digest=expected_digest,
        verification_context=verification_context,
    ):
        raise PermissionError("Kubernetes Pod recovery receipt verification failed")


def _resource_type(record: OntologyObjectRecord) -> str | None:
    if record.object_type != "Resource":
        return None
    value = record.properties.get("type")
    return value if isinstance(value, str) else None


def _resource_properties(record: OntologyObjectRecord) -> Mapping[str, Any]:
    value = record.properties.get("properties")
    if not isinstance(value, Mapping):
        raise ValueError("Pod Resource properties are unavailable")
    return value


def _state_metadata(record: OntologyObjectRecord) -> StateFactMetadata:
    properties = _resource_properties(record)
    raw = properties.get(STATE_FACT_METADATA_PROPERTY)
    if not isinstance(raw, Mapping):
        raise ValueError("Pod Resource state evidence is unavailable")
    return StateFactMetadata.from_mapping(raw)


def _optional_int(properties: Mapping[str, Any], key: str) -> int | None:
    value = properties.get(key)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise ValueError(f"{key} MUST be an integer or null")
    return value


def _optional_text(properties: Mapping[str, Any], key: str) -> str | None:
    value = properties.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{key} MUST be text or null")
    return value


__all__ = [
    "KUBERNETES_POD_RECOVERY_FUNCTION_NAME",
    "KUBERNETES_POD_RECOVERY_PURPOSE",
    "KUBERNETES_POD_RESTART_HISTORY_CONCEPT",
    "KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT",
    "evaluate_kubernetes_pod_recovery_graph",
    "evaluate_kubernetes_pod_replacement_graph",
    "kubernetes_pod_recovery_function",
    "kubernetes_pod_recovery_function_type",
]
