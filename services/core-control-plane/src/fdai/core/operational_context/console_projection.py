"""Project receipt-bound operational Context metadata for read-only presentation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

from .models import (
    OperationalContextEvidenceLink,
    OperationalContextEvidencePath,
    OperationalContextSnapshot,
)

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


class _Object(Protocol):
    id: str


class _Link(Protocol):
    link_type: str
    from_id: str
    to_id: str


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
    expected_purpose: str,
) -> dict[str, object]:
    """Return bounded Context metadata only after receipt and graph verification."""

    if not expected_purpose.strip() or secured_result.receipt.purpose != expected_purpose:
        raise ValueError("secured Context receipt purpose does not match the requested purpose")
    if secured_result.receipt.execution_authority is not False:
        raise ValueError("secured Context receipt MUST NOT grant execution authority")
    release_digest = secured_result.receipt.ontology_release.digest
    catalog_versions = dict(snapshot.catalog_versions)
    if catalog_versions.get("ontology") != release_digest:
        raise ValueError("secured Context receipt release does not match snapshot release")
    if _utc(snapshot.cutoff) != _utc(secured_result.receipt.observation_cutoff):
        raise ValueError("secured Context receipt cutoff does not match snapshot cutoff")

    graph = secured_result.materialization.graph
    if len(graph.objects) > _MAX_CONTEXT_OBJECTS or len(graph.links) > _MAX_CONTEXT_LINKS:
        raise ValueError("secured Context result exceeds projection bounds")
    object_ids = {item.id for item in graph.objects}
    required_ids = {item.object_id for item in snapshot.evidence_paths}
    required_ids.update(item.object_id for item in snapshot.temporal_exclusions)
    if not required_ids <= object_ids:
        raise ValueError("secured Context result does not provide complete object coverage")
    graph_links = {(item.from_id, item.link_type, item.to_id) for item in graph.links}
    required_links = {
        (item.from_id, item.link_type, item.to_id) for item in snapshot.evidence_links
    }
    if not required_links <= graph_links:
        raise ValueError("secured Context result does not provide complete link coverage")

    complete = (
        secured_result.receipt.complete
        and not secured_result.receipt.truncated
        and not snapshot.stale_sources
        and not snapshot.conflicts
    )
    return {
        "schema_version": "1.0.0",
        "snapshot_id": snapshot.snapshot_id,
        "ontology_release_digest": release_digest,
        "query_result_digest": secured_result.receipt.projected_result_digest,
        "purpose": secured_result.receipt.purpose,
        "cutoff": _timestamp(snapshot.cutoff),
        "recorded_at": _timestamp(snapshot.recorded_at),
        "complete": complete,
        "query_complete": secured_result.receipt.complete,
        "truncated": secured_result.receipt.truncated,
        "truncation_reason": _enum_value(secured_result.receipt.truncation_reason),
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
