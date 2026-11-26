"""Reviewed provider-region value domain for ``Resource.location``.

The vocabulary lists every region code the inventory adapter can report, plus
``global``. A stated region is grounded by closed choice against this complete
list; display names are context for the choosing model, never a lookup table.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_REGION_ID = r"^[a-z][a-z0-9]{1,63}$"


class ProviderRegion(BaseModel):
    """One provider region code and its display name."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(pattern=_REGION_ID)]
    display_name: Annotated[str, Field(min_length=1, max_length=128)]


class ProviderRegionRegistry(BaseModel):
    """The complete, sorted region list of one provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"]
    version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    provider: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")]
    regions: Annotated[tuple[ProviderRegion, ...], Field(min_length=1, max_length=512)]

    @model_validator(mode="after")
    def _sorted_unique(self) -> ProviderRegionRegistry:
        ids = [item.id for item in self.regions]
        if ids != sorted(set(ids)):
            raise ValueError("provider regions MUST be sorted and unique by id")
        return self


def load_provider_region_registry_from_mapping(raw: Mapping[str, Any]) -> ProviderRegionRegistry:
    """Validate the region vocabulary and return its registry."""

    return ProviderRegionRegistry.model_validate(dict(raw))


__all__ = [
    "ProviderRegion",
    "ProviderRegionRegistry",
    "load_provider_region_registry_from_mapping",
]
