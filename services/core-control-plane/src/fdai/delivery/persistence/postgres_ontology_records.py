"""Record conversion and validation helpers for PostgreSQL ontology persistence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from fdai.shared.contracts.models import (
    OntologyDeclarationKind,
    OntologyRelease,
    OntologyTypeRef,
)
from fdai.shared.providers.ontology_instance import (
    OntologyDirection,
    OntologyInstanceValidationError,
    OntologyLinkRecord,
    OntologyObjectRecord,
    normalize_json_value,
)

_MAX_LIMIT: Final[int] = 1000


def _next_endpoint(
    edge: OntologyLinkRecord,
    *,
    object_id: str,
    direction: OntologyDirection,
) -> str | None:
    if direction in {"outgoing", "both"} and edge.from_id == object_id:
        return edge.to_id
    if direction in {"incoming", "both"} and edge.to_id == object_id:
        return edge.from_id
    return None


def _object_from_row(
    row: Mapping[str, Any],
    *,
    releases: Mapping[str, OntologyRelease] | None = None,
) -> OntologyObjectRecord:
    properties = row["properties"]
    if isinstance(properties, str):
        properties = json.loads(properties)
    if not isinstance(properties, Mapping):
        raise RuntimeError("ontology_resource.properties MUST be a JSON object")
    normalized = normalize_json_value(properties, path="ontology_resource.properties")
    if not isinstance(normalized, dict):  # pragma: no cover - Mapping normalizes to dict
        raise RuntimeError("ontology_resource.properties MUST be a JSON object")
    return OntologyObjectRecord(
        id=str(row["id"]),
        object_type=str(row["object_type"]),
        properties=normalized,
        revision=int(row["revision"]),
        type_ref=_row_type_ref(
            row,
            kind=OntologyDeclarationKind.OBJECT,
            name=str(row["object_type"]),
            releases=releases,
        ),
    )


def _link_from_row(
    row: Mapping[str, Any],
    *,
    releases: Mapping[str, OntologyRelease] | None = None,
) -> OntologyLinkRecord:
    properties = row["properties"]
    if isinstance(properties, str):
        properties = json.loads(properties)
    if not isinstance(properties, Mapping):
        raise RuntimeError("ontology_link.properties MUST be a JSON object")
    normalized = normalize_json_value(properties, path="ontology_link.properties")
    if not isinstance(normalized, dict):  # pragma: no cover - Mapping normalizes to dict
        raise RuntimeError("ontology_link.properties MUST be a JSON object")
    return OntologyLinkRecord(
        link_type=str(row["link_type"]),
        from_id=str(row["from_id"]),
        to_id=str(row["to_id"]),
        properties=normalized,
        type_ref=_row_type_ref(
            row,
            kind=OntologyDeclarationKind.LINK,
            name=str(row["link_type"]),
            releases=releases,
        ),
    )


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= _MAX_LIMIT:
        raise ValueError(f"limit MUST be in [1, {_MAX_LIMIT}]")


def _require_type_ref(value: OntologyTypeRef | None) -> OntologyTypeRef:
    if value is None:
        raise RuntimeError("ontology record MUST be pinned before persistence")
    return value


def _require_projection_revision(*, object_id: str, expected: int, current: int) -> None:
    if expected != current:
        raise OntologyInstanceValidationError(
            f"ontology projection {object_id!r} revision fence mismatch: "
            f"expected {expected}, current {current}"
        )


def _row_type_ref(
    row: Mapping[str, Any],
    *,
    kind: OntologyDeclarationKind,
    name: str,
    releases: Mapping[str, OntologyRelease] | None,
) -> OntologyTypeRef | None:
    version = row.get("type_version")
    digest = row.get("catalog_digest")
    if version is None and digest is None:
        return None
    if not isinstance(version, str) or not isinstance(digest, str):
        raise RuntimeError("persisted ontology type reference is incomplete")
    if releases is None:
        return OntologyTypeRef(kind=kind, name=name, version=version, catalog_digest=digest)
    release = releases.get(digest)
    if release is None:
        raise RuntimeError(
            f"persisted ontology release {digest!r} for {kind.value} {name!r} is unavailable"
        )
    try:
        reference = release.type_ref(kind, name)
    except KeyError as exc:
        raise RuntimeError(
            f"persisted ontology release {digest!r} has no {kind.value} declaration {name!r}"
        ) from exc
    if reference.version != version:
        raise RuntimeError(
            f"persisted ontology type reference version {version!r} does not match "
            f"release {digest!r}"
        )
    return reference


__all__ = [
    "_link_from_row",
    "_next_endpoint",
    "_object_from_row",
    "_require_projection_revision",
    "_require_type_ref",
    "_validate_limit",
]
