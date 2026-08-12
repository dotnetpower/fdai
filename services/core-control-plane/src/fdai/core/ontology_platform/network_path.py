"""Bounded deterministic verification of network paths in secured ontology results.

The evaluator performs no provider I/O and grants no reachability or execution
authority from missing graph data. Directed storage remains visible on every
segment. A symmetric peering hop exists only when both directed records are
present and independently evidence-bearing.
"""

from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

from pydantic import Field, model_validator

from fdai.shared.contracts.models import (
    CeilingRole,
    ContractBase,
    LogicExecutionClass,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
    OntologyReleaseRef,
)
from fdai.shared.providers.ontology_instance import OntologyLinkRecord
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext
from .query_gateway import SecuredObjectSetQueryReceipt, SecuredObjectSetQueryResult

NETWORK_PATH_FUNCTION_NAME = "query.network_path_segments"
NETWORK_PATH_PURPOSE = "network-path-verification"
_NETWORK_LINK_TYPES = frozenset({"attached_to", "contains", "peered_with", "routes_to"})
_MAX_FRESHNESS_CEILING_SECONDS = 31_536_000


def _source_artifact_digest() -> str:
    return f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}"


class NetworkQueryReceiptVerifier(Protocol):
    """Authenticate one secured query receipt against an opaque trust context."""

    def verify(
        self,
        *,
        receipt: SecuredObjectSetQueryReceipt,
        invocation_context: FunctionInvocationContext,
        expected_release: OntologyReleaseRef,
        expected_purpose: str,
        expected_result_digest: str,
        verification_context: object,
    ) -> bool: ...


class NetworkSegmentStatus(StrEnum):
    """Evidence quality for one traversed network segment."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    STALE = "stale"
    MISSING = "missing"


class NetworkPathStatus(StrEnum):
    """Terminal result without a false negative reachability claim."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    STALE = "stale"
    MISSING_ENDPOINT = "missing_endpoint"
    NO_PATH_EVIDENCE = "no_path_evidence"
    CYCLE_DETECTED = "cycle_detected"
    LIMIT_EXCEEDED = "limit_exceeded"


class NetworkPathSegment(ContractBase):
    """One traversal hop with stored-edge direction and evidence state."""

    from_id: Annotated[str, Field(min_length=1, max_length=512)]
    to_id: Annotated[str, Field(min_length=1, max_length=512)]
    link_type: Annotated[str, Field(min_length=1, max_length=64)] | None
    status: NetworkSegmentStatus
    stored_edges: tuple[Annotated[str, Field(min_length=1, max_length=1200)], ...] = ()
    evidence_refs: tuple[Annotated[str, Field(min_length=1, max_length=512)], ...] = ()
    reason_codes: tuple[Annotated[str, Field(min_length=1, max_length=64)], ...] = ()


class NetworkPathResult(ContractBase):
    """Bounded path evidence pinned to one secured query and ontology release."""

    source_id: Annotated[str, Field(min_length=1, max_length=512)]
    target_id: Annotated[str, Field(min_length=1, max_length=512)]
    status: NetworkPathStatus
    reachability_verified: bool | None = None
    segments: Annotated[tuple[NetworkPathSegment, ...], Field(max_length=64)] = ()
    ontology_release: OntologyReleaseRef
    query_result_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    examined_segments: int = Field(ge=0, le=64)
    cycle_detected: bool = False
    invalid_peering_edges: int = Field(default=0, ge=0, le=1000)
    reason_codes: tuple[Annotated[str, Field(min_length=1, max_length=64)], ...] = ()
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _verified_reachability_is_never_false(self) -> NetworkPathResult:
        if self.reachability_verified is False:
            raise ValueError("network path absence MUST NOT assert unreachable")
        if self.reachability_verified is True and self.status is not NetworkPathStatus.VERIFIED:
            raise ValueError("only a fully verified path may assert reachability")
        return self


