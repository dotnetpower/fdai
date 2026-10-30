"""Severity-based assessment preferences, independent of execution authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class ControlSeverity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


def control_severity(value: str) -> ControlSeverity:
    normalized = value.casefold()
    return ControlSeverity("informational" if normalized == "info" else normalized)


@dataclass(frozen=True, slots=True)
class ControlEnablement:
    severity: ControlSeverity
    default_enabled: bool
    enabled: bool
    source: Literal["severity_default", "profile_override", "lifecycle_disabled"]

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity.value,
            "default_enabled": self.default_enabled,
            "enabled": self.enabled,
            "source": self.source,
            "mode": "shadow",
            "execution_authority": False,
        }


def resolve_control_enablement(
    severity: str,
    *,
    enabled: bool | None = None,
    active: bool = True,
) -> ControlEnablement:
    if enabled is not None and type(enabled) is not bool:
        raise ValueError("control enablement override MUST be a boolean")
    if type(active) is not bool:
        raise ValueError("control lifecycle state MUST be a boolean")
    priority = control_severity(severity)
    default = priority in {
        ControlSeverity.CRITICAL,
        ControlSeverity.HIGH,
        ControlSeverity.MEDIUM,
    }
    return ControlEnablement(
        severity=priority,
        default_enabled=default,
        enabled=active and (default if enabled is None else enabled),
        source=(
            "lifecycle_disabled"
            if not active
            else "profile_override"
            if enabled is not None
            else "severity_default"
        ),
    )
