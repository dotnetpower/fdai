"""Provider-neutral capability-state contract for A2/A4 notification channels.

Separates ``available`` (prerequisites observed complete), ``enabled``
(operator preference), ``configured`` (startup-validated wiring present),
and ``mode`` (authority axis: shadow vs enforce) per
[coding-conventions.instructions.md § Safety]
(../../../../../../.github/instructions/coding-conventions.instructions.md#safety):
"Capability flags MUST separate `available`, `enabled`, and authority /
`mode`."

This is a read-only projection type: constructing or reading one performs no
I/O and mutates nothing. It never substitutes for the router's own target
selection (`Declared ∩ Enabled ∩ Configured ∩ TrustAllowed` in
`docs/roadmap/interfaces/multi-channel-notification-delivery.md § 1`); a
capability state is evidence a composition root or Settings surface reads,
never a health probe consulted at send time.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .base import require_channel_id


class ChannelMode(StrEnum):
    """Authority axis for one channel binding - never a health signal.

    ``SHADOW`` MUST NOT invoke network transport - see
    :class:`fdai.core.notifications.shadow.ShadowNotificationChannel`. Only
    an explicit, separately reviewed promotion moves a binding to
    ``ENFORCE`` (constitution principle 7: "New capabilities start in shadow
    mode... Promotion to enforce is explicit, per-action.").
    """

    SHADOW = "shadow"
    ENFORCE = "enforce"


@dataclass(frozen=True, slots=True)
class ChannelCapabilityState:
    """One channel binding's availability, preference, and authority.

    - ``available``: prerequisites/configuration this process could observe
      are complete (mirrors a `ready` readiness row, never a live probe).
    - ``enabled``: operator preference, independent of availability.
    - ``configured``: startup-validated wiring is present.
    - ``mode``: :class:`ChannelMode`; ``mode`` never raises autonomy by
      itself - composition still gates the target set on the other three
      fields exactly as it does today.
    """

    channel_id: str
    available: bool
    enabled: bool
    configured: bool
    mode: ChannelMode = ChannelMode.SHADOW

    def __post_init__(self) -> None:
        require_channel_id(self.channel_id)

    @property
    def ready(self) -> bool:
        """Whether this binding is eligible to be part of a live target set."""
        return self.available and self.enabled and self.configured

    def to_readiness_row(self, *, source: str) -> dict[str, object]:
        """Render the source-attributed shape used by the Settings readiness
        projection (see `fdai.delivery.integration_readiness.integration_row`),
        so a capability-state instance and that projection never report a
        different vocabulary for the same channel. Pure and read-only."""
        return {
            "key": self.channel_id,
            "source": source,
            "observed": True,
            "configured": self.configured,
            "ready": self.ready,
            "mode": self.mode.value if self.ready else "disabled",
            "reason": None if self.ready else _unready_reason(self),
        }


def _unready_reason(state: ChannelCapabilityState) -> str:
    if not state.available:
        return "prerequisites are incomplete"
    if not state.enabled:
        return "disabled by operator"
    if not state.configured:
        return "configuration is invalid"
    return "not ready"


__all__ = ["ChannelCapabilityState", "ChannelMode"]