@dataclass(frozen=True, slots=True)
class _EvidenceAssessment:
    status: NetworkSegmentStatus
    evidence_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _AdjacentSegment:
    to_id: str
    link_type: str
    stored_edges: tuple[OntologyLinkRecord, ...]
    evidence: _EvidenceAssessment


def network_path_function_type() -> OntologyFunctionType:
    """Return the exact read-only deterministic FunctionType declaration."""

    return OntologyFunctionType(
        name=NETWORK_PATH_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=_source_artifact_digest(),
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "query_result",
                "source_id",
                "target_id",
                "max_depth",
                "max_segments",
            ],
            "properties": {
                "query_result": {"type": "object"},
                "source_id": {"type": "string", "minLength": 1, "maxLength": 512},
                "target_id": {"type": "string", "minLength": 1, "maxLength": 512},
                "evaluated_at": {"type": "string", "format": "date-time"},
                "max_depth": {"type": "integer", "minimum": 1, "maximum": 16},
                "max_segments": {"type": "integer", "minimum": 1, "maximum": 64},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "source_id",
                "target_id",
                "status",
                "reachability_verified",
                "segments",
                "ontology_release",
                "query_result_digest",
                "examined_segments",
                "cycle_detected",
                "invalid_peering_edges",
                "reason_codes",
                "execution_authority",
            ],
            "properties": {
                "source_id": {"type": "string"},
                "target_id": {"type": "string"},
                "status": {"type": "string"},
                "reachability_verified": {"type": ["boolean", "null"]},
                "segments": {"type": "array", "maxItems": 64},
                "ontology_release": {"type": "object"},
                "query_result_digest": {"type": "string"},
                "examined_segments": {"type": "integer"},
                "cycle_detected": {"type": "boolean"},
                "invalid_peering_edges": {"type": "integer"},
                "reason_codes": {"type": "array"},
                "execution_authority": {"const": False},
            },
        },
        read_sets=["Resource", "attached_to", "contains", "peered_with", "routes_to"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[NETWORK_PATH_PURPOSE],
        timeout_seconds=5,
        cpu_millis=1000,
        memory_bytes=134_217_728,
        max_output_bytes=131_072,
        network_allowed=False,
        credentials_allowed=False,
    )


def network_path_function(
    ontology_release: OntologyRelease,
    *,
    receipt_verifier: NetworkQueryReceiptVerifier,
    verification_context: object,
) -> ContextualOntologyFunction:
    """Bind a contextual read callback to trusted secured-query verification.

    The opaque verification context is supplied by composition, never function
    arguments. A receipt is accepted only when its authorization tuple matches
    the immutable invocation context and the injected verifier authenticates it.
    """

    if verification_context is None:
        raise ValueError("network path receipt verification context MUST be non-null")
    expected_release = ontology_release.ref()

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        query_result = SecuredObjectSetQueryResult.model_validate(arguments["query_result"])
        _authenticate_query_receipt(
            query_result,
            invocation_context=invocation_context,
            expected_release=expected_release,
            receipt_verifier=receipt_verifier,
            verification_context=verification_context,
        )
        evaluated_at = (
            _timestamp(arguments["evaluated_at"])
            if "evaluated_at" in arguments
            else query_result.receipt.observation_cutoff
        )
        return evaluate_network_path(
            query_result,
            source_id=_string(arguments, "source_id"),
            target_id=_string(arguments, "target_id"),
            evaluated_at=evaluated_at,
            max_depth=_integer(arguments, "max_depth"),
            max_segments=_integer(arguments, "max_segments"),
        )

    return evaluate


