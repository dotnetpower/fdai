"""Exact source-row validation and bounded identity for off-path index snapshots."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.contracts.models import CeilingRole, OntologyObjectType
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    pin_object_record,
    validate_object_record,
)


def freeze_snapshot_json(value: Any) -> Any:
    """Freeze nested snapshot properties without losing their JSON serialization."""
    if isinstance(value, Mapping):
        return _ImmutableDict({key: freeze_snapshot_json(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(freeze_snapshot_json(item) for item in value)
    return value


class _ImmutableDict(dict[str, Any]):
    """JSON-serializable mapping that rejects every post-construction mutation."""

    def __setitem__(self, key: str, value: Any) -> None:
        raise TypeError("secured ObjectSet properties are immutable")

    def __delitem__(self, key: str) -> None:
        raise TypeError("secured ObjectSet properties are immutable")

    def clear(self) -> None:
        raise TypeError("secured ObjectSet properties are immutable")

    def pop(self, key: str, default: Any = None) -> Any:
        raise TypeError("secured ObjectSet properties are immutable")

    def popitem(self) -> tuple[str, Any]:
        raise TypeError("secured ObjectSet properties are immutable")

    def setdefault(self, key: str, default: Any = None) -> Any:
        raise TypeError("secured ObjectSet properties are immutable")

    def update(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("secured ObjectSet properties are immutable")

    # dict's overloaded union signatures cannot express an override that always refuses mutation.
    def __ior__(self, other: object, /) -> _ImmutableDict:  # type: ignore[override,misc]
        raise TypeError("secured ObjectSet properties are immutable")


def validate_snapshot_records(
    graph: OntologyGraphSnapshot,
    object_types: Mapping[str, OntologyObjectType],
) -> None:
    """Reject stale declarations and malformed row identities without exposing values."""
    release = build_ontology_release(object_types=tuple(object_types.values()))
    try:
        for record in graph.objects:
            if record.type_ref is None:
                raise ValueError("missing declaration reference")
            pin_object_record(record, release)
            validate_object_record(record, object_types)
    except ValueError:
        raise ValueError(
            "index snapshot source record does not match current declarations"
        ) from None


def snapshot_projection_digest(
    *,
    graph: OntologyGraphSnapshot,
    object_type_names: tuple[str, ...],
    ontology_release_digest: str,
    principal_scope_digest: str,
    caller_role: CeilingRole,
    purpose: str,
    observation_cutoff: datetime,
) -> str:
    """Bind every ordered projected row without exceeding the wire JSON ceiling."""
    if (
        not object_type_names
        or not ontology_release_digest.strip()
        or not principal_scope_digest.strip()
        or not purpose.strip()
        or observation_cutoff.tzinfo is None
        or observation_cutoff.utcoffset() is None
    ):
        raise ValueError("snapshot projection digest requires bounded identities and aware cutoff")
    object_root = hashlib.sha256()
    for record in sorted(graph.objects, key=lambda item: (item.object_type, item.id)):
        object_root.update(
            content_digest(
                {
                    "id": record.id,
                    "object_type": record.object_type,
                    "properties": _mutable_json(record.properties),
                    "revision": record.revision,
                    "type_ref": record.type_ref.model_dump(mode="json")
                    if record.type_ref
                    else None,
                }
            ).encode("ascii")
        )
    return content_digest(
        {
            "object_type_names": object_type_names,
            "ontology_release_digest": ontology_release_digest,
            "principal_scope_digest": principal_scope_digest,
            "caller_role": caller_role.value,
            "purpose": purpose,
            "observation_cutoff": observation_cutoff.isoformat(),
            "source_generation": graph.source_generation,
            "object_count": len(graph.objects),
            "objects_root": "sha256:" + object_root.hexdigest(),
        }
    )


def _mutable_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _mutable_json(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [_mutable_json(item) for item in sorted(value, key=str)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_mutable_json(item) for item in value]
    return value
