"""Trajectory schema compatibility policy."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.core.trajectory.models import TRAJECTORY_SCHEMA_VERSION


class TrajectorySchemaCompatibilityError(ValueError):
    """Raised when an export version is unsupported or incompatible."""


@dataclass(frozen=True, slots=True)
class TrajectoryVersionPolicy:
    """Accept the current major and explicitly listed older minor versions."""

    current: str = TRAJECTORY_SCHEMA_VERSION
    readable: tuple[str, ...] = (TRAJECTORY_SCHEMA_VERSION,)

    def __post_init__(self) -> None:
        if self.current not in self.readable:
            raise ValueError("current trajectory schema version MUST be readable")
        current_major = _parts(self.current)[0]
        if any(_parts(version)[0] != current_major for version in self.readable):
            raise ValueError("readable trajectory versions MUST share the current major")

    def require_readable(self, version: str) -> None:
        if version not in self.readable:
            raise TrajectorySchemaCompatibilityError(
                f"trajectory schema version is not readable: {version}"
            )

    def require_current(self, version: str) -> None:
        if version != self.current:
            raise TrajectorySchemaCompatibilityError(
                f"trajectory schema version is not current: {version}"
            )


def _parts(version: str) -> tuple[int, int]:
    try:
        major, minor = version.split(".", maxsplit=1)
        return int(major), int(minor)
    except (TypeError, ValueError) as exc:
        raise ValueError("trajectory schema version MUST use major.minor integers") from exc


__all__ = ["TrajectorySchemaCompatibilityError", "TrajectoryVersionPolicy"]
