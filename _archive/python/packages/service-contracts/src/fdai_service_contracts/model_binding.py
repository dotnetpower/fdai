"""Authority-free environment model binding policy shared by Operator and Core."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

_CAPABILITY = re.compile(r"^(t1|t2)\.[a-z][a-z0-9._-]{1,63}$")
_PUBLISHER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
_FAMILY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
_MAX_CAPACITY = 10_000_000


class ModelSelectionMode(StrEnum):
    """Supported environment binding postures."""

    AUTO = "auto"
    PINNED = "pinned"
    HIL_ONLY = "hil-only"


class ModelSku(StrEnum):
    """Supported Azure OpenAI deployment SKU names."""

    STANDARD = "Standard"
    GLOBAL_STANDARD = "GlobalStandard"
    PROVISIONED_MANAGED = "ProvisionedManaged"
    GLOBAL_PROVISIONED_MANAGED = "GlobalProvisionedManaged"
    DATA_ZONE_PROVISIONED_MANAGED = "DataZoneProvisionedManaged"

    @property
    def is_provisioned(self) -> bool:
        return self in {
            ModelSku.PROVISIONED_MANAGED,
            ModelSku.GLOBAL_PROVISIONED_MANAGED,
            ModelSku.DATA_ZONE_PROVISIONED_MANAGED,
        }


class ModelBindingCapacity(BaseModel):
    """One explicit TPM or PTU request for a pinned capability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit: Literal["tpm", "ptu"]
    value: Annotated[int, Field(ge=1, le=_MAX_CAPACITY)]


class CapabilityBindingPolicy(BaseModel):
    """One capability's requested selection posture without activation authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    selection_mode: ModelSelectionMode
    publisher: Annotated[str, Field(pattern=_PUBLISHER_PATTERN)] | None = None
    family: Annotated[str, Field(pattern=_FAMILY_PATTERN)] | None = None
    version_policy: Literal["latest-compatible"] | None = None
    sku: ModelSku | None = None
    capacity: ModelBindingCapacity | None = None

    @model_validator(mode="after")
    def _validate_mode_shape(self) -> CapabilityBindingPolicy:
        pinned_fields = (
            self.publisher,
            self.family,
            self.version_policy,
            self.sku,
            self.capacity,
        )
        if self.selection_mode is not ModelSelectionMode.PINNED:
            if any(value is not None for value in pinned_fields):
                raise ValueError("auto and hil-only policies cannot declare pinned fields")
            return self
        if any(value is None for value in pinned_fields):
            raise ValueError("pinned policy requires publisher, family, version, SKU, and capacity")
        sku = cast(ModelSku, self.sku)
        capacity = cast(ModelBindingCapacity, self.capacity)
        expected_unit = "ptu" if sku.is_provisioned else "tpm"
        if capacity.unit != expected_unit:
            raise ValueError(f"{sku.value} requires {expected_unit} capacity")
        if capacity.unit == "tpm" and capacity.value < 1_000:
            raise ValueError("pinned TPM capacity MUST be at least 1000")
        return self


class ModelBindingPolicy(BaseModel):
    """Revisioned capability intent for one deployment environment."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    environment: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")]
    revision: Annotated[int, Field(ge=1)]
    expected_active_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")] | None = None
    capabilities: dict[str, CapabilityBindingPolicy]

    @model_validator(mode="after")
    def _validate_capability_names(self) -> ModelBindingPolicy:
        if not self.capabilities:
            raise ValueError("model binding policy requires at least one capability")
        if len(self.capabilities) > 64:
            raise ValueError("model binding policy supports at most 64 capabilities")
        invalid = sorted(name for name in self.capabilities if _CAPABILITY.fullmatch(name) is None)
        if invalid:
            raise ValueError(f"invalid model binding capability names: {invalid}")
        return self

    def digest(self) -> str:
        """Return a stable content digest for plan and audit binding."""
        payload = self.model_dump(mode="json", exclude_none=True)
        canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return "sha256:" + hashlib.sha256(canonical).hexdigest()


__all__ = [
    "CapabilityBindingPolicy",
    "ModelBindingCapacity",
    "ModelBindingPolicy",
    "ModelSelectionMode",
    "ModelSku",
]
