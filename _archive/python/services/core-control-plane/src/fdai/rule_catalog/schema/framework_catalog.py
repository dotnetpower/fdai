"""Strict non-authoritative framework-definition catalog."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from fdai.shared.contracts.models import BestPractice

_IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{0,127}$"
_CONTROL_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_RECORD_REF = r"^[a-z0-9][a-z0-9._:-]{0,127}@\d+\.\d+\.\d+$"
_GIT_REF = r"^[a-f0-9]{40}$"
_SHA256 = r"^sha256:[a-f0-9]{64}$"
_UUID = r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"
_VERSION = r"^\d{4}-\d{2}-\d{2}$"


class FrameworkMappingStatus(StrEnum):
    """How a framework control is represented in FDAI."""

    BEST_PRACTICE = "best_practice"
    OBJECTIVE = "objective"
    REFERENCE_ONLY = "reference_only"
    UNMAPPED = "unmapped"


class FrameworkSource(BaseModel):
    """Pinned first-party source for one framework area."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(pattern=_IDENTIFIER)] | None = None
    source_url: HttpUrl
    source_version: Annotated[str, Field(pattern=_VERSION)]
    resolved_ref: Annotated[str, Field(pattern=_GIT_REF)]
    retrieved_at: str


class WaraRecommendationMetadata(BaseModel):
    """Pinned APRL metadata consumed by the WARA analyzer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recommendation_type_id: Annotated[str, Field(pattern=_UUID)] | None = None
    control: Annotated[str, Field(min_length=1, max_length=64)]
    impact: Annotated[str, Field(pattern=r"^(Low|Medium|High)$")]
    resource_type: Annotated[str, Field(min_length=1, max_length=256)]
    state: Annotated[str, Field(pattern=r"^(Active|Disabled)$")]
    product_group_verified: bool
    automation_available: bool
    tags: tuple[Annotated[str, Field(min_length=1, max_length=64)], ...] = ()
    potential_benefits: Annotated[str, Field(min_length=1, max_length=256)]
    learn_more_name: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    learn_more_url: HttpUrl | None = None
    source_path: Annotated[str, Field(min_length=1, max_length=512)]
    source_digest: Annotated[str, Field(pattern=_SHA256)]
    query_digest: Annotated[str, Field(pattern=_SHA256)] | None = None

    @model_validator(mode="after")
    def validate_metadata(self) -> WaraRecommendationMetadata:
        if self.tags != tuple(sorted(set(self.tags))):
            raise ValueError("WARA tags MUST be unique and ordered")
        if (self.learn_more_name is None) != (self.learn_more_url is None):
            raise ValueError("WARA learn-more name and URL MUST be supplied together")
        if self.automation_available and self.state == "Active" and self.query_digest is None:
            raise ValueError("active automated WARA recommendation requires query_digest")
        return self


class FrameworkControl(BaseModel):
    """One non-authoritative framework recommendation or methodology area."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(pattern=_CONTROL_IDENTIFIER)]
    title: Annotated[str, Field(min_length=1, max_length=256)]
    description: Annotated[str, Field(min_length=1, max_length=2048)] | None = None
    best_practice_ref: Annotated[str, Field(pattern=_RECORD_REF)] | None = None
    objective_refs: tuple[Annotated[str, Field(pattern=_RECORD_REF)], ...] = ()
    mapping_status: FrameworkMappingStatus
    applicability: Annotated[str, Field(pattern=_IDENTIFIER)] | None = None
    source_url: HttpUrl | None = None
    source_version: Annotated[str, Field(pattern=_VERSION)] | None = None
    resolved_ref: Annotated[str, Field(pattern=_GIT_REF)] | None = None
    retrieved_at: str | None = None
    wara: WaraRecommendationMetadata | None = None

    @model_validator(mode="after")
    def validate_mapping(self) -> FrameworkControl:
        if self.objective_refs != tuple(sorted(set(self.objective_refs))):
            raise ValueError("objective_refs MUST be unique and ordered")
        if self.mapping_status is FrameworkMappingStatus.BEST_PRACTICE:
            if self.best_practice_ref is None:
                raise ValueError("best_practice mapping requires best_practice_ref")
        elif self.best_practice_ref is not None:
            raise ValueError("only best_practice mapping may set best_practice_ref")
        if self.mapping_status is FrameworkMappingStatus.OBJECTIVE and not self.objective_refs:
            raise ValueError("objective mapping requires objective_refs")
        source_fields = (
            self.source_url,
            self.source_version,
            self.resolved_ref,
            self.retrieved_at,
        )
        if any(item is not None for item in source_fields) and not all(
            item is not None for item in source_fields
        ):
            raise ValueError("inline control source fields MUST be supplied together")
        return self


