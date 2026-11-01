"""Load and resolve the complete 420-entry Azure Resource Graph relationship mapping catalog.

Combines the 119 curated ``azure-arg-v1.yaml`` relationship mappings with 301
extended ARM property-reference relationship mappings across all 156 canonical
ResourceTypes (total 420 mappings). Read-only topology metadata only.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from fdai.delivery.repo_assets import repo_asset_root

_REL_CATALOG_REL_PATH: Final[Path] = Path(
    "rule-catalog/collected/azure-arg/relationship-mappings.json"
)
_ALLOWED_LINK_TYPES: Final[frozenset[str]] = frozenset(
    {"contains", "attached_to", "depends_on", "routes_to", "authenticates_with"}
)


@dataclass(frozen=True, slots=True)
class ArgRelationshipMappingSpec:
    """One declarative ARM property-path relationship mapping."""

    mapping_id: str
    source_provider_type: str
    target_provider_type: str
    source_property_path: str
    link_type: str
    origin: str

    def __post_init__(self) -> None:
        if (
            not self.mapping_id.strip()
            or not self.source_provider_type.strip()
            or not self.target_provider_type.strip()
            or not self.source_property_path.strip()
            or not self.origin.strip()
        ):
            raise ValueError("ArgRelationshipMappingSpec text fields MUST be non-empty")
        if self.link_type not in _ALLOWED_LINK_TYPES:
            raise ValueError(f"Unsupported link_type: {self.link_type!r}")


@dataclass(frozen=True, slots=True)
class ArgRelationshipMappingCatalog:
    """In-memory index over all 420 Azure Resource Graph relationship mappings."""

    mappings: Mapping[str, ArgRelationshipMappingSpec]
    by_source_type: Mapping[str, tuple[ArgRelationshipMappingSpec, ...]]
    base_mappings_count: int
    extended_mappings_count: int

    @property
    def total_mappings(self) -> int:
        return len(self.mappings)

    def mappings_for_source_type(
        self, source_provider_type: str
    ) -> tuple[ArgRelationshipMappingSpec, ...]:
        clean = (
            source_provider_type.strip().lower() if isinstance(source_provider_type, str) else ""
        )
        return self.by_source_type.get(clean, ())


@functools.lru_cache(maxsize=2)
def load_arg_relationship_mapping_catalog(
    repo_root: Path | None = None,
) -> ArgRelationshipMappingCatalog:
    """Load and validate all 420 ARG provider relationship mappings."""
    root = repo_root or repo_asset_root()
    raw: dict[str, Any] = json.loads((root / _REL_CATALOG_REL_PATH).read_text(encoding="utf-8"))
    by_id: dict[str, ArgRelationshipMappingSpec] = {}
    by_src: dict[str, list[ArgRelationshipMappingSpec]] = {}
    for entry in raw.get("mappings", ()):
        spec = ArgRelationshipMappingSpec(
            mapping_id=str(entry["mapping_id"]),
            source_provider_type=str(entry["source_provider_type"]).lower(),
            target_provider_type=str(entry["target_provider_type"]).lower(),
            source_property_path=str(entry["source_property_path"]),
            link_type=str(entry["link_type"]),
            origin=str(entry["origin"]),
        )
        by_id[spec.mapping_id] = spec
        by_src.setdefault(spec.source_provider_type, []).append(spec)
    return ArgRelationshipMappingCatalog(
        mappings=MappingProxyType(by_id),
        by_source_type=MappingProxyType({k: tuple(v) for k, v in by_src.items()}),
        base_mappings_count=int(raw.get("base_mappings_count", 119)),
        extended_mappings_count=int(raw.get("extended_mappings_count", 301)),
    )


__all__ = [
    "ArgRelationshipMappingCatalog",
    "ArgRelationshipMappingSpec",
    "load_arg_relationship_mapping_catalog",
]
