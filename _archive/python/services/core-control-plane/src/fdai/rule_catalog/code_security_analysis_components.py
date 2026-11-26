"""Strict component and license inventory for the owned analysis engine."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from fdai.rule_catalog.code_security import CodeSecurityCatalogError


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AnalysisComponent(_Strict):
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9.-]{2,127}$")]
    version: Annotated[str, Field(min_length=1, max_length=64)]
    purpose: Annotated[str, Field(min_length=10, max_length=200)]
    status: Literal["active", "planned", "research_only"]
    source_url: Annotated[str, Field(pattern=r"^https://[^\s]+$")]
    license: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9.+-]{1,127}$")]
    redistribution: Literal["embeddable", "reference_only"]
    integration: Literal["stdlib", "library", "process", "research"]

    @model_validator(mode="after")
    def _status_matches_terms(self) -> AnalysisComponent:
        if self.status == "active" and (
            self.version == "unselected" or self.license == "LicenseRef-review-required"
        ):
            raise ValueError("active component requires a selected version and reviewed license")
        if self.status == "research_only" and self.redistribution != "reference_only":
            raise ValueError("research-only component must remain reference-only")
        if self.integration == "research" and self.status != "research_only":
            raise ValueError("research integration requires research-only status")
        return self


class AnalysisComponentInventory(_Strict):
    schema_version: Literal["1.0.0"]
    inventory_id: Literal["fdai.code-security.analysis-components"]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    components: Annotated[tuple[AnalysisComponent, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _unique_components(self) -> AnalysisComponentInventory:
        identities = [component.id for component in self.components]
        if len(identities) != len(set(identities)):
            raise ValueError("analysis component ids must be unique")
        return self


def load_analysis_components(root: Path) -> AnalysisComponentInventory:
    """Load the pinned component inventory or fail closed."""
    try:
        return AnalysisComponentInventory.model_validate(
            yaml.safe_load((root / "analysis-components.yaml").read_text(encoding="utf-8"))
        )
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise CodeSecurityCatalogError(f"invalid analysis component inventory: {exc}") from exc


__all__ = [
    "AnalysisComponent",
    "AnalysisComponentInventory",
    "load_analysis_components",
]
