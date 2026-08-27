"""Project receipt-bound operational Context metadata for read-only presentation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol

from fdai.core.ontology_platform.query_gateway import (
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.shared.providers.ontology_instance import canonical_json_mapping
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
)

from .models import (
    OperationalContextEvidenceLink,
    OperationalContextEvidencePath,
    OperationalContextSnapshot,
)
from .principal_context import AuthenticatedPrincipalContext

_MAX_CONTEXT_OBJECTS = 1_000
_MAX_CONTEXT_LINKS = 8_000


class _ReleaseRef(Protocol):
    digest: str


class _Receipt(Protocol):
    ontology_release: _ReleaseRef
    projected_result_digest: str
    purpose: str
    observation_cutoff: datetime
    complete: bool
    truncated: bool
    truncation_reason: object | None
    execution_authority: bool
    principal_scope_digest: str | None


class _Object(Protocol):
    id: str


class _Link(Protocol):
    link_type: str
    from_id: str
    to_id: str
    properties: Mapping[str, object]


class _Graph(Protocol):
    objects: Sequence[_Object]
    links: Sequence[_Link]


class _Materialization(Protocol):
    graph: _Graph


class SecuredContextResult(Protocol):
    receipt: _Receipt
    materialization: _Materialization


def project_context_snapshot(
    *,
    snapshot: OperationalContextSnapshot,
    secured_result: SecuredContextResult,
    authenticated_context: AuthenticatedPrincipalContext,
) -> dict[str, object]:
    """Return bounded Context metadata only after receipt and graph verification."""

    if not isinstance(secured_result, SecuredObjectSetQueryResult):
        raise ValueError("secured Context result MUST use the ObjectSet query receipt contract")
    receipt = secured_result.receipt
    if receipt.purpose != authenticated_context.purpose:
        raise ValueError("secured Context receipt purpose does not match the requested purpose")
    if receipt.principal_scope_digest != authenticated_context.principal_scope_digest:
        raise ValueError(
            "secured Context receipt principal scope does not match authenticated context"
        )
    if not authenticated_context.receipt_authority.verify(
        receipt=receipt,
        invocation_context=authenticated_context.invocation_context,
        expected_release=receipt.ontology_release,
        expected_purpose=authenticated_context.purpose,
        expected_result_digest=receipt.projected_result_digest,
        verification_context=authenticated_context.verification_context,
    ):
        raise ValueError("secured Context receipt was not issued by the receipt authority")
    if receipt.execution_authority is not False:
        raise ValueError("secured Context receipt MUST NOT grant execution authority")
    if receipt.projected_result_digest != _projected_result_digest(secured_result.materialization):
        raise ValueError("secured Context receipt digest does not match the materialization")
    release_digest = receipt.ontology_release.digest
    catalog_versions = dict(snapshot.catalog_versions)
    if catalog_versions.get("ontology") != release_digest:
        raise ValueError("secured Context receipt release does not match snapshot release")
    if _utc(snapshot.cutoff) != _utc(receipt.observation_cutoff):
        raise ValueError("secured Context receipt cutoff does not match snapshot cutoff")
    if not receipt.complete or receipt.truncated or snapshot.stale_sources or snapshot.conflicts:
        raise ValueError("secured Context evidence is unavailable")

    graph = secured_result.materialization.graph
    if len(graph.objects) > _MAX_CONTEXT_OBJECTS or len(graph.links) > _MAX_CONTEXT_LINKS:
        raise ValueError("secured Context result exceeds projection bounds")
    object_by_id = {item.id: item for item in graph.objects}
    if len(object_by_id) != len(graph.objects):
        raise ValueError("secured Context result contains duplicate object identities")
    required_paths = (*snapshot.evidence_paths, *snapshot.temporal_exclusions)
    required_ids = {item.object_id for item in required_paths}
    if snapshot.target_resource_id not in object_by_id:
        raise ValueError("secured Context result does not provide the target Resource")
    required_ids.update(item.object_id for item in snapshot.temporal_exclusions)
    if not required_ids <= set(object_by_id):
        raise ValueError("secured Context result does not provide complete object coverage")
    target = object_by_id[snapshot.target_resource_id]
    if target.object_type != "Resource":
        raise ValueError("secured Context target object type does not match Resource")
    for path in required_paths:
        object_record = object_by_id[path.object_id]
        if object_record.object_type != path.object_type or object_record.revision != path.revision:
            raise ValueError(
                "secured Context result object type or revision does not match its path"
            )
        canonical_json_mapping(
            object_record.properties,
            path=f"{object_record.object_type}.properties",
        )
        for name, expected in (
            ("effective_from", path.effective_from),
            ("effective_to", path.effective_to),
        ):
            actual = object_record.properties.get(name)
            if expected is None and actual is not None:
                raise ValueError("secured Context result temporal identity does not match its path")
            if expected is not None and actual != _timestamp(expected):
                raise ValueError("secured Context result temporal identity does not match its path")
    graph_links = {
        (item.from_id, item.link_type, item.to_id): _graph_link_metadata(item)
        for item in graph.links
    }
    if len(graph_links) != len(graph.links):
        raise ValueError("secured Context result contains duplicate link identities")
    if any(
        link.from_id not in object_by_id or link.to_id not in object_by_id for link in graph.links
    ):
        raise ValueError("secured Context result link endpoint identity is incomplete")
    required_links = _required_link_metadata(snapshot, required_paths=required_paths)
    if not required_links.keys() <= graph_links.keys():
        raise ValueError("secured Context result does not provide complete link coverage")
    if any(graph_links[identity] != metadata for identity, metadata in required_links.items()):
        raise ValueError("secured Context result link observation metadata does not match snapshot")

    complete = (
        secured_result.receipt.complete
        and not secured_result.receipt.truncated
        and not snapshot.stale_sources
        and not snapshot.conflicts
    )
    return {
        "schema_version": "1.0.0",
        "snapshot_id": snapshot.snapshot_id,
        "principal_ref": authenticated_context.principal_ref,
        "ontology_release_digest": release_digest,
        "query_result_digest": secured_result.receipt.projected_result_digest,
        "purpose": receipt.purpose,
        "cutoff": _timestamp(snapshot.cutoff),
        "recorded_at": _timestamp(snapshot.recorded_at),
        "complete": complete,
        "query_complete": receipt.complete,
        "truncated": receipt.truncated,
        "truncation_reason": _enum_value(receipt.truncation_reason),
        "autonomy_ceiling": snapshot.autonomy_ceiling.value,
        "object_count": len(graph.objects),
        "link_count": len(graph.links),
        "source_freshness": [
            {
                "source": item.source,
                "observed_at": _timestamp(item.observed_at),
                "max_age_seconds": item.max_age_seconds,
            }
            for item in snapshot.source_freshness
        ],
        "stale_sources": list(snapshot.stale_sources),
        "conflicts": list(snapshot.conflicts),
        "evidence_paths": [_path_projection(item) for item in snapshot.evidence_paths],
        "temporal_exclusions": [_path_projection(item) for item in snapshot.temporal_exclusions],
        "mutation_authority": False,
        "execution_authority": False,
    }


def _path_projection(path: OperationalContextEvidencePath) -> dict[str, object]:
    return {
        "object_id": path.object_id,
        "object_type": path.object_type,
        "revision": path.revision,
        "effective_from": _optional_timestamp(path.effective_from),
        "effective_to": _optional_timestamp(path.effective_to),
        "provenance_refs": list(path.provenance_refs),
        "links": [_link_projection(item) for item in path.links],
    }


def _link_projection(link: OperationalContextEvidenceLink) -> dict[str, str]:
    return {
        "link_type": link.link_type,
        "from_id": link.from_id,
        "to_id": link.to_id,
    }


def _graph_link_metadata(link: _Link) -> LinkObservationMetadata | None:
    raw = link.properties.get(LINK_OBSERVATION_METADATA_PROPERTY)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("secured Context result link observation metadata MUST be an object")
    return LinkObservationMetadata.from_mapping(raw)


def _required_link_metadata(
    snapshot: OperationalContextSnapshot,
    *,
    required_paths: tuple[OperationalContextEvidencePath, ...],
) -> dict[tuple[str, str, str], LinkObservationMetadata | None]:
    required: dict[tuple[str, str, str], LinkObservationMetadata | None] = {}
    links = (
        *snapshot.evidence_links,
        *(link for path in required_paths for link in path.links),
    )
    for link in links:
        identity = (link.from_id, link.link_type, link.to_id)
        existing = required.get(identity)
        if identity in required and existing != link.observation_metadata:
            raise ValueError(
                "operational Context snapshot has conflicting link observation metadata"
            )
        required[identity] = link.observation_metadata
    return required


def _optional_timestamp(value: datetime | None) -> str | None:
    return None if value is None else _timestamp(value)


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Context projection timestamps MUST be timezone-aware")
    return value.astimezone(UTC)


def _enum_value(value: object | None) -> object | None:
    return getattr(value, "value", value)


__all__ = ["SecuredContextResult", "project_context_snapshot"]
