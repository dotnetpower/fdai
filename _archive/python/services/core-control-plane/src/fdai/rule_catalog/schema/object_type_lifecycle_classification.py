"""Machine-readable authority classification for lifecycle-free ObjectTypes."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai.shared.contracts.models import OntologyObjectType


class ObjectTypeLifecycleClassification(StrEnum):
    """Reviewed authority class for an ObjectType without lifecycle ownership."""

    CATALOG_AS_CODE = "catalog_as_code"
    EVENT_BUS_REGISTRY = "event_bus_registry"
    PROJECTION_OWNED = "projection_owned"
    OWNER_REQUIRED = "owner_required"


class ObjectTypeLifecycleClassificationGroup(BaseModel):
    """One classification group with a shared review rationale."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rationale: Annotated[str, Field(min_length=20, max_length=500)]
    source_refs: tuple[Annotated[str, Field(min_length=1, max_length=512)], ...]
    object_types: tuple[Annotated[str, Field(pattern=r"^[A-Z][A-Za-z0-9]{0,127}$")], ...]

    @model_validator(mode="after")
    def _canonical_values(self) -> ObjectTypeLifecycleClassificationGroup:
        if tuple(sorted(set(self.source_refs))) != self.source_refs:
            raise ValueError("classification source_refs MUST be sorted and unique")
        if tuple(sorted(set(self.object_types))) != self.object_types:
            raise ValueError("classification object_types MUST be sorted and unique")
        return self


class ObjectTypeLifecycleClassificationRegistry(BaseModel):
    """Complete exact classification of every lifecycle-free ObjectType."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=r"^1\.0\.0$")] = "1.0.0"
    categories: dict[
        ObjectTypeLifecycleClassification,
        ObjectTypeLifecycleClassificationGroup,
    ]

    @model_validator(mode="after")
    def _complete_categories(self) -> ObjectTypeLifecycleClassificationRegistry:
        expected = set(ObjectTypeLifecycleClassification)
        if set(self.categories) != expected:
            missing = sorted(item.value for item in expected - set(self.categories))
            extra = sorted(str(item) for item in set(self.categories) - expected)
            raise ValueError(
                f"classification categories MUST be complete; missing={missing}, extra={extra}"
            )
        names = [
            name
            for classification in ObjectTypeLifecycleClassification
            for name in self.categories[classification].object_types
        ]
        if len(names) != len(set(names)):
            raise ValueError("an ObjectType MUST appear in exactly one classification")
        return self

    def classified_names(self) -> frozenset[str]:
        """Return every classified ObjectType name."""

        return frozenset(name for group in self.categories.values() for name in group.object_types)


def load_object_type_lifecycle_classification_registry(
    path: Path,
    *,
    object_types: tuple[OntologyObjectType, ...],
) -> ObjectTypeLifecycleClassificationRegistry:
    """Load the registry and require exact parity with lifecycle-free declarations."""

    lifecycle_free = frozenset(item.name for item in object_types if item.lifecycle is None)
    if not path.is_file():
        if lifecycle_free:
            raise ValueError(
                "lifecycle-free ObjectTypes require object-type-lifecycle-classification.yaml"
            )
        return ObjectTypeLifecycleClassificationRegistry(
            categories={
                classification: ObjectTypeLifecycleClassificationGroup(
                    rationale="No lifecycle-free ObjectTypes are present in this catalog.",
                    source_refs=("docs/roadmap/architecture/operating-ontology.md",),
                    object_types=(),
                )
                for classification in ObjectTypeLifecycleClassification
            }
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("invalid ObjectType lifecycle classification registry") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("ObjectType lifecycle classification registry MUST be a mapping")
    registry = ObjectTypeLifecycleClassificationRegistry.model_validate(dict(raw))
    classified = registry.classified_names()
    if classified != lifecycle_free:
        missing = sorted(lifecycle_free - classified)
        extra = sorted(classified - lifecycle_free)
        raise ValueError(
            "ObjectType lifecycle classification MUST match lifecycle-free declarations; "
            f"missing={missing}, extra={extra}"
        )
    return registry


__all__ = [
    "ObjectTypeLifecycleClassification",
    "ObjectTypeLifecycleClassificationGroup",
    "ObjectTypeLifecycleClassificationRegistry",
    "load_object_type_lifecycle_classification_registry",
]