def _authenticate_query_receipt(
    query_result: SecuredObjectSetQueryResult,
    *,
    invocation_context: FunctionInvocationContext,
    expected_release: OntologyReleaseRef,
    receipt_verifier: NetworkQueryReceiptVerifier,
    verification_context: object,
) -> None:
    receipt = query_result.receipt
    expected_digest = receipt.projected_result_digest
    if receipt.ontology_release != expected_release:
        raise ValueError("network path query result does not match the exact ontology release")
    if receipt.purpose != NETWORK_PATH_PURPOSE:
        raise ValueError("network path query result has the wrong purpose")
    if (
        receipt.caller_role != invocation_context.caller_role
        or invocation_context.purposes != (NETWORK_PATH_PURPOSE,)
        or invocation_context.evidence_refs != (expected_digest,)
    ):
        raise PermissionError("network path query receipt does not match invocation context")
    if not receipt_verifier.verify(
        receipt=receipt,
        invocation_context=invocation_context,
        expected_release=expected_release,
        expected_purpose=NETWORK_PATH_PURPOSE,
        expected_result_digest=expected_digest,
        verification_context=verification_context,
    ):
        raise PermissionError("network path query receipt verification failed")


def evaluate_network_path(
    query_result: SecuredObjectSetQueryResult,
    *,
    source_id: str,
    target_id: str,
    evaluated_at: datetime,
    max_depth: int,
    max_segments: int,
) -> NetworkPathResult:
    """Return bounded segment evidence and never infer unreachable from absence.

    Raises:
        ValueError: The query isn't purpose-bound, inputs exceed the evaluator
            bounds, or the secured graph violates endpoint/property closure.
    """

    secured = SecuredObjectSetQueryResult.model_validate(query_result.model_dump(mode="json"))
    if secured.receipt.purpose != NETWORK_PATH_PURPOSE:
        raise ValueError("network path query result has the wrong purpose")
    if evaluated_at.tzinfo is None:
        raise ValueError("network path evaluated_at MUST be timezone-aware")
    if evaluated_at.astimezone(UTC) != secured.receipt.observation_cutoff.astimezone(UTC):
        raise ValueError("network path evaluation cutoff MUST equal receipt observation cutoff")
    if not 1 <= max_depth <= 16:
        raise ValueError("network path max_depth MUST be between 1 and 16")
    if not 1 <= max_segments <= 64:
        raise ValueError("network path max_segments MUST be between 1 and 64")
    source = source_id.strip()
    target = target_id.strip()
    if not source or not target:
        raise ValueError("network path endpoint ids MUST be non-empty")

    graph = secured.materialization.graph
    objects = {item.id: item for item in graph.objects}
    if len(objects) != len(graph.objects):
        raise ValueError("secured network path object ids MUST be unique")
    if not secured.receipt.complete or graph.truncated:
        return _result(
            secured,
            source=source,
            target=target,
            status=NetworkPathStatus.UNVERIFIED,
            segments=(),
            examined=0,
            reason_codes=("query_incomplete",),
        )
    missing = tuple(endpoint for endpoint in (source, target) if endpoint not in objects)
    if missing:
        missing_reasons = tuple(
            reason
            for endpoint, reason in (
                (source, "missing_source"),
                (target, "missing_target"),
            )
            if endpoint in missing
        )
        missing_segment = NetworkPathSegment(
            from_id=source,
            to_id=target,
            link_type=None,
            status=NetworkSegmentStatus.MISSING,
            reason_codes=missing_reasons,
        )
        return _result(
            secured,
            source=source,
            target=target,
            status=NetworkPathStatus.MISSING_ENDPOINT,
            segments=(missing_segment,),
            examined=0,
            reason_codes=("endpoint_missing",),
        )
    relevant_links = tuple(link for link in graph.links if link.link_type in _NETWORK_LINK_TYPES)
    if len(relevant_links) > max_segments:
        return _result(
            secured,
            source=source,
            target=target,
            status=NetworkPathStatus.LIMIT_EXCEEDED,
            segments=(),
            examined=0,
            reason_codes=("segment_limit",),
        )

    adjacency, invalid_peering_edges = _build_adjacency(
        relevant_links,
        object_ids=set(objects),
        evaluated_at=evaluated_at,
    )
    queue: deque[tuple[str, tuple[str, ...], tuple[NetworkPathSegment, ...]]] = deque(
        [(source, (source,), ())]
    )
    examined = 0
    cycle_detected = False
    depth_limited = False
    while queue:
        current, path_ids, path = queue.popleft()
        if len(path) >= max_depth:
            if adjacency.get(current):
                depth_limited = True
            continue
        for adjacent in adjacency.get(current, ()):
            examined += 1
            if examined > max_segments:
                return _result(
                    secured,
                    source=source,
                    target=target,
                    status=NetworkPathStatus.LIMIT_EXCEEDED,
                    segments=path,
                    examined=max_segments,
                    cycle_detected=cycle_detected,
                    invalid_peering_edges=invalid_peering_edges,
                    reason_codes=("segment_limit",),
                )
            segment = _segment(current, adjacent)
            if adjacent.to_id in path_ids:
                cycle_detected = True
                continue
            next_path = (*path, segment)
            if adjacent.to_id == target:
                status = _path_status(next_path, query_complete=secured.receipt.complete)
                return _result(
                    secured,
                    source=source,
                    target=target,
                    status=status,
                    segments=next_path,
                    examined=examined,
                    cycle_detected=cycle_detected,
                    invalid_peering_edges=invalid_peering_edges,
                    reason_codes=(() if secured.receipt.complete else ("query_incomplete",)),
                )
            queue.append((adjacent.to_id, (*path_ids, adjacent.to_id), next_path))

    if depth_limited:
        status = NetworkPathStatus.LIMIT_EXCEEDED
        reasons = ("depth_limit",)
    elif cycle_detected:
        status = NetworkPathStatus.CYCLE_DETECTED
        reasons = ("cycle_without_verified_path",)
    else:
        status = NetworkPathStatus.NO_PATH_EVIDENCE
        reasons = ("path_not_observed",)
    return _result(
        secured,
        source=source,
        target=target,
        status=status,
        segments=(),
        examined=examined,
        cycle_detected=cycle_detected,
        invalid_peering_edges=invalid_peering_edges,
        reason_codes=reasons,
    )


