"""Shared pydantic base for workflow catalog contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

SemVer = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$", min_length=5)]


class WorkflowCatalogBase(BaseModel):
    """Base whose config matches Core's historical contract model base."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


__all__ = ["SemVer", "WorkflowCatalogBase"]
