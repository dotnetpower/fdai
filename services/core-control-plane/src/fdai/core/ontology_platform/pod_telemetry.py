"""Deterministic Pod telemetry path verification over secured graph evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import StateFactMetadata

from .pod_telemetry_evidence import (
    PodTelemetryPathResult,
    TelemetryPathSegment,
    TelemetrySegmentKind,
    TelemetrySegmentStatus,
    evaluate_state_fact_metadata,
    telemetry_link_subject,
    telemetry_object_subject,
)
from .query_gateway import SecuredObjectSetQueryResult

_PURPOSE = "telemetry-verification"
_EXPECTED_SEGMENT_COUNT = 4


def evaluate_pod_telemetry_path(
    secured: SecuredObjectSetQueryResult,
    *,
    pod_id: str,
    expected_cluster_ref: str,
    cutoff: datetime,
    state_evidence: Mapping[str, StateFactMetadata],
) -> PodTelemetryPathResult:
    """Verify a Pod telemetry path without provider I/O or health inference.

    The secured ObjectSet receipt proves the bounded graph projection. State
    metadata independently verifies each physical relationship and sample.
    Missing, stale, incomplete, conflicting, synthetic, ambiguous, truncated,
    or cross-cluster evidence can only reduce completeness.
    """

    if not pod_id.strip() or not expected_cluster_ref.strip():
        raise ValueError("pod_id and expected_cluster_ref MUST be non-empty")
    if cutoff.tzinfo is None:
        raise ValueError("telemetry evaluation cutoff MUST be timezone-aware")
    if secured.receipt.purpose != _PURPOSE:
        raise ValueError(f"secured graph purpose MUST be {_PURPOSE!r}")

    graph = secured.materialization.graph
    objects = _objects_by_id(graph)
    graph_complete = secured.receipt.complete and not graph.truncated
    pod = objects.get(pod_id)
    identity_reasons = _pod_identity_reasons(
        pod,
        pod_id=pod_id,
        expected_cluster_ref=expected_cluster_ref,
    )
    if identity_reasons:
        segments = _identity_failure_segments(identity_reasons)
        return _result(
            pod_id=pod_id,
            expected_cluster_ref=expected_cluster_ref,
            segments=segments,
            graph_receipt_ref=secured.receipt.projected_result_digest,
            graph_complete=False,
        )

    selector_links = _matching_links(
        graph.links,
        link_type="kubernetes_selects",
        to_id=pod_id,
    )
    service_link, service_reasons = _single_typed_link(
        selector_links,
        objects=objects,
        source_kind="Service",
        target_kind="Pod",
        graph_complete=graph_complete,
    )
    if service_link is not None:
        service_reasons = (
            *service_reasons,
            *_resource_cluster_reasons(
                objects.get(service_link.from_id),
                expected_cluster_ref=expected_cluster_ref,
                label="service",
            ),
        )
    selector_segment = _link_segment(
        kind=TelemetrySegmentKind.POD_SELECTED_BY_SERVICE,
        link=service_link,
        missing_from_id=None,
        missing_to_id=pod_id,
        state_evidence=state_evidence,
        cutoff=cutoff,
        reasons=service_reasons,
        graph_complete=graph_complete,
    )

    endpoint_links = (
        _matching_links(
            graph.links,
            link_type="kubernetes_exposes_endpoints",
            from_id=service_link.from_id,
        )
        if service_link is not None
        else ()
    )
    endpoint_link, endpoint_reasons = _single_typed_link(
        endpoint_links,
        objects=objects,
        source_kind="Service",
        target_kind="Endpoints",
        graph_complete=graph_complete,
    )
    if endpoint_link is not None:
        endpoint_reasons = (
            *endpoint_reasons,
            *_resource_cluster_reasons(
                objects.get(endpoint_link.from_id),
                expected_cluster_ref=expected_cluster_ref,
                label="service",
            ),
            *_resource_cluster_reasons(
                objects.get(endpoint_link.to_id),
                expected_cluster_ref=expected_cluster_ref,
                label="endpoints",
            ),
        )
    if service_link is None:
        endpoint_reasons = (*endpoint_reasons, "service_unresolved")
    endpoint_segment = _link_segment(
        kind=TelemetrySegmentKind.SERVICE_EXPOSES_ENDPOINTS,
        link=endpoint_link,
        missing_from_id=(service_link.from_id if service_link is not None else None),
        missing_to_id=None,
        state_evidence=state_evidence,
        cutoff=cutoff,
        reasons=endpoint_reasons,
        graph_complete=graph_complete,
    )

    observation_links = _matching_links(
        graph.links,
        link_type="observation_targets_resource",
        to_id=pod_id,
    )
    observation_link, observation_reasons = _single_typed_link(
        observation_links,
        objects=objects,
        source_kind="Observation",
        target_kind="Pod",
        graph_complete=graph_complete,
    )
    observation_target_segment = _link_segment(
        kind=TelemetrySegmentKind.OBSERVATION_TARGETS_POD,
        link=observation_link,
        missing_from_id=None,
        missing_to_id=pod_id,
        state_evidence=state_evidence,
        cutoff=cutoff,
        reasons=observation_reasons,
        graph_complete=graph_complete,
    )
    observation = objects.get(observation_link.from_id) if observation_link is not None else None
    observation_sample_segment = _object_segment(
        observation,
        state_evidence=state_evidence,
        cutoff=cutoff,
        graph_complete=graph_complete,
    )

    return _result(
        pod_id=pod_id,
        expected_cluster_ref=expected_cluster_ref,
        segments=(
            selector_segment,
            endpoint_segment,
            observation_target_segment,
            observation_sample_segment,
        ),
        graph_receipt_ref=secured.receipt.projected_result_digest,
        graph_complete=graph_complete,
    )


def _objects_by_id(graph: OntologyGraphSnapshot) -> dict[str, OntologyObjectRecord]:
    objects = {record.id: record for record in graph.objects}
    if len(objects) != len(graph.objects):
        raise ValueError("secured telemetry graph object ids MUST be unique")
    return objects


def _pod_identity_reasons(
    pod: OntologyObjectRecord | None,
    *,
    pod_id: str,
    expected_cluster_ref: str,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if pod is None:
        reasons.append("pod_missing")
        return tuple(reasons)
    if _resource_kind(pod) != "Pod":
        reasons.append("target_is_not_pod")
    prefix = f"{expected_cluster_ref.rstrip('/')}/"
    if not pod_id.startswith(prefix):
        reasons.append("wrong_cluster_identity")
    cluster_ref = _nested_text(pod, "cluster_ref")
    if cluster_ref is not None and cluster_ref != expected_cluster_ref:
        reasons.append("wrong_cluster_identity")
    return tuple(sorted(set(reasons)))


def _identity_failure_segments(reasons: tuple[str, ...]) -> tuple[TelemetryPathSegment, ...]:
    return tuple(
        TelemetryPathSegment(
            kind=kind,
            from_id=None,
            to_id=None,
            status=TelemetrySegmentStatus.MISSING,
            evidence_refs=(),
            reasons=reasons,
        )
        for kind in TelemetrySegmentKind
    )


def _resource_cluster_reasons(
    resource: OntologyObjectRecord | None,
    *,
    expected_cluster_ref: str,
    label: str,
) -> tuple[str, ...]:
    if resource is None or resource.object_type != "Resource":
        return ()
    expected_prefix = f"{expected_cluster_ref.rstrip('/')}/"
    cluster_ref = _nested_text(resource, "cluster_ref")
    if not resource.id.startswith(expected_prefix) or (
        cluster_ref is not None and cluster_ref != expected_cluster_ref
    ):
        return (f"{label}_wrong_cluster_identity",)
    return ()


def _matching_links(
    links: Sequence[OntologyLinkRecord],
    *,
    link_type: str,
    from_id: str | None = None,
    to_id: str | None = None,
) -> tuple[OntologyLinkRecord, ...]:
    return tuple(
        sorted(
            (
                link
                for link in links
                if link.link_type == link_type
                and (from_id is None or link.from_id == from_id)
                and (to_id is None or link.to_id == to_id)
            ),
            key=lambda link: (link.from_id, link.to_id),
        )
    )


def _single_typed_link(
    links: Sequence[OntologyLinkRecord],
    *,
    objects: Mapping[str, OntologyObjectRecord],
    source_kind: str,
    target_kind: str,
    graph_complete: bool,
) -> tuple[OntologyLinkRecord | None, tuple[str, ...]]:
    valid = tuple(
        link
        for link in links
        if _resource_or_object_kind(objects.get(link.from_id)) == source_kind
        and _resource_or_object_kind(objects.get(link.to_id)) == target_kind
    )
    if len(valid) == 1:
        return valid[0], ()
    if len(valid) > 1:
        return None, ("ambiguous_relationship",)
    return None, (("relationship_missing",) if graph_complete else ("graph_incomplete",))


def _link_segment(
    *,
    kind: TelemetrySegmentKind,
    link: OntologyLinkRecord | None,
    missing_from_id: str | None,
    missing_to_id: str | None,
    state_evidence: Mapping[str, StateFactMetadata],
    cutoff: datetime,
    reasons: tuple[str, ...],
    graph_complete: bool,
) -> TelemetryPathSegment:
    if link is None:
        status = (
            TelemetrySegmentStatus.MISSING
            if graph_complete and "relationship_missing" in reasons
            else TelemetrySegmentStatus.UNVERIFIED
        )
        return TelemetryPathSegment(
            kind=kind,
            from_id=missing_from_id,
            to_id=missing_to_id,
            status=status,
            evidence_refs=(),
            reasons=tuple(sorted(set(reasons))),
        )
    metadata = state_evidence.get(telemetry_link_subject(link))
    status, metadata_reasons = evaluate_state_fact_metadata(metadata, cutoff=cutoff)
    if reasons and status is TelemetrySegmentStatus.VERIFIED:
        status = TelemetrySegmentStatus.UNVERIFIED
    return TelemetryPathSegment(
        kind=kind,
        from_id=link.from_id,
        to_id=link.to_id,
        status=status,
        evidence_refs=(metadata.evidence_refs if metadata is not None else ()),
        reasons=tuple(sorted(set((*reasons, *metadata_reasons)))),
    )


def _object_segment(
    observation: OntologyObjectRecord | None,
    *,
    state_evidence: Mapping[str, StateFactMetadata],
    cutoff: datetime,
    graph_complete: bool,
) -> TelemetryPathSegment:
    if observation is None:
        return TelemetryPathSegment(
            kind=TelemetrySegmentKind.OBSERVATION_SAMPLE,
            from_id=None,
            to_id=None,
            status=(
                TelemetrySegmentStatus.MISSING
                if graph_complete
                else TelemetrySegmentStatus.UNVERIFIED
            ),
            evidence_refs=(),
            reasons=(("observation_missing",) if graph_complete else ("graph_incomplete",)),
        )
    metadata = state_evidence.get(telemetry_object_subject(observation.id))
    status, reasons = evaluate_state_fact_metadata(metadata, cutoff=cutoff)
    evidence_ref = observation.properties.get("evidence_ref")
    object_refs = (evidence_ref,) if isinstance(evidence_ref, str) and evidence_ref.strip() else ()
    metadata_refs = metadata.evidence_refs if metadata is not None else ()
    return TelemetryPathSegment(
        kind=TelemetrySegmentKind.OBSERVATION_SAMPLE,
        from_id=observation.id,
        to_id=None,
        status=status,
        evidence_refs=tuple(sorted(set((*object_refs, *metadata_refs)))),
        reasons=reasons,
    )


def _resource_or_object_kind(record: OntologyObjectRecord | None) -> str | None:
    if record is None:
        return None
    if record.object_type == "Resource":
        return _resource_kind(record)
    return record.object_type


def _resource_kind(record: OntologyObjectRecord) -> str | None:
    kind = _nested_text(record, "kind")
    if kind is not None:
        return kind
    resource_type = record.properties.get("type")
    if not isinstance(resource_type, str):
        return None
    return resource_type.rsplit(".", 1)[-1].title()


def _nested_text(record: OntologyObjectRecord, key: str) -> str | None:
    properties = record.properties.get("properties")
    if not isinstance(properties, Mapping):
        return None
    value = properties.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _result(
    *,
    pod_id: str,
    expected_cluster_ref: str,
    segments: tuple[TelemetryPathSegment, ...],
    graph_receipt_ref: str,
    graph_complete: bool,
) -> PodTelemetryPathResult:
    verified = sum(segment.status is TelemetrySegmentStatus.VERIFIED for segment in segments)
    completeness = verified / _EXPECTED_SEGMENT_COUNT
    complete = graph_complete and verified == _EXPECTED_SEGMENT_COUNT
    evidence_refs = tuple(sorted({ref for segment in segments for ref in segment.evidence_refs}))
    return PodTelemetryPathResult(
        pod_id=pod_id,
        expected_cluster_ref=expected_cluster_ref,
        segments=segments,
        completeness=completeness,
        complete=complete,
        graph_receipt_ref=graph_receipt_ref,
        evidence_refs=evidence_refs,
    )


__all__ = [
    "PodTelemetryPathResult",
    "TelemetryPathSegment",
    "TelemetrySegmentKind",
    "TelemetrySegmentStatus",
    "evaluate_pod_telemetry_path",
    "telemetry_link_subject",
    "telemetry_object_subject",
]
