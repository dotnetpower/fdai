"""Server-owned catalog for the five bounded investigation tools."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fdai.shared.providers.read_investigation import ReadToolId


class LatencyClass(StrEnum):
    FAST = "fast"
    STANDARD = "standard"
    SLOW = "slow"


@dataclass(frozen=True, slots=True)
class ReadToolSpec:
    tool_id: ReadToolId
    operation_class: str
    timeout_seconds: float
    max_results: int
    max_output_bytes: int
    latency_class: LatencyClass
    required_role: str = "Reader"
    side_effect_class: str = "read"
    query_template_owner: str = "server"

    def __post_init__(self) -> None:
        if self.required_role != "Reader":
            raise ValueError("investigation tools require Reader RBAC")
        if self.side_effect_class != "read":
            raise ValueError("investigation tools MUST be read-only")
        if self.query_template_owner != "server":
            raise ValueError("investigation query templates MUST be server-owned")


READ_TOOL_SPECS: tuple[ReadToolSpec, ...] = (
    ReadToolSpec(
        ReadToolId.RESOLVE_RESOURCE,
        "resource_resolution",
        10.0,
        8,
        64_000,
        LatencyClass.FAST,
    ),
    ReadToolSpec(
        ReadToolId.GET_RESOURCE_STATE,
        "resource_state",
        10.0,
        8,
        64_000,
        LatencyClass.FAST,
    ),
    ReadToolSpec(
        ReadToolId.QUERY_RESOURCE_ACTIVITY,
        "control_plane_activity",
        30.0,
        32,
        256_000,
        LatencyClass.STANDARD,
    ),
    ReadToolSpec(
        ReadToolId.QUERY_RESOURCE_HEALTH,
        "platform_health",
        20.0,
        16,
        128_000,
        LatencyClass.STANDARD,
    ),
    ReadToolSpec(
        ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS,
        "guest_shutdown",
        45.0,
        32,
        256_000,
        LatencyClass.SLOW,
    ),
)

_BY_ID = {spec.tool_id: spec for spec in READ_TOOL_SPECS}


def read_tool_spec(tool_id: ReadToolId) -> ReadToolSpec:
    return _BY_ID[tool_id]


__all__ = ["LatencyClass", "READ_TOOL_SPECS", "ReadToolSpec", "read_tool_spec"]
