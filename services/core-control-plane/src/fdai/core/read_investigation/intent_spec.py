"""Single runtime authority for read-investigation intent semantics."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from fdai.shared.providers.read_investigation import ReadInvestigationIntent, ReadToolId


@dataclass(frozen=True, slots=True)
class ReadInvestigationIntentSpec:
    intent: ReadInvestigationIntent
    plan_id: str
    default_tools: tuple[ReadToolId, ...]
    interactive_tools: tuple[ReadToolId, ...]
    lookback_seconds: int

    def __post_init__(self) -> None:
        if not self.plan_id.strip():
            raise ValueError("read investigation plan_id MUST be non-empty")
        if not self.default_tools:
            raise ValueError("read investigation default_tools MUST be non-empty")
        if len(set(self.default_tools)) != len(self.default_tools):
            raise ValueError("read investigation default_tools MUST be unique")
        if len(set(self.interactive_tools)) != len(self.interactive_tools):
            raise ValueError("read investigation interactive_tools MUST be unique")
        if not 60 <= self.lookback_seconds <= 2_592_000:
            raise ValueError("read investigation lookback_seconds MUST be in [60, 2592000]")


_HOUR = 3_600
_THIRTY_DAYS = 30 * 24 * _HOUR

READ_INVESTIGATION_INTENT_SPECS = MappingProxyType(
    {
        ReadInvestigationIntent.RESOURCE_STATE: ReadInvestigationIntentSpec(
            intent=ReadInvestigationIntent.RESOURCE_STATE,
            plan_id="read.resource-state.v1",
            default_tools=(ReadToolId.GET_RESOURCE_STATE,),
            interactive_tools=(),
            lookback_seconds=_HOUR,
        ),
        ReadInvestigationIntent.CHANGE_ATTRIBUTION: ReadInvestigationIntentSpec(
            intent=ReadInvestigationIntent.CHANGE_ATTRIBUTION,
            plan_id="read.change-attribution.v1",
            default_tools=(
                ReadToolId.QUERY_RESOURCE_ACTIVITY,
                ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS,
                ReadToolId.QUERY_RESOURCE_HEALTH,
            ),
            interactive_tools=(ReadToolId.QUERY_RESOURCE_ACTIVITY,),
            lookback_seconds=_THIRTY_DAYS,
        ),
        ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY: ReadInvestigationIntentSpec(
            intent=ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY,
            plan_id="read.resource-change-history.v1",
            default_tools=(ReadToolId.QUERY_RESOURCE_ACTIVITY,),
            interactive_tools=(),
            lookback_seconds=_THIRTY_DAYS,
        ),
        ReadInvestigationIntent.PLATFORM_HEALTH: ReadInvestigationIntentSpec(
            intent=ReadInvestigationIntent.PLATFORM_HEALTH,
            plan_id="read.platform-health.v1",
            default_tools=(ReadToolId.QUERY_RESOURCE_HEALTH,),
            interactive_tools=(),
            lookback_seconds=_HOUR,
        ),
        ReadInvestigationIntent.GUEST_SHUTDOWN: ReadInvestigationIntentSpec(
            intent=ReadInvestigationIntent.GUEST_SHUTDOWN,
            plan_id="read.guest-shutdown.v1",
            default_tools=(ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS,),
            interactive_tools=(),
            lookback_seconds=_HOUR,
        ),
        ReadInvestigationIntent.NETWORK_SECURITY: ReadInvestigationIntentSpec(
            intent=ReadInvestigationIntent.NETWORK_SECURITY,
            plan_id="read.network-security.v1",
            default_tools=(ReadToolId.QUERY_NETWORK_SECURITY,),
            interactive_tools=(),
            lookback_seconds=_HOUR,
        ),
        ReadInvestigationIntent.NETWORK_PEERING: ReadInvestigationIntentSpec(
            intent=ReadInvestigationIntent.NETWORK_PEERING,
            plan_id="read.network-peering.v1",
            default_tools=(ReadToolId.QUERY_NETWORK_PEERINGS,),
            interactive_tools=(),
            lookback_seconds=_HOUR,
        ),
    }
)

if set(READ_INVESTIGATION_INTENT_SPECS) != set(ReadInvestigationIntent):
    raise RuntimeError("read investigation intent specs do not cover the runtime enum")


def read_investigation_intent_spec(
    intent: ReadInvestigationIntent,
) -> ReadInvestigationIntentSpec:
    return READ_INVESTIGATION_INTENT_SPECS[intent]


__all__ = [
    "READ_INVESTIGATION_INTENT_SPECS",
    "ReadInvestigationIntentSpec",
    "read_investigation_intent_spec",
]