def _build_adjacency(
    links: tuple[OntologyLinkRecord, ...],
    *,
    object_ids: set[str],
    evaluated_at: datetime,
) -> tuple[dict[str, tuple[_AdjacentSegment, ...]], int]:
    keyed: dict[tuple[str, str, str], OntologyLinkRecord] = {}
    for link in links:
        if link.from_id not in object_ids or link.to_id not in object_ids:
            raise ValueError("secured network path link has a missing endpoint")
        if set(link.properties) - {LINK_OBSERVATION_METADATA_PROPERTY}:
            raise ValueError("secured network path link contains unsupported properties")
        if link.link_type in _NETWORK_LINK_TYPES:
            key = (link.link_type, link.from_id, link.to_id)
            if key in keyed:
                raise ValueError("secured network path links MUST be unique")
            keyed[key] = link

    adjacency: dict[str, list[_AdjacentSegment]] = {}
    invalid_peering_edges = 0
    handled_peer_pairs: set[tuple[str, str]] = set()
    for (link_type, from_id, to_id), link in sorted(keyed.items()):
        if link_type == "peered_with":
            pair = (from_id, to_id) if from_id < to_id else (to_id, from_id)
            if pair in handled_peer_pairs:
                continue
            reverse = keyed.get((link_type, to_id, from_id))
            if reverse is None:
                invalid_peering_edges += 1
                continue
            handled_peer_pairs.add(pair)
            evidence = _peering_evidence(link, reverse, evaluated_at=evaluated_at)
            _append(adjacency, pair[0], pair[1], link_type, (link, reverse), evidence)
            _append(adjacency, pair[1], pair[0], link_type, (link, reverse), evidence)
            continue
        evidence = _combined_evidence((link,), evaluated_at=evaluated_at)
        _append(adjacency, from_id, to_id, link_type, (link,), evidence)
        if link_type == "attached_to":
            _append(adjacency, to_id, from_id, link_type, (link,), evidence)
    return {
        source: tuple(sorted(items, key=lambda item: (item.to_id, item.link_type)))
        for source, items in adjacency.items()
    }, invalid_peering_edges


