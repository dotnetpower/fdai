"""Provider-neutral structured availability policy shared by Settings boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

RESOURCE_AVAILABILITY_SETTING_KEY = "detection.resource_availability"
RESOURCE_AVAILABILITY_RESOURCE_TYPES = frozenset(
    {
        "compute.vm",
        "compute.web-app",
        "compute.function",
        "compute.container-app",
        "kubernetes-cluster",
        "kubernetes-node-pool",
        "mysql-server",
        "network.application-gateway",
    }
)
DEFAULT_RESOURCE_AVAILABILITY_SETTINGS: Mapping[str, object] = {
    "enabled": False,
    "resource_types": [],
    "max_age_seconds": 300.0,
    "resources": {},
}
_Reference = Annotated[
    str,
    StringConstraints(
        pattern=r"^(policy|maintenance|change|settings):[A-Za-z0-9._:-]+$",
        max_length=448,
    ),
]


class AvailabilityPlannedStopSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    since: AwareDatetime
    until: AwareDatetime
    reference: _Reference
    maintenance: StrictBool = False

    @model_validator(mode="after")
    def _ordered(self) -> AvailabilityPlannedStopSettings:
        if self.since >= self.until:
            raise ValueError("planned stop window MUST be positive")
        return self


class AvailabilityResourcePolicySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_type: StrictStr
    reference: _Reference
    expected_state: Literal["running", "stopped"] | None = None
    planned_stops: tuple[AvailabilityPlannedStopSettings, ...] = Field(
        default=(),
        max_length=64,
    )


class ResourceAvailabilitySettings(BaseModel):
    """One exact-key structured setting; never an action or authorization setting."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: StrictBool = False
    resource_types: tuple[StrictStr, ...] = Field(default=(), max_length=32)
    max_age_seconds: float = Field(
        default=300.0,
        gt=0,
        le=86_400,
        strict=True,
        allow_inf_nan=False,
    )
    resources: dict[str, AvailabilityResourcePolicySettings] = Field(
        default_factory=dict,
        max_length=1000,
    )

    @model_validator(mode="after")
    def _explicit_scope(self) -> ResourceAvailabilitySettings:
        selected = frozenset(self.resource_types)
        if (
            len(selected) != len(self.resource_types)
            or not selected <= RESOURCE_AVAILABILITY_RESOURCE_TYPES
            or (self.enabled and not selected)
        ):
            raise ValueError("availability monitoring MUST select unique supported resource types")
        for resource_ref, policy in self.resources.items():
            if (
                not resource_ref.strip()
                or len(resource_ref) > 512
                or resource_ref.startswith("/")
                or "://" in resource_ref
                or policy.resource_type not in selected
            ):
                raise ValueError(
                    "availability policy MUST bind a logical resource and selected type"
                )
        return self


def validate_resource_availability_setting(value: object) -> dict[str, object]:
    """Validate without storage/provider imports; return JSON-native Settings values."""

    try:
        settings = ResourceAvailabilitySettings.model_validate(value)
    except ValidationError:
        raise ValueError("resource availability setting is invalid") from None
    return settings.model_dump(mode="json")
