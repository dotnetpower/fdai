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
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_mutable_json(item) for item in value]
    return value
