"""Bounded deterministic entity resolution for ontology proposals."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fdai.rule_catalog.pipeline.distill.ontology_models import (
    EntityResolution,
    OntologyOperation,
)

_MAX_IDENTITY_LENGTH = 200
_MAX_ALIASES = 100_000


@dataclass(frozen=True, slots=True)
class EntityRecord:
    identity: str
    object_type: str

    def __post_init__(self) -> None:
        if not self.identity or not self.object_type:
            raise ValueError("entity identity and object_type MUST be non-empty")
        if (
            len(self.identity) > _MAX_IDENTITY_LENGTH
            or len(self.object_type) > _MAX_IDENTITY_LENGTH
        ):
            raise ValueError("entity identity and object_type MUST be bounded")


@dataclass(frozen=True, slots=True)
class EntityAliasRecord:
    alias: str
    identity: str

    def __post_init__(self) -> None:
        if not _normalize_alias(self.alias) or not self.identity:
            raise ValueError("entity alias and identity MUST be non-empty")
        if len(self.alias) > _MAX_IDENTITY_LENGTH or len(self.identity) > _MAX_IDENTITY_LENGTH:
            raise ValueError("entity alias and identity MUST be bounded")


@dataclass(frozen=True, slots=True)
class EntityResolutionRequest:
    supplied_identity: str
    target_type: str
    operation: OntologyOperation

    def __post_init__(self) -> None:
        if not self.supplied_identity or not self.target_type:
            raise ValueError("entity resolution request MUST be non-empty")


def resolve_entity_identity(
    request: EntityResolutionRequest,
    *,
    entities: Sequence[EntityRecord],
    aliases: Sequence[EntityAliasRecord],
) -> EntityResolution:
    """Resolve an exact id or one unique configured alias without fuzzy matching."""
    if len(aliases) > _MAX_ALIASES:
        raise ValueError("entity alias count exceeds the bounded limit")
    entity_ids = {entity.identity for entity in entities}
    if request.supplied_identity in entity_ids:
        return EntityResolution(
            selected_identity=request.supplied_identity,
            candidates=(request.supplied_identity,),
            method="exact",
        )

    normalized = _normalize_alias(request.supplied_identity)
    candidates = tuple(
        sorted(
            {record.identity for record in aliases if _normalize_alias(record.alias) == normalized}
        )
    )
    if len(candidates) == 1:
        return EntityResolution(
            selected_identity=candidates[0],
            candidates=candidates,
            method="alias",
        )
    if candidates:
        return EntityResolution(candidates=candidates, method="ambiguous_alias")
    return EntityResolution(method="unresolved")


def _normalize_alias(value: str) -> str:
    return " ".join(value.split()).casefold()


__all__ = [
    "EntityAliasRecord",
    "EntityRecord",
    "EntityResolutionRequest",
    "resolve_entity_identity",
]