def _append(
    adjacency: dict[str, list[_AdjacentSegment]],
    from_id: str,
    to_id: str,
    link_type: str,
    stored_edges: tuple[OntologyLinkRecord, ...],
    evidence: _EvidenceAssessment,
) -> None:
    adjacency.setdefault(from_id, []).append(
        _AdjacentSegment(
            to_id=to_id,
            link_type=link_type,
            stored_edges=stored_edges,
            evidence=evidence,
        )
    )


def _combined_evidence(
    links: tuple[OntologyLinkRecord, ...],
    *,
    evaluated_at: datetime,
) -> _EvidenceAssessment:
    assessments = tuple(_assess_evidence(link, evaluated_at=evaluated_at) for link in links)
    if any(item.status is NetworkSegmentStatus.STALE for item in assessments):
        status = NetworkSegmentStatus.STALE
    elif all(item.status is NetworkSegmentStatus.VERIFIED for item in assessments):
        status = NetworkSegmentStatus.VERIFIED
    else:
        status = NetworkSegmentStatus.UNVERIFIED
    return _EvidenceAssessment(
        status=status,
        evidence_refs=tuple(sorted({ref for item in assessments for ref in item.evidence_refs})),
        reason_codes=tuple(
            sorted({reason for item in assessments for reason in item.reason_codes})
        ),
    )


def _peering_evidence(
    forward: OntologyLinkRecord,
    reverse: OntologyLinkRecord,
    *,
    evaluated_at: datetime,
) -> _EvidenceAssessment:
    combined = _combined_evidence((forward, reverse), evaluated_at=evaluated_at)
    forward_metadata = _link_metadata(forward)
    reverse_metadata = _link_metadata(reverse)
    if forward_metadata is None or reverse_metadata is None:
        return combined
    reused_lineage = (
        forward_metadata.state_fact.evidence_refs == reverse_metadata.state_fact.evidence_refs
        or forward_metadata.verification_receipt_ref == reverse_metadata.verification_receipt_ref
    )
    if not reused_lineage:
        return combined
    return _EvidenceAssessment(
        status=(
            NetworkSegmentStatus.STALE
            if combined.status is NetworkSegmentStatus.STALE
            else NetworkSegmentStatus.UNVERIFIED
        ),
        evidence_refs=combined.evidence_refs,
        reason_codes=tuple(sorted({*combined.reason_codes, "peering_receipt_reused"})),
    )


def _link_metadata(link: OntologyLinkRecord) -> LinkObservationMetadata | None:
    raw = link.properties.get(LINK_OBSERVATION_METADATA_PROPERTY)
    if not isinstance(raw, Mapping):
        return None
    try:
        return LinkObservationMetadata.from_mapping(raw)
    except (KeyError, TypeError, ValueError):
        return None


def _assess_evidence(
    link: OntologyLinkRecord,
    *,
    evaluated_at: datetime,
) -> _EvidenceAssessment:
    metadata = _link_metadata(link)
    if metadata is None:
        return _EvidenceAssessment(
            NetworkSegmentStatus.UNVERIFIED,
            (),
            (
                "evidence_missing"
                if LINK_OBSERVATION_METADATA_PROPERTY not in link.properties
                else "evidence_malformed",
            ),
        )
    fact = metadata.state_fact
    evidence_refs = tuple(
        sorted(
            {
                *fact.evidence_refs,
                *(
                    (metadata.verification_receipt_ref,)
                    if metadata.verification_receipt_ref is not None
                    else ()
                ),
            }
        )
    )
    if fact.freshness_ceiling_seconds > _MAX_FRESHNESS_CEILING_SECONDS:
        return _EvidenceAssessment(
            NetworkSegmentStatus.UNVERIFIED,
            evidence_refs,
            ("freshness_ceiling_exceeded",),
        )
    try:
        fresh_until = fact.evidence_cutoff + timedelta(seconds=fact.freshness_ceiling_seconds)
    except OverflowError:
        return _EvidenceAssessment(
            NetworkSegmentStatus.UNVERIFIED,
            evidence_refs,
            ("freshness_overflow",),
        )
    if evaluated_at > fresh_until:
        return _EvidenceAssessment(
            NetworkSegmentStatus.STALE,
            evidence_refs,
            ("evidence_stale",),
        )
    reasons: list[str] = []
    if not metadata.verified:
        reasons.append("not_independently_verified")
    if fact.completeness < 1.0:
        reasons.append("evidence_incomplete")
    if fact.synthetic:
        reasons.append("synthetic_evidence")
    if fact.conflicts:
        reasons.append("evidence_conflict")
    if fact.evidence_cutoff > evaluated_at:
        reasons.append("evidence_after_evaluation")
    if fact.effective_at > evaluated_at:
        reasons.append("evidence_effective_after_cutoff")
    if fact.recorded_at > evaluated_at:
        reasons.append("evidence_recorded_after_cutoff")
    return _EvidenceAssessment(
        NetworkSegmentStatus.UNVERIFIED if reasons else NetworkSegmentStatus.VERIFIED,
        evidence_refs,
        tuple(reasons),
    )