class FrameworkArea(FrameworkSource):
    """Pinned framework area containing coded controls."""

    source_path: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    source_digest: Annotated[str, Field(pattern=_SHA256)] | None = None
    controls: tuple[FrameworkControl, ...] = Field(min_length=1)


class FrameworkInventory(BaseModel):
    """Deterministic completeness accounting for a framework snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_controls: int = Field(ge=1)
    active_controls: int = Field(ge=0)
    disabled_controls: int = Field(ge=0)
    area_count: int = Field(ge=1)
    resource_type_count: int = Field(ge=0)
    automated_active_controls: int = Field(ge=0)
    product_group_verified_active_controls: int = Field(ge=0)
    published_active_digest: Annotated[str, Field(pattern=_SHA256)] | None = None
    source_set_digest: Annotated[str, Field(pattern=_SHA256)]

    @model_validator(mode="after")
    def validate_counts(self) -> FrameworkInventory:
        if self.active_controls + self.disabled_controls != self.total_controls:
            raise ValueError("active and disabled counts MUST equal total_controls")
        if self.automated_active_controls > self.active_controls:
            raise ValueError("automated_active_controls exceeds active_controls")
        if self.product_group_verified_active_controls > self.active_controls:
            raise ValueError("product_group_verified_active_controls exceeds active_controls")
        return self


class FrameworkDefinition(BaseModel):
    """Version-pinned framework surface that grants no decision authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    kind: str
    id: Annotated[str, Field(pattern=_IDENTIFIER)]
    version: Annotated[str, Field(pattern=_VERSION)]
    name: Annotated[str, Field(min_length=1, max_length=256)]
    scope: Annotated[str, Field(pattern=_IDENTIFIER)]
    advisory: bool
    completeness_scope: Annotated[str, Field(min_length=1, max_length=2048)]
    inventory: FrameworkInventory | None = None
    areas: tuple[FrameworkArea, ...] = ()
    sources: tuple[FrameworkSource, ...] = ()
    controls: tuple[FrameworkControl, ...] = ()

    @model_validator(mode="after")
    def validate_definition(self) -> FrameworkDefinition:
        if self.kind != "framework-definition":
            raise ValueError("kind MUST be framework-definition")
        if not self.advisory:
            raise ValueError("framework definitions MUST remain advisory")
        if not self.areas and not self.controls:
            raise ValueError("framework definition requires areas or controls")
        area_ids = tuple(area.id for area in self.areas)
        if len(area_ids) != len(set(area_ids)):
            raise ValueError("framework area ids MUST be unique")
        source_ids = tuple(item.id for item in self.sources)
        if any(item is None for item in source_ids):
            raise ValueError("top-level sources require ids")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source ids MUST be unique")
        control_ids = tuple(item.control.id for item in self.resolved_controls())
        if len(control_ids) != len(set(control_ids)):
            raise ValueError("framework control ids MUST be unique")
        if self.inventory is not None:
            if self.inventory.total_controls != len(control_ids):
                raise ValueError("framework inventory total does not match controls")
            if self.inventory.area_count != len(self.areas):
                raise ValueError("framework inventory area count does not match areas")
            source_set = [
                (area.source_path, area.source_digest)
                for area in self.areas
                if area.source_path is not None and area.source_digest is not None
            ]
            if len(source_set) != len(self.areas):
                raise ValueError("inventoried framework areas require source path and digest")
            encoded = json.dumps(
                sorted(source_set),
                separators=(",", ":"),
            ).encode("utf-8")
            expected_digest = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
            if self.inventory.source_set_digest != expected_digest:
                raise ValueError("framework inventory source_set_digest mismatch")
        return self

    def resolved_controls(self) -> tuple[ResolvedFrameworkControl, ...]:
        resolved = [
            ResolvedFrameworkControl(
                area=None,
                control=control,
                source_url=str(control.source_url),
                source_version=control.source_version or "",
                resolved_ref=control.resolved_ref or "",
                retrieved_at=control.retrieved_at or "",
            )
            for control in self.controls
        ]
        resolved.extend(
            ResolvedFrameworkControl(
                area=area.id,
                control=control,
                source_url=str(area.source_url),
                source_version=area.source_version,
                resolved_ref=area.resolved_ref,
                retrieved_at=area.retrieved_at,
            )
            for area in self.areas
            for control in area.controls
        )
        return tuple(resolved)