def _segment(from_id: str, adjacent: _AdjacentSegment) -> NetworkPathSegment:
    return NetworkPathSegment(
        from_id=from_id,
        to_id=adjacent.to_id,
        link_type=adjacent.link_type,
        status=adjacent.evidence.status,
        stored_edges=tuple(
            sorted(
                f"{edge.from_id}|{edge.link_type}|{edge.to_id}" for edge in adjacent.stored_edges
            )
        ),
        evidence_refs=adjacent.evidence.evidence_refs,
        reason_codes=adjacent.evidence.reason_codes,
    )


def _path_status(
    segments: tuple[NetworkPathSegment, ...],
    *,
    query_complete: bool,
) -> NetworkPathStatus:
    if any(segment.status is NetworkSegmentStatus.STALE for segment in segments):
        return NetworkPathStatus.STALE
    if not query_complete or any(
        segment.status is not NetworkSegmentStatus.VERIFIED for segment in segments
    ):
        return NetworkPathStatus.UNVERIFIED
    return NetworkPathStatus.VERIFIED


def _result(
    query_result: SecuredObjectSetQueryResult,
    *,
    source: str,
    target: str,
    status: NetworkPathStatus,
    segments: tuple[NetworkPathSegment, ...],
    examined: int,
    cycle_detected: bool = False,
    invalid_peering_edges: int = 0,
    reason_codes: tuple[str, ...] = (),
) -> NetworkPathResult:
    return NetworkPathResult(
        source_id=source,
        target_id=target,
        status=status,
        reachability_verified=(True if status is NetworkPathStatus.VERIFIED else None),
        segments=segments,
        ontology_release=query_result.receipt.ontology_release,
        query_result_digest=query_result.receipt.projected_result_digest,
        examined_segments=examined,
        cycle_detected=cycle_detected,
        invalid_peering_edges=invalid_peering_edges,
        reason_codes=reason_codes,
    )


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("network path evaluated_at MUST be an RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("network path evaluated_at MUST be RFC 3339") from exc
    if parsed.tzinfo is None:
        raise ValueError("network path evaluated_at MUST be timezone-aware")
    return parsed


def _string(arguments: Mapping[str, Any], name: str) -> str:
    value = arguments[name]
    if not isinstance(value, str):
        raise ValueError(f"network path {name} MUST be a string")
    return value


def _integer(arguments: Mapping[str, Any], name: str) -> int:
    value = arguments[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"network path {name} MUST be an integer")
    return int(value)


__all__ = [
    "NETWORK_PATH_FUNCTION_NAME",
    "NETWORK_PATH_PURPOSE",
    "NetworkQueryReceiptVerifier",
    "NetworkPathResult",
    "NetworkPathSegment",
    "NetworkPathStatus",
    "NetworkSegmentStatus",
    "evaluate_network_path",
    "network_path_function",
    "network_path_function_type",
]