@dataclass(frozen=True, slots=True)
class ResolvedFrameworkControl:
    """A framework control with its inherited source identity resolved."""

    area: str | None
    control: FrameworkControl
    source_url: str
    source_version: str
    resolved_ref: str
    retrieved_at: str


def load_framework_catalog(
    root: Path,
    *,
    best_practices: tuple[BestPractice, ...] = (),
    objective_refs: frozenset[str] = frozenset(),
    additional_roots: tuple[Path, ...] = (),
) -> tuple[FrameworkDefinition, ...]:
    """Load framework definitions and validate all optional mappings."""

    roots = (root, *additional_roots)
    for catalog_root in roots:
        if not catalog_root.is_dir():
            raise FileNotFoundError(f"framework catalog root not a directory: {catalog_root}")
    definitions: list[FrameworkDefinition] = []
    seen: set[str] = set()
    best_by_ref = {f"{item.id}@{item.version}": item for item in best_practices}
    paths = sorted(
        (
            path
            for catalog_root in roots
            for pattern in ("*.yaml", "*.json")
            for path in catalog_root.glob(pattern)
        ),
        key=lambda path: str(path),
    )
    for path in paths:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        definition = FrameworkDefinition.model_validate(raw)
        if path.stem != definition.id:
            raise ValueError(f"{path.name}: file stem MUST equal framework id {definition.id!r}")
        if definition.id in seen:
            raise ValueError(f"{path.name}: duplicate framework id {definition.id!r}")
        seen.add(definition.id)
        for resolved in definition.resolved_controls():
            control = resolved.control
            if control.best_practice_ref is not None:
                best_practice = best_by_ref.get(control.best_practice_ref)
                if best_practice is None:
                    raise ValueError(
                        f"{path.name}:{control.id}: unknown best_practice_ref "
                        f"{control.best_practice_ref!r}"
                    )
                if best_practice.framework != definition.id:
                    raise ValueError(f"{path.name}:{control.id}: best practice framework mismatch")
                if best_practice.control_id != control.id:
                    raise ValueError(f"{path.name}:{control.id}: best practice control id mismatch")
                provenance = best_practice.provenance
                if (
                    provenance.source_url != resolved.source_url
                    or provenance.source_version != resolved.source_version
                    or provenance.resolved_ref != resolved.resolved_ref
                ):
                    raise ValueError(
                        f"{path.name}:{control.id}: best practice provenance differs "
                        "from the pinned framework source"
                    )
            unknown_objectives = sorted(set(control.objective_refs) - objective_refs)
            if unknown_objectives:
                raise ValueError(
                    f"{path.name}:{control.id}: unknown objective refs {unknown_objectives}"
                )
        definitions.append(definition)
    return tuple(definitions)


__all__ = [
    "FrameworkControl",
    "FrameworkDefinition",
    "FrameworkMappingStatus",
    "FrameworkSource",
    "ResolvedFrameworkControl",
    "load_framework_catalog",
]
